# PH-020: Live semaphore resize without over-admission

**State:** Code CI passed ([run 40816879931](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40816879931)), staging pending; Draft PR #4. No production deployment or database changes.

## Root cause and change

Previously update_limit replaced each asyncio.Semaphore instance. Existing holders continued under the old object while new calls used the new object, permitting concurrency beyond the updated limit and separating waiters from their existing domain budget.

ResizableSemaphore now keeps each semaphore object's identity stable. Resizing adjusts the same permit balance by (new limit - old limit). If the limit shrinks below active operations, negative available permits represent temporary debt. Current operations complete normally, each release repays debt, and a new task can enter only when capacity becomes available. Increasing the limit wakes only as many pending tasks as new permits allow.

PH-019 cancellation-safe current_active and queue_length accounting remains unchanged; update_limit validates positive integers, including rejecting booleans. New domains are supported.

## Runtime compatibility

The implementation subclasses asyncio.Semaphore and overrides locked and release to prevent waking queued tasks while permit balance is negative. It uses the internal _wake_up_next hook, which is CPython implementation-specific. Run the focused and full regression suite whenever changing supported Python versions. The asyncio synchronization API is single-event-loop, not thread-safe.

Official documentation: https://docs.python.org/3/library/asyncio-sync.html#semaphore

## Tests

tests/test_semaphore_resize.py verifies shrinking 3 to 1 with holders and queued tasks, growing 1 to 3 without replacing waiters, cancellation during permit debt, repeated resize under 20 contenders, timeouts, invalid limits and new domains. The previous PH-019 cancellation tests must also pass.

## Acceptance gates

- [x] Full Python suite, ephemeral MongoDB/dual Redis, compile/lint and Docker preflight passed at code SHA `ba5acbfd` ([run 40816879931](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40816879931)). The first run found that lazy-created domains still used the old semaphore class; corrected before the green run.
- [ ] Isolated staging exercise while holders are active: both growing and shrinking, queued work, cancellations and failure paths.
- [ ] Verify no new admission during debt, no leaked permits, and accurate active/queue metrics. Active work admitted under an earlier higher limit can temporarily exceed the newly lowered limit; it must not be cancelled or supplemented by new work.
- [ ] Review all Python runtime upgrades against the internal semaphore hook. Multiple processes have independent limits.
- [ ] Verify rollback: prior image restores the unsafe hot-resize behavior, so avoid live limit changes after rollback.

No index, schema, Redis, Telegram callback or feature-flag changes. PH-024 Telegram FloodWait behavior remains separate. PH-020 stays In review until CI and staging acceptance.