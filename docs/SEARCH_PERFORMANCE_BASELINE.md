# Search performance baseline and indexed-search decision (PH-006)

**Status:** instrumented on a draft branch; **no production measurements collected**, no new production indexes, migration or search-algorithm replacement.

## Why this comes before redesign

Media search constructs case-insensitive regex predicates and multi-token lookaheads, counts exact matches, then fetches a sorted page. This preserves legacy filename matching, but MongoDB cannot efficiently use case-insensitive indexes for these regex queries. The existing text index behaves differently from the bot's regex contract (stemming, stop words and punctuation).

Do **not** replace the matcher with `$text` or add/drop indexes before measuring query plans and proving result equivalence.

Sources:
- [MongoDB regex index use](https://www.mongodb.com/docs/manual/reference/operator/query/regex/)
- [MongoDB explain executionStats](https://www.mongodb.com/docs/manual/reference/explain-results/)
- [MongoDB text search semantics](https://www.mongodb.com/docs/manual/reference/operator/query/text/)

## Implemented changes

1. Fixed-size, process-local telemetry records cache hit/miss, count/page latency, successful search time, and backend/generation failures. No raw searches, filenames, user IDs, credentials or query fingerprints are stored.
2. Approximate histogram p50/p95/p99 bucket upper bounds, mean and max are exposed in `metrics.media_search` on the **existing** `/metrics` and `/performance` routes. No endpoint hardening/network changes (PH-004 remains deferred).
3. Slow count, page or full-search stages exceeding **1000 ms** are logged with stage name and duration only.
4. Redundant duplicate-token regex lookaheads are removed. Previously a query `doctor doctor x` required only one `doctor` occurrence. That matching behavior is preserved.
5. New **read-only** `scripts/profile_media_search.py` uses the *same* filter compiler to measure executionStats and existing index usage. It never changes MongoDB documents or indexes. The profiler shows query digests, not the query texts.
6. New unit and real-MongoDB CI tests cover histograms, failures, exact filename search, query plans, index statistics and read-only safety.

### What remains unchanged

No MongoDB schema, indexes, records, file IDs, seasons, resolutions or search result format changed. No Redis cache keys, TTLs or search result pagination changes. No unsafe `$text` prefilter that might exclude legacy matches.

## Safe read-only profiler procedure

Provide `DATABASE_URI` and `DATABASE_NAME` via your existing securely-injected environment. **Do not paste credentials into a shell command, repo or ticket.** Localhost is allowed by default, while remote MongoDB requires `--allow-remote`. The profiler bounds each explained query with `--max-time-ms` (100–10000).

On **staging** with a local MongoDB:

```bash
python scripts/profile_media_search.py \
  --query "doctor x mafia" \
  --query "doctor x mafia s01e03 540p" \
  --query "s01e03" \
  --index-stats \
  --max-time-ms 3000
```

For a remote staging server, add `--allow-remote` after checking the database host and permissions. For a production baseline use a **read-only monitoring account**, off peak and only after confirming the source database and tier:

```bash
python scripts/profile_media_search.py \
  --allow-remote --index-stats --include-counts \
  --query "doctor x mafia" \
  --query "Doctor X Mafia in White S01E03 NF x264 540p mkv" \
  --query "s01e03" \
  --max-time-ms 3000
```

`--include-counts` separately explains expensive exact-count aggregation. Begin without it. MongoDB EXPLAIN with executionStats **does execute read queries to collect measurements**, so even read-only probes can consume CPU/IO. The script does not alter records and prints only aggregate numbers.

Reported fields: estimated document count, existing index names, optional `$indexStats` access counters, and `nReturned`, `totalDocsExamined`, `totalKeysExamined`, `executionTimeMillis`, query plan stages and index names per hashed query ID.

## Runtime metrics

`metrics.media_search` includes:
- `cache_hit_ratio` (null before the first search)
- `events.cache_hit` / `events.cache_miss` counts
- `events.count`, `events.page`, `events.search` with bounded histogram times
- `events.backend_error` and `events.generation_error` counts
- `p50_bucket_ms`, `p95_bucket_ms`, `p99_bucket_ms` are **upper bounds**, not exact quantiles
- Scope is **one bot process since start**; counters reset on restart and are not aggregated across replicas

## Verification and decisions

| Observation | Action |
|---|---|
| Cache hit ratio high and uncached p95 acceptable | Keep existing matcher |
| Uncached scans examine most records or latency grows | Benchmark an indexed candidate on staging with legacy-match fallback |
| Exact counts dominate | Explore alternative count/pagination contracts under PH-014 |
| Deep offsets dominate | Measure stable sort/keyset under PH-014 |
| Indexes unused/duplicated | Audit inventory and usage under PH-016, never automatically drop |
| MongoDB tier cannot sustain traffic | Compare Atlas Search/external search only after correctness and migration analysis |

**Acceptance before PH-006 Verified:** representative MongoDB version/tier; 5+ real query plans including full filenames, episodes and metadata-only; p50/p95/p99 and cache hit/miss measured over a meaningful period; scan-to-return ratios; count-vs-page costs; before/after correctness tests; staged decision and rollback. This document and CI establish the measurement tools, **not** a proven production performance improvement.

See also PH-014 (pagination), PH-015 (quality metadata) and PH-016 (index inventory).
