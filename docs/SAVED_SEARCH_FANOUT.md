# PH-017: Complete saved-search subscriber traversal

**Status:** implementation on existing hardening branch / Draft PR #4. No production
database access, deployment or migration. PH-018 remains responsible for
durable notification scheduling/retry and bounded background fan-out.

## Root cause

When `FEATURE_SAVED_SEARCH_ALERTS=true`, `FeatureService.notify_saved_search_matches()`
previously called `get_active_saved_searches(limit=500)` once. Sorted by
`updated_at DESC`, only the newest 500 subscriptions were inspected per file.
Older matching subscribers were silently excluded.

## Implemented contract

1. `FeatureRepository.get_active_saved_search_page(after_id=None, limit=100)`
   reads at most **100** active documents per call, using a projected
   `_id ASC` keyset (`_id > last_seen_id`). The current writer assigns
   fixed-width UUID-hex string IDs. No added MongoDB fields or indexes.
2. Service iterates until the final short/empty page, checking monotonic IDs
   and yielding to the asyncio event loop between full pages. Read failures,
   oversized results and cursor disorder raise visible errors, never a false
   empty result. Per-page memory is bounded, without a global 500 ceiling.
3. The prior case-normalized token matcher, Telegram payload/buttons,
   atomic notification claims, deduplication and send-failure claim-release
   semantics remain unchanged. The old bounded repository API remains for
   compatibility with any external callers.
4. The feature flag remains disabled by default. Existing collections,
   indexes, documents, Redis and callbacks are unchanged.

MongoDB recommends range-based pagination rather than expensive deep
`skip()` and requires a unique sort key for stability:
https://www.mongodb.com/docs/manual/reference/method/cursor.skip/
https://www.mongodb.com/docs/manual/reference/method/cursor.sort/

## Operational limits

- Each query and response is capped at 100 documents. Matching and sending
  across a single file can still take time proportional to the number of
  active subscribers. **PH-017 has not implemented an inverted index or a
  globally bounded per-file scan.** The built-in `_id_` index supports
  keyset traversal, but `active=true` can still filter inactive records.
- Updating a saved search's `updated_at` does not move its ID, so paging
  remains ordered. Creation/deactivation/deletion/reactivation mid-scan
  can change eligibility, because this is not snapshot isolation.
- The historical saved-search writer creates string `_id` values. Legacy
  mixed BSON ID types are not automatically converted or covered.
- Background tasks remain process-local: interruption can lose remaining
  pages, and database failures do not auto-resume. PH-018 must add durable
  work admission, bounded Telegram send fan-out, backpressure,
  checkpoints/retry and monitoring before broad activation.
- Current claim IDs prevent duplicate sends after successful claims under
  normal operation, but do not provide exactly-once delivery across
  external Telegram API uncertainty.

## Tests and release gates

- [ ] CI: full Python, real disposable MongoDB/Redis, container preflight
      pass at PH-017 code SHA.
- [ ] Fixtures exceeding 1,200 active records verify early and late
      matching users, no duplicates on repeated scans, bounded pages and
      stable traversal when `updated_at` changes.
- [ ] Test read errors, invalid cursor order, failed Telegram sends and
      release/retry, on an isolated staging bot.
- [ ] Measure matches/file, pages/file, scan latency, index plan,
      active/inactive ratio, notification task depth, Telegram flood waits,
      and oldest undelivered alert before enabling widely.
- [ ] Review legacy `_id` type inventory and deletion/reactivation behavior
      in staging, then confirm rollback is compatible.

No production DDL/data writes, no migrations, no Redis flush, no deploy
and no PR merge. PH-017 remains **In review** until CI and real staging.
