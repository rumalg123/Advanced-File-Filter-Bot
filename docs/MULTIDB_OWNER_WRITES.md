# PH-025: Locate exactly one owning MongoDB before an update

**Status:** Code and tests on the existing hardening branch, Draft PR #4. CI passed at SHA `6b7e64bf`; staging pending. **Production still uses one MongoDB database. Do not enable multi-database mode.**

## Root cause

`MultiDatabaseManager.update_one_across_databases` claimed to update the first matching document, but previously dispatched `update_one` or `upsert=True` to **every** active database concurrently. An upsert for a missing ID could insert multiple independent copies. Even without upsert, duplicates across databases could both be modified, destroying any notion of document ownership.

MongoDB uniquely indexes `_id` **inside each collection**, not globally across disconnected deployments; the existing per-database unique indexes do not provide global uniqueness. MongoDB documents explicitly warn that parallel upserts may create duplicate records without an appropriate uniqueness guarantee: https://www.mongodb.com/docs/manual/reference/command/update/.

## New behavior

The existing four-argument method `update_one_across_databases(collection, query, update, upsert=False)` now:

1. Requires **all configured databases** to be active and accessible before performing any write. A missing/failed database prevents an ownership decision, so it raises rather than treating an outage as “not found.”
2. Probes each database **sequentially and read-only** with the original query, projecting `_id`. If exactly one database matches, only that owner is updated.
3. If **two or more databases** match, raises before any write. This identifies duplicate ownership as a safety incident rather than arbitrarily choosing one copy.
4. If **none** match and `upsert=False`, returns `False`, preserving the normal missing-record contract.
5. If **none** match and `upsert=True` with **two or more configured databases**, refuses creation. No automatic fallback to a preferred database until PH-028 provides global identity and ownership.
6. If exactly one database is configured, `upsert=True` retains the existing insert-on-miss behavior. If an owner already exists in a multi-database configuration, an `upsert=True` call updates that owner with MongoDB `upsert=False` to prevent accidentally creating the ID on a different database.
7. Returns successful result for a **matched no-op update**, not just a document whose value changed. Any lookup or write exception propagates rather than silently treating an uncertain outcome as success/failure.

No public repository method signatures, existing media records, collection names, indexes, or single-database production settings changed.

## Remaining risk and non-goals

This fix prevents the existing scatter write, but **owner discovery and the subsequent write are not a transaction** across disconnected databases. If another writer concurrently inserts/moves the same ID after the scan, the code cannot guarantee global uniqueness. PH-028 must establish an authoritative ownership registry or native sharded architecture before activating another DB. A duplicated ID is not automatically deleted, migrated or reconciled.

PH-027 must still handle comprehensive multi-DB read/count failures and caching. Bulk deletes remain separately blocked. Serial owner reads add O(number of databases) latency, and indexes/lookup cardinality must be benchmarked before any multi-DB rollout. An arbitrary filter matching multiple documents in one database still follows MongoDB `updateOne` semantics, not bulk updates.

## Verification checklist

- [x] Full Python regression, disposable MongoDB/dual Redis, compile/lint and Docker/Compose preflight passed at SHA `6b7e64bf` ([run 40822577874](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40822577874), attempt 2). Docker Hub returned HTTP 500 resolving the existing Python base image on attempt 1; the failed job was retried successfully without changing code or Dockerfile.
- [ ] On two isolated databases, match only DB B: only B updated; DB A untouched. A matched no-op still succeeds.
- [ ] Deliberate duplicate owner in A and B raises before *either* update.
- [ ] Multi-DB upsert for unknown ID fails without creating records. Single-DB upsert behaves as before; multi-DB upsert for existing owner updates only that owner.
- [ ] Unavailable DB, circuit breaker and lookup errors fail closed without writes to a partially observed cluster.
- [ ] Load test owner scans and concurrent creation/failover races on an isolated staging clone; define global identity/ownership PH-028 before enabling the second DB.
- [ ] Review any legitimate callers relying on scatter-update behavior before rollout.

**Rollback:** revert approved image without DB migration. This reinstates unsafe scatter updates if multi-DB is enabled, so keep multi-DB disabled. No production deployment, no PR merge, no DB/index changes.
