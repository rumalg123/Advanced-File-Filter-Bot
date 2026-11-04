# PH-019: Cancellation-safe semaphore accounting

**Status:** Full code CI passed ([run 40815817623](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40815817623)); staging validation required before Verified. Draft PR #4 remains unmerged.

## Root cause

`SemaphoreManager.acquire()` previously executed its active-counter
decrement in an unconditional outer `finally`, even when cancellation or an
exception occurred *before* `asyncio.Semaphore` was acquired. When an
already-saturated semaphore had waiting tasks cancelled, the counter could
become negative. Metrics could disagree with the actual number of operations
and the resulting monitoring was unreliable.

The previous `queue_length` was calculated from `total_requests -
current_active`, where total_requests is cumulative, so it grew over
time despite an empty wait queue.

Python's recommended asyncio semaphore pattern uses an acquired permit
with `try/finally` release. Cancellation must be allowed to propagate:
https://docs.python.org/3/library/asyncio-sync.html#semaphore
https://docs.python.org/3/library/asyncio-task.html#task-cancellation

## Implementation and invariant

- Each acquisition registers one waiting reservation under the manager lock.
  `queue_length` now measures actual pending waiters instead of lifetime
  request totals.
- Only after `async with semaphore` enters successfully **and** the
  manager metrics lock is acquired do `current_active`, `total_requests`,
  peak concurrency, latency and start-time tracking advance.
- A waiting coroutine cancelled before registration has no counters to
  unwind. A coroutine cancelled while waiting for a permit or while
  waiting to record a *successfully obtained* permit decrements only
  its waiting reservation. The semaphore's own context manager is
  responsible for releasing the actual permit.
- A successfully admitted coroutine decrements `current_active` once in
  the acquired-body `finally`, including body cancellation, normal
  exceptions, timeouts and successful completion. Cancellation propagates
  to the caller.
- Auto-generated monitoring operation IDs use `time.time_ns()` instead
  of millisecond-resolution timestamps to avoid collisions during
  sub-millisecond bursts. The optional caller-provided ID is still
  accepted unchanged.
- `avg_wait_time` continues to track only successful admissions.
  `total_requests` continues to count *successful admissions*; cancelled
  waiters do not inflate either metric.
- `SemaphoreManager.update_limit` and its currently unsafe replacement
  of an in-use semaphore are **explicitly NOT modified by PH-019**.
  PH-020 owns live reconfiguration correctness. Do not hot-reconfigure
  concurrency limits in production until PH-020 is tested.

## Tests

`tests/test_semaphore_cancellation.py` includes:
- Task cancelled before entering the context; no permit or metric changes.
- Task cancelled while contending for the last permit; active holder is
  unaffected and waiting count returns to zero.
- Cancellation while waiting on the manager's internal lock before
  queue registration.
- Cancellation after the semaphore permit is acquired but while waiting
  for metrics registration; no permit leak or false admission.
- Cancellation after entry, normal body exception and `asyncio.timeout`.
- Twelve concurrent contenders with seven cancelled pending waiters;
  peak active never exceeds configured limit and queue drains.
- Multiple sub-millisecond auto-generated operation IDs stay distinct.
- Exact start-time and counter cleanup after each failure path.

## Safety and rollout

No MongoDB, Redis, Telegram API, queue, index, application feature-flag,
configuration or stored document changes. The semaphore admission API
and per-domain limits remain unchanged, so the fix is deployable without
database migration.

- [x] Full Python regression suite, compile/lint, real disposable MongoDB/
      dual Redis and Docker/Compose preflight passed at code SHA `cb333907`
      ([CI run 40815817623](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40815817623)).
- [ ] Inject cancellation and timeouts in isolated staging under high
      Telegram/database load; observe `current_active >= 0`,
      `queue_length >= 0`, `peak_concurrent <= configured limit`
      for each domain **without live limit reconfiguration**.
- [ ] Confirm normal throughput, call-site exception propagation,
      semaphore permits and shutdown behavior are unchanged.
- [ ] Check that previous monitoring consumers tolerate truthful pending
      waiter counts rather than cumulative `queue_length`.
- [ ] Review PH-020 before any hot limit changes.

**Rollback:** revert to the previous approved application image without
data migration or external service changes. It will reintroduce the old
metrics bug on cancelled waiters. Keep PH-019 In review until both CI
and operator staging are confirmed.
