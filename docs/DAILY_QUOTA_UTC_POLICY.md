# PH-021: UTC daily quota and original-day refunds

**Status:** Code CI passed ([run 40817870542](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40817870542)) at SHA `7c5c0ed5`; isolated staging acceptance pending. Existing Draft PR #4; no production deployment or database migration.

## Policy and boundary

The bot now uses **UTC calendar days** for both retrieval and request quotas, not the local timezone of a Docker host or individual user. A quota day begins at **00:00 UTC**. For example, in Sri Lanka (UTC+05:30), that boundary is **05:30 local time**. All replicas therefore agree on the same daily key. No user-specific or business-region timezone is inferred. If a different product policy is desired, it requires a separate explicitly approved decision before rollout.

The stored values `last_retrieval_date` and `last_request_date` remain ISO `YYYY-MM-DD` strings, and `daily_retrieval_count` / `daily_request_count` remain integer fields. The existing document format, unique indexes, Redis keys and Telegram callbacks are unchanged. Python's timezone-aware datetime behavior is documented at https://docs.python.org/3/library/datetime.html.

## Implemented changes

1. `core/utils/quota_calendar.py`: `quota_day_utc()` derives the calendar date from an aware UTC instant and rejects naive timestamps in tests. All repository retrieval, request tracking, stats and free-plan status views use this one policy.
2. `UserRepository.reserve_quota_atomic` keeps its three-value return contract and **one atomic conditional MongoDB update**. Successful reserved amounts are now `QuotaReservation` values, a subclass of `int` carrying the original UTC day. A partial amount calculated as `reserved_count - delivered_count` carries that same day. Existing handlers do not need new persistent IDs, extra return values, or callback changes.
3. `release_quota(user_id, count)` guards the update by **the reserved amount's original day**, not a new date calculated after Telegram finishes. For plain old `int` callers it continues to use the current UTC day. Its existing `count >= refund` guard prevents a negative daily counter. A day-1 refund never reduces a day-2 counter. Cache invalidation now covers both user data and aggregate user stats.
4. Both `increment_retrieval_count` and its batch equivalent use one atomic conditional pipeline that resets the counter only if the document's date is different and otherwise adds to its current value. This removes a previous read-then-overwrite race across midnight. The existing request-tracking and reservation pipeline semantics remain atomic.
5. The old maintenance bulk reset zeroed counters across **all users** whenever it ran, potentially after users already consumed some new-day allowance. `reset_daily_counters` is retained as a compatibility no-op. Daily maintenance records only its existing UTC day marker and never bulk-clears usage. Individual users reset lazily on their next UTC-day action. Maintenance reports `quota_day_recorded`, `counters_reset=False` and `reset_count=0`.
6. The `active_today` aggregate user-stats cache expires no later than the next UTC midnight, preventing a stale previous-day count from surviving its normal cache TTL.

## Concurrency and refund guarantees

- Atomic MongoDB single-document conditional updates prevent simultaneous reservations exceeding the same day's configured limit.
- A refund with a tagged reservation never credits an unrelated later day. When midnight passes and no new quota has yet been reserved, the old-day refund can still decrement the old stored record; the first new-day reservation then resets it as usual.
- The refund is **not idempotent** with the old two-argument API. Retrying the *same* refund twice after intervening reservations can still result in an inappropriate second decrement, and an unknown Telegram send outcome can still cause inconsistent accounting. PH-022 remains responsible for durable per-delivery reservation IDs, double-refund prevention and outcome reconciliation.
- Any plain legacy integer refund is bound to the current UTC day. In normal production paths, successful reservations from this version return tagged integers and arithmetic preserves the original day. Old versions running concurrently would not honor the tag and should not be mixed during rollout.
- This change does not add a MongoDB transaction or backfill old dates. Existing stored ISO dates remain as recorded. When switching from a non-UTC host-local reset policy to UTC, the **first day at cutover may have a shortened or extended practical window** for existing users. Stage and communicate this behavior rather than rewriting old history.

## Tests and acceptance

- [x] Full Python suite with cancellation, quota, disposable MongoDB and dual-Redis integration tests plus Docker/Compose preflight **passed** at code SHA `7c5c0ed5` ([CI run 40817870542](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40817870542)).
- [ ] Timezone offsets: UTC 23:59:59 / 00:00:00, Sri Lanka UTC+05:30 midnight, negative UTC offsets, naive timestamp rejection and legacy string date decoding.
- [ ] Real local-only MongoDB: 25 concurrent first-day reservations, exactly 10 accepted, no over-limit writes, correct reset at midnight and partial refunds. No new indexes or schema fields.
- [ ] Refund after UTC rollover never decrements the new day's counter; double-refund is explicitly deferred to PH-022. Verify single-file, send-all, deep-link and batch paths with real Telegram failure/cancellation injection on an isolated bot.
- [ ] Scheduled maintenance no longer resets quota consumed during the current UTC day. Existing monitoring consumers understand the `quota_day_recorded` flag.
- [ ] Compare daily requests, warnings, retrieval status, premium bypasses, and aggregate stats around UTC rollover; verify user-facing 05:30 Sri Lanka reset policy is acceptable.
- [ ] Review no-migration rollback and restore old approved image only with an acknowledged policy rollback.

**PH-021 stays In review** until CI and staging verification. No production DB writes, index DDL, Redis flush, deployment, new branch or PR merge are part of this change.
