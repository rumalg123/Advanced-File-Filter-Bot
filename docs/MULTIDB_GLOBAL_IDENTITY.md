# PH-028: Global media identity and ownership, pre-enable gate

**Status:** Defensive write-block and read-only collision audit implemented; **global uniqueness is NOT yet implemented**. The phase stays In review until an authoritative ownership protocol and staging failover tests exist. Production uses one MongoDB database. Existing Draft PR #4 and branch remain unchanged.

## Why existing unique indexes are insufficient

Individual independent MongoDB databases enforce their own unique `_id` and `file_unique_id` indexes, but cannot atomically prevent the same identity from being inserted into two different databases. A read-before-insert duplicate check races when two workers select different write pools. PH-025's sequential owner lookup prevents existing scatter writes but is not a globally transactional reservation mechanism.

MongoDB explicitly documents unique index constraints in native sharding, including the shard-key prefix requirement: https://www.mongodb.com/docs/manual/core/sharding-shard-key-indexes/. A manual fan-out of independent database connections does **not** inherit native `mongos` routing, global key ownership or transactions.

## Defense now implemented

1. **Fail-closed media creation:** `MediaRepository.save_media` refuses new insertions if the manager reports two or more configured DBs. This is a temporary safety interlock to ensure adding a second MongoDB cannot silently allow duplicate ingestion. The original one-database path is unchanged, and already-existing updates use PH-025's unique-owner update.
2. **Read-only, bounded collision audit:** `MultiDatabaseManager.audit_media_identity_uniqueness(collection, max_docs_per_db=50000)` scans projected `_id`, `file_unique_id`, `file_ref` fields in 200-document chunks and counts cross-database duplicate identities. It never copies full media documents, returns raw identifiers, writes records or creates indexes.
3. **Bounded evidence:** A configured source failure or more documents than the explicit per-DB scan cap produces a hard error, never a misleading “0 duplicates”. Caps may be explicitly raised up to 100,000 per database; large production-scale audits may require a different offline streamed merge/partitioned inspection design.
4. **Honest result:** Even when audit output shows zero duplicates, `global_uniqueness_proven=False`. The scan is not transactional with concurrent writers. There is no claim that duplicate-free history guarantees future uniqueness. The duplicate lookup path from PH-027 also fails when multiple owners already exist.

**Note:** audit uses hashed in-memory keys but stores them only inside the Python process for the duration of a capped read. Its report contains aggregate counts, not original media IDs. It should not be used on a live production cluster without explicit operator approval. No migration, new collection or index DDL has been run.

## Authoritative design required before enabling second DB

The following options remain subject to a separate approved architecture design, schema migration/rollback and concurrency tests:

- **Prefer native MongoDB sharding via `mongos`:** choose a shard key and validate global uniqueness/unique-index constraints and existing media identity indexes before migrating. A single database/cluster model has a coordinated router and defined consistency behavior.
- **If independent deployments must remain:** create an authoritative **global identity and owner registry** on an always-available consistent store, with a unique key for `file_unique_id` and every other promised globally unique identifier. Every writer must atomically claim the identity **before** a media insertion, then commit its stable owner. Stale pending claims, crashes between registry claim and media write, conflict repair, fencing/lease expiry, and removal/transfer must have explicit recovery rules. Do not infer ownership from a best-effort cached lookup.
- During a registry outage the **new write must fail closed**; no fallback insertion to whichever database is reachable. For existing IDs, routing and failed owner reads must be authoritative, not first-match.
- Migration needs read-only inventory of all configured sources, duplicate resolution approval, an offline cutover or dual-write-free rollback, monitoring and fault injection of concurrent creators, mid-flight crashes and inter-DB network partitions.

## Verification gates

- [x] Full Python regression, disposable MongoDB/dual Redis and Docker/Compose preflight **passed** on code SHA `01be21f3` ([CI run 40823704857](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40823704857)). Global ownership design remains incomplete despite passing tests.
- [ ] Two local-only MongoDB databases with identical `_id`, `file_unique_id` and `file_ref` values produce collision counts, with no index/document changes; no raw identifiers appear in report.
- [ ] Cap exceeded, unavailable DB, and duplicate owner always fail visibly. No misleading clean scan or default-off production changes.
- [ ] Two-DB `save_media` path refuses creation **before selecting a write pool or inserting**; one-DB path continues to create media normally.
- [ ] Define and implement a **real** atomic ownership reservation protocol or native sharding migration, including claims/commit/reconcile/fencing, and test at least 100 simultaneous same-ID writers.
- [ ] Pass staging restart and failover tests, index/identity audit, owner recovery, duplicate reconciliation, and operator rollback approval.
- [ ] Integrate PH-027 read-failure handling, PH-025 owner updates and PH-026 pagination performance before enabling more than one DB.

**Release decision:** PH-028's defense-in-depth components can be code-reviewed, but **the phase cannot be considered Verified or permission to enable a second database**. The missing global-ownership mechanism is a known explicit blocker, not silently marked solved.
