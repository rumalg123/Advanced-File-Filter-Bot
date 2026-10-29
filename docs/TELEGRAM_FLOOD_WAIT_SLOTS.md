# PH-024: Telegram retry delays must not hold concurrency slots

**Status:** Code CI passed ([run 40820968179](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40820968179)) on SHA `89fadb57`, staging pending. Existing hardening branch / Draft PR #4. No production changes.

## Failure

Previously `TelegramAPIWrapper.call_api()` acquired the `telegram_send` semaphore once, then `_execute_with_retry()` slept inside that context during Telegram FloodWait and HTTP 5xx backoff. Ten requests with long FloodWait could occupy all ten default send slots while doing no work, starving unrelated messages. PH-019/020 fixed semaphore metrics and resizing but not this slot-holding problem.

## Implemented design

- **Acquire per network attempt**, not per full retry sequence. After a FloodWait/5xx error, the semaphore context exits first, releasing its permit. Awaiting the required delay happens **outside** all semaphore acquisitions. Cancellation also leaves no held permit.
- **Honor Telegram's retry-after** stored in `FloodWait.value`. Retry attempts share bounded *monotonic* cooldown deadlines, plus jitter. Exhaustion propagates the original FloodWait with its actual delay, rather than raising a fabricated 60-second exception.
- **Scope:** for send operations with a specified `chat_id`, maintain a per-chat cooldown so a wait does not occupy slots or unnecessarily stall distinct chats. For calls without a chat ID, and non-send calls, use a domain-wide cooldown. The domain-wide key is also checked by all callers to prevent stampedes under fallback.
- **Bounded cooldown memory:** maximum 2048 per-process deadline entries (including 3 reserved domain scopes). Expired per-chat entries are pruned at capacity; if full, further waits are recorded under the reserved domain scope rather than silently evicted. The longest outstanding deadline wins.
- **Avoid queued-call stampedes:** check the scope's deadline both before requesting a permit and immediately after obtaining it; a newly discovered wait forces the call to release its permit and retry after the deadline.
- **Other retry behavior:** 5xx retry with exponential backoff happens after slot release. 4xx and unexpected errors still propagate. Public `call_api(func, *args, chat_id=..., **kwargs)` return and argument contract remains unchanged.
- **Metrics:** `flood_metrics()` reports aggregate FloodWait count, current cooldown scope count and overflow count without chat IDs or media names.

## Operational caveats

Telegram's FloodWait may have **account-wide, method-specific or chat-specific** scope. The wrapper cannot infer Telegram's real enforcement scope from the generic FloodWait exception. Per-chat cooldown prevents one chat from holding all permits, but is not a guarantee that other chats are eligible to send. Account-wide waits must be handled conservatively in staging before broad rollout, potentially with a domain-wide policy chosen from evidence. Telegram rate limits are unknown and can change.

This coordination is **per bot process only**, not across replicas. It does not enforce a global MTProto session quota. A running Pyrogram/Wzgram client may also have internal FloodWait retries below its own sleep threshold, which this wrapper cannot release from its semaphore. Tune the client `sleep_threshold` in a separate reviewed change if supported, and verify with real staging API behavior.

References: https://docs.pyrogram.org/start/errors and https://docs.pyrogram.org/faq/how-to-avoid-flood-waits

## Acceptance and rollback

- [x] Full Python regression with MongoDB/dual Redis integration, compile/lint and Docker preflight passed at code SHA `89fadb57` ([CI run 40820968179](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40820968179)). Initial test used fractional FloodWait seconds that Wzgram normalized to zero; fixed to use integer seconds with genuine waiting.
- [ ] Inject long FloodWait from one chat with `telegram_send` limit=1. Another chat succeeds while the first is sleeping and active-slot count remains zero.
- [ ] Concurrent same-chat calls honor shared deadline before re-entering; no retry stampede.
- [ ] Test cancellation during delay, 5xx delay, genuine FloodWait on max retries, dynamic limits, bounded 2048 scopes and unmodified 4xx behavior.
- [ ] Isolated staging measurements with real Telegram: per-chat vs global FloodWait, slow mode, Pyrogram automatic internal retry, queue depth, starvation, tail latency, floods per minute and throughput.
- [ ] Multiple replica and long-retry tests; confirm safe shutdown and no leaked permits or infinite retry loops. Set explicit operational thresholds.
- [ ] Rollback to prior approved image needs no schema/Redis migration, but reinstates semaphore-slot starvation.

PH-024 remains **In review** until CI and live staging results. Nothing was merged or deployed.
