# PH-014: Deterministic offset paging and deep-page profiling

**Status:** implementation and tests committed to the existing hardening branch
and Draft PR #4. Both CI jobs passed on [run 40809408684](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40809408684).
**No production measurements or deployment have occurred.**

## Finding and scope

In single-database media search, every uncached page currently incurs an
exact match count and a sorted `skip(offset)` page query. Sorting solely on
`indexed_at` does not define a total order when two media files have the
same timestamp. MongoDB explicitly warns that `skip` can be expensive at
large offsets and requires a unique sort tie-breaker for consistent ordering.

- [MongoDB skip and range-based pagination](https://www.mongodb.com/docs/manual/reference/method/cursor.skip/)
- [MongoDB sort consistency and index-supported ordering](https://www.mongodb.com/docs/manual/reference/method/cursor.sort/)

## Implemented, with compatibility boundaries

1. The **single-database** search page now sorts by
   `[("indexed_at", -1), ("_id", -1)]`. `_id` already exists and is unique,
   including for documents whose `indexed_at` values match or are absent.
   This makes repeated offset reads deterministic for a **fixed dataset**.
2. The search cache adds a single-DB ordering namespace
   `|sort:indexed-at-id-desc-v1`, so old cached pages do not mix with
   new-order pages during a rolling deployment. Old Redis entries expire
   normally. The PH-011 generation checks and count/page retry contract
   remain intact.
3. `scripts/profile_media_search.py` now supports repeatable `--offset`
   values, optional `--compare-legacy-sort`, and output for each offset,
   without returning filenames, query text, credentials or documents.
   The original PH-006 `page` output is preserved for offset zero.
4. Validation caps offsets at 0..1,000,000, six distinct offsets and at most
   24 page EXPLAIN operations in one run. Each command is bounded by
   `--max-time-ms`, but EXPLAIN executes database reads and can use CPU/IO.
   Remote MongoDB requires explicit `--allow-remote`; use a read-only DB
   user and never run write/integration tests against production.
5. Tests cover legacy `search_files(query, offset, limit)` and
   `(files, next_offset, total)` output, cached pages, tie ordering,
   non-overlap on a fixed fixture, plan summaries, read-only guarantees and
   invalid profiler inputs.

No MongoDB collection, stored media record, field type, index definition,
Redis key migration, bot callback/button encoding, authentication, Compose
network or Telegram handler is changed. The multi-DB merge path remains
intentionally unchanged until PH-025..PH-028.

## Controlled measurement procedure

Provide `DATABASE_URI` and `DATABASE_NAME` in the process environment
via your normal secret injection. Never commit/paste them. Begin on an
isolated staging clone, not against production.

```bash
python scripts/profile_media_search.py \
  --query "doctor x mafia" \
  --query "s01e03" \
  --offset 0 --offset 100 --offset 1000 \
  --limit 10 --max-time-ms 3000
```

To compare the old and new sort plans in staging:

```bash
python scripts/profile_media_search.py \
  --query "doctor x mafia" \
  --offset 0 --offset 100 --offset 1000 \
  --compare-legacy-sort --include-counts \
  --limit 10 --max-time-ms 3000
```

Use `--allow-remote` **only** after explicitly validating the target and
having operator approval. The CLI does not automatically read `.env`.
Start with narrow queries and low offsets. A deliberately broad query
can scan many records even in EXPLAIN; raise offsets only after reviewing
the previous plan. Use real workload samples without saving query strings
to the report.

Record, for each workload (popular, rare, full filename, episode, and no
matches), at least:

| Field | Evidence needed |
|---|---|
| MongoDB tier/version, index inventory | Read-only environment information |
| Match total and 0/100/1000/deeper offset | Exact count if separately enabled |
| Old vs new page | executionTimeMillis, keys/docs examined, nReturned, SORT stage |
| Count vs page costs | Separate count EXPLAIN and page EXPLAIN |
| Bot latency | Uncached p50/p95/p99, cached p50/p95/p99 from PH-006 telemetry |
| Cache behavior | Hit share and generation-change retries |
| Read correctness | Zero duplicates/missing files across pages on unchanged dataset |

The profiler reports per-command `executionTimeMillis`, **not p95**.
Repeated samples and actual application telemetry are necessary before
inferring production tail latency. A `SORT` stage or marked latency
regression after adding the tie-breaker is a rollout blocker until an
index-supported alternative is measured. Do **not** create/drop indexes
automatically. Any prospective compound index belongs to PH-016, with
measured justification and rollback plan.

## Cursor/keyset redesign decision

**Decision: defer switching button semantics pending measurements.**

Range/keyset pagination using a descending pair `(indexed_at, _id)`
could avoid repeated deep `skip` traversal where appropriate. However:

- Existing Telegram pagination callbacks contain numeric **offsets**,
  totals and user/session data. A cursor rollout requires an explicit
  backwards-compatible server-side mapping, expiry, tamper resistance and
  handling of old in-flight callbacks. It must retain current first/next/
  previous page behavior and user ownership checks.
- `indexed_at` is serialized as an ISO string in existing media records;
  legacy documents may have missing or heterogeneous values. A cursor
  comparison must be tested with real types before using a range predicate.
- Non-unique or differently typed sort keys, page boundary mutations and
  out-of-band MongoDB writes can still cause shifting pages. The PH-011
  generation is **not** a snapshot across Telegram button presses.
- Exact total counts still have a cost with a cursor. Avoid promising
  an end-to-end latency win from eliminating skip alone.

Keep numeric offset buttons for now. Revisit a cursor prototype on
**staging only** if representative deep-page p95, total docs examined, or
scan/return ratios breach an operator-approved threshold and the design
can preserve old callback semantics and full result equivalence.

## Verification and rollback gates

- [x] Python compileall, full pytest, real ephemeral MongoDB/Redis CI and
      Docker/Compose preflight passed at PH-014 code SHA `f838be99`
      ([run 40809408684](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40809408684)).
- [ ] Isolated staging bot shows correct first, next, previous, last and
      repeated pages, including equal timestamps, no-results and expired
      callbacks, without leaking data between users.
- [ ] Capture shallow/deep old-vs-new EXPLAIN with the **same predicates**;
      validate no unacceptable new blocking SORT or p95 regression.
- [ ] Confirm old cached entries naturally expire, new pages use the new
      namespace, and cache invalidation works after an indexed file change.
- [ ] Verify existing Telegram buttons/sessions issued before deployment
      remain accepted, noting that newly ordered pages may differ on ties.
- [ ] Rollback by restoring the previous reviewed image. Redis generations
      and old cache data are not deleted; no schema/index rollback exists.

**Until evidence is collected: PH-014 remains In review, not Verified.
No production database has been connected to or benchmarked.**
