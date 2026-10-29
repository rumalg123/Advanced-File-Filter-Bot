# PH-026: Bounded distributed MongoDB pagination and stable merge

**Status:** Implemented on the existing hardening branch and Draft PR #4; Full CI passed at SHA `6b7e64bf`; isolated staging acceptance pending. Production still uses only one MongoDB database. **This work does not authorize activating additional databases.**

## Prior behavior

`MultiDatabaseManager.search_across_all_databases` previously fetched `skip+limit` records from **each configured DB**, materialized all of them, sorted the combined Python list, then applied global `skip/limit`. At deep page 2,000 on N DBs, this could construct ~2,000×N documents in application memory, plus the database-level work. Equal `indexed_at` timestamps also required a stable tie-breaker.

## New bounded merge

- Maintains the public `search_across_all_databases(collection, query, limit, skip, sort)` signature and existing offset-based Telegram next-button contract. `limit=0` returns no results; negative/float skip or limits are explicitly rejected.
- A stable per-DB sorted cursor is opened for each configured DB. `_id` is appended as a descending secondary key unless the caller already supplied it; if no sort is supplied, `_id` ascending is used. A final **configured database index** breaks rare identical-ID ties, making the merged output deterministic even before PH-028 global ID enforcement.
- Each source cursor is read using **`to_list(length=64)`**, never `length=None` or `skip+limit` per database. A min-heap combines the next item from each DB, handling reverse sort ordering. Work advances until the requested *global* page has been reached. Only a bounded number of documents per DB are buffered in Python.
- Open cursors are closed on success, short final page, query error, cancellation and early return.
- If a configured DB is offline, the method raises instead of producing a knowingly incomplete result. Cursor read exceptions propagate rather than silently returning an incomplete page. **Other multi-DB count/find helper paths still need PH-027**.
- The per-DB data should use homogeneous indexed-at ISO string timestamps for correct MongoDB/Python sort agreement; mixed BSON types and concurrent additions can still cause ordering changes and require staging data audit.

## Complexity and important limitations

Application-side memory for page iteration is roughly **O(number of DBs × 64 + number of returned records)** rather than O(number of DBs × (skip+limit)). The number of records iterated to reach a deep offset is still **O(skip+limit)** across the combined result, so deep offsets remain CPU/network intensive even though the Python memory usage is bounded. MongoDB still performs each sorted collection scan; indexed filters and sort fields should be confirmed with `explain()` in staging.

**This is cursor-based streaming, not a new persistent stateless keyset continuation token.** Changing Telegram callback payloads to a distributed keyset cursor and maintaining snapshot consistency is a separate design change requiring an opt-in rollout and real benchmarks. We have intentionally not changed existing Telegram pagination buttons, search count metadata or Redis cache-key formats. No distributed snapshot-isolation guarantee is claimed, and PH-028 duplicate/global ID strategy remains unresolved.

Unlike native MongoDB sharding with `mongos`, this application is combining independent databases itself. MongoDB's query router illustrates why targeted routing and shard metadata matter: https://www.mongodb.com/docs/manual/core/sharded-cluster-query-router/

## Test and release gates

- [x] Full Python regression, disposable MongoDB/dual Redis, compile/lint and Docker/Compose preflight passed at SHA `6b7e64bf` ([run 40822577874](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40822577874), attempt 2). Docker Hub returned HTTP 500 resolving the existing Python base image on attempt 1; the failed job was retried successfully without changing code or Dockerfile.
- [ ] Two/three isolated MongoDB databases with **3,750 synthetic media documents** and repeated timestamps: verify pages 0, 50, 1050 and 3200 agree with a deterministic reference ordering. Repeat deep pages to rule out unstable ties. Check disjoint adjacent pages.
- [ ] Instrumented cursor: every `to_list` fetch must request at most 64 records; ensure every cursor closes, and one-source errors cause a hard failure rather than incomplete results.
- [ ] Validate malformed limits, unavailable DBs, partially failed cursor reads and exhausted results.
- [ ] Stage benchmarks at offsets 0, 100, 1,000, 10,000+ with production-shaped index/timestamp distributions, many concurrent searches, peak RSS, latency and MongoDB `explain`.
- [ ] Before enabling a second database: design stable keyset continuation if deep offsets fail latency limits; integrate PH-027 partial failure handling and PH-028 global uniqueness/ownership. Decide when to migrate from manual multi-DB aggregation to native sharding.

**Rollback:** revert to the prior approved image if necessary, but **do not enable multi-DB**. No media schema/backfill, index DDL, production data modification, deployment or PR merge.
