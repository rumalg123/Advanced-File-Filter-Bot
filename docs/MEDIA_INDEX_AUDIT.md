# PH-016: Media index ownership and read-only evidence gate

**Current continuation (2026-10-29):** inventory and EXPLAIN were subsequently collected on all three authorized disposable sources. The manifest now also owns the two default-off search/page indexes. No production DDL or automatic index drops/renames occurred. See [current QA](qa/coverage-expansion/STATUS.md) and [indexed-search rollout](INDEXED_MEDIA_SEARCH.md).

**Status:** code CI passed ([run 40812661483](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40812661483)) / Draft PR #4. Existing MongoDB collections,
documents and indexes were **not queried or modified** during implementation.
The operator-reported ~18 indexes is an approximate snapshot, **not** a
verified list of index definitions or utilization. Real staging/prod plans are
still missing.

## Audit findings

Before PH-016, `MediaRepository.create_indexes` declared 12 media indexes,
and `IndexOptimizer._create_media_indexes` declared 12 with overlapping
names. The bot called **both** during startup on the primary and each
optional secondary database. Combined declarations describe **16 distinct
named indexes**, excluding MongoDB's default `_id_` index. That is **not**
a claim that exactly 17 indexes exist in production. The 18-index screenshot
may represent an extra/differently named index, and must be inventoried.

The same `text_search_idx` was declared in both locations with different
explicit text options. Both paths previously interpreted some exception
messages as successful builds, concealing existing-index option drift. The
database may have a different actual definition from either source.

## Implemented source reconciliation

- `core/database/media_indexes.py`: single named manifest for **all 16**
  historic media index definitions. No new index names, key patterns, unique
  constraints or sparse flags were introduced. It understands how MongoDB
  reports text index keys through `_fts/_ftsx` and `weights`.
- `IndexOptimizer` owns media index creation. The startup code now calls it
  once on the primary and once on each configured secondary. The old
  `MediaRepository.create_indexes` API remains only as a compatibility
  delegator, not an independently maintained index list.
- Existing names are **compared**, not rebuilt. If keys or meaningful options
  differ, log drift and return `False`. Never drop/recreate a conflicting
  index and never report an `IndexOptionsConflict` as successful.
- **For compatibility with fresh installs**, startup still attempts to create
  legacy index names that are *missing*, just as the old startup paths did.
  It does not introduce a new index migration, but this is **not a strictly
  read-only startup** when any historic index is absent. This needs staging
  and operator review before deploying the branch.
- Non-media index initialization remains unchanged. The fact that startup
  previously created some redundant indexes does not authorize removing
  them. If a more restrictive no-DDL mode is required, implement and test
  it separately before deployment.

## Safe read-only inventory

The new `scripts/audit_media_indexes.py` is **always read-only**.
It enumerates index names, key patterns, material options, statuses
(`matching`, `missing`, `definition_drift`), unmanaged indexes and
potential key-prefix overlaps. Prefix overlaps are **candidates for review**,
not proven redundant indexes. It cannot change MongoDB indexes or documents.

Credentials are taken only from securely injected `DATABASE_URI` and
`DATABASE_NAME`, never a CLI argument or `.env`. The script does not
return connection URLs, hostnames, raw data or partial index filter values.
Localhost is the default target. Remote Atlas/staging requires an **explicit
`--allow-remote` acknowledgement**, a verified URI/DB name and suitable
read-only permissions.

```bash
python scripts/audit_media_indexes.py --max-time-ms 3000
```

For an approved **remote staging** clone with appropriate credentials:

```bash
python scripts/audit_media_indexes.py --allow-remote --max-time-ms 3000
```

With a `clusterMonitor` role or equivalent necessary privilege, optional
usage statistics can be included. This may not work with a simple
database-level read-only account; never elevate production privileges solely
for this audit without operator approval.

```bash
python scripts/audit_media_indexes.py \
  --allow-remote --include-index-stats --max-time-ms 3000
```

MongoDB's `$indexStats` values are **per node** and reset on restart,
drop/rebuild or certain index modifications. `access_ops=0` is *not* proof
of non-use, and statistics exclude some internal activity. The report omits
host identities; interpret the `sampled_nodes` counts and `since` windows.
`listIndexes` includes ordinary indexes but not Atlas Search indexes.

## Query-plan and index decision matrix

First run this inventory, then the existing bounded, explain-only PH-006/
PH-014 profiler with actual representative searches **on an isolated
staging clone** (a human may provide query strings; the tool prints digests):

```bash
python scripts/profile_media_search.py \
  --query "doctor x mafia s01e03 540p" \
  --query "s01e03" \
  --offset 0 --offset 100 --offset 1000 \
  --compare-legacy-sort --include-counts \
  --max-time-ms 3000
```

Record MongoDB version/tier, index specs and sizes, p50/p95/p99 application
latencies, actual counts, `nReturned`, `totalDocsExamined`,
`totalKeysExamined`, `executionTimeMillis`, sort/collection scan stages,
plan indexes, cache hit share, and whether a unique index is actually
present for `file_unique_id` and `file_ref`. Compare legacy and stable
PH-014 ordering, plus PH-015 quality/legacy resolution predicates.

**Do not infer index redundancy only from matching key prefixes**:
unique/sparse/partial/TTL, collation, reverse scans, sort requirements and
query shape alter equivalence. Case-insensitive filename regex and
lookahead patterns do not automatically benefit from existing text indexes.
Any proposed index create, hide, drop, or option migration needs **separate
approval**, staging benchmark, backup/restore plan, compatibility check and
rollback, under a future change.

Official references:

- [MongoDB getIndexes](https://www.mongodb.com/docs/manual/reference/method/db.collection.getIndexes/)
- [MongoDB $indexStats](https://www.mongodb.com/docs/manual/reference/operator/aggregation/indexStats/)
- [MongoDB EXPLAIN executionStats](https://www.mongodb.com/docs/manual/reference/explain-results/)

## Verification and rollback

- [x] Both code CI jobs passed on SHA `65da6746` (Python compile/lint,
  complete tests, disposable MongoDB/dual Redis and Docker preflight) in
  [GitHub Actions run 40812661483](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40812661483).
  The first run caught an unsupported `maxTimeMS` argument to PyMongo
  `list_indexes()`, fixed before this passing run. `listIndexes` is bounded
  by the CLI client socket timeout rather than that unsupported option.
- [ ] Confirm `listIndexes` report against operator snapshot with exact
  count and options; explicitly account for the default `_id_` and any
  extra unmanaged names without dropping anything.
- [ ] On fresh **disposable** MongoDB, verify the 16 historic index
  declarations are created once; on existing staging indexes, no repeated
  builds; on conflict, the result is `False` with no index replacement.
- [ ] Run actual workload EXPLAIN on isolated staging; evaluate bottlenecks
  before choosing any changes to index keys.
- [ ] Inspect first/last Telegram searches and indexing with existing
  duplicate constraints and PH-015 flag left OFF.
- [ ] Rollback: restore prior reviewed application image; no index is
  deleted/migrated by PH-016. **If a missing historic index was created
  during staging/rollout, it remains**, and reverting the application does
  not remove it; do not automatically drop it.

**Status remains In review until measured staging and operator acceptance.**
