# Indexed media search (PH-006)

`FEATURE_INDEXED_MEDIA_SEARCH` defaults to `false`. When enabled, an indexed
necessary-word candidate predicate narrows documents before the existing regex
matcher checks every title, metadata and caption constraint. Unsupported words,
missing/invalidated metadata and unknown versions retain the legacy path.
Internal metadata is stripped on reads regardless of the flag. Text edits remove
it atomically, including after the flag is disabled; backfill can refresh it.

## Activation

Use an explicitly selected disposable/staging database first. Set `DATABASE_URI`
and `DATABASE_NAME` privately in the process environment; do not put secrets in
command arguments. Run from the repository root:

```sh
python -m scripts.backfill_search_tokens --allow-remote
python -m scripts.backfill_search_tokens --allow-remote --apply
```

The default scan is capped at 1,000,000 documents, batches at 200. `truncated=true`
means the inventory is incomplete; increase `--limit` (maximum 10,000,000) before
claiming a complete backfill. Optimistic writes skip concurrent text changes;
repeat until `needs_update=0`. No index is dropped or renamed. Enable the flag
and restart to create the optional `media_search_terms_v1` index, then compare:

```sh
python -m scripts.profile_media_search --allow-remote --include-counts
python -m scripts.profile_media_search --allow-remote --include-counts --indexed-tokens
```

Check complete result identity sets, plans and repeated timings on representative
queries. Metadata-only queries have no title candidate and keep the old plan.
Partial backfill remains correct but may reduce the performance benefit.

## Rollback

Disable the flag and restart: this version continues reading tagged documents.
Before deploying an older image that does not strip internal fields, stop writers
and remove the two fields with the same bounded tool:

```sh
python -m scripts.backfill_search_tokens --allow-remote --rollback
python -m scripts.backfill_search_tokens --allow-remote --rollback --apply
```

Repeat the inventory and confirm `needs_update=0` and `truncated=false`. The
optional index can remain; removing it is a separate operator decision.

## QA evidence, 2026-10-29

A disposable 96,913-record fixture (96,908 cloned media projections plus five
array/cross-field/multiline edge records) returned identical complete ID sets
for eight legacy/indexed queries. Spring of Youth: 4.353s → 0.046s; Dae Jo Yeong:
2.841s → 0.017s; no-match: 2.807s → 0.001s; youth spring: 2.752s → 0.021s;
the doctor x: 4.427s → 0.039s. These are individual local full-match timings,
not production p95 or a Telegram latency claim. Real-Mongo regression cases
also cover typo aliases, Unicode case variants, arrays, captions, missing/future
versions, optimistic edit conflicts, bounded backfill and metadata rollback.

## Deep-page sort index

The same optional flag now declares `media_stable_page_v1` on descending
`indexed_at, _id`. For pages whose offset plus limit reaches 1,000, repository
reads explicitly use that index rather than a blocking sort. Both single-source
and distributed readers retain exact offset semantics. Shallow selective title
queries continue using the candidate planner. Missing/conflicting optional
indexes cause a visible backend error; do not enable the flag before successful
startup index checks. The read-only profiler applies the same hint when
`--indexed-tokens` and a deep `--offset` are selected.

A live 36,563-match metadata search exposed a 32 MB sort failure at its last
page even after bounding the per-source top K. On the disposable remote clone,
the added index produced FETCH/IXSCAN/LIMIT/SKIP plans with **no SORT**. Shallow
pages took 59–74ms; offset 1,000 took 73ms; offset 36,550 took 500ms. These are
single-source measured reads, not distributed or Telegram tail-latency claims.
Rollback leaves this additive index in place; neither index is dropped or renamed.

Optimistic backfill compares source values with `$expr/$eq/$literal`, treating
missing/null text consistently. Ordinary MongoDB array equality is insufficient:
an old array can match an element inside a newly nested array. A real-Mongo
concurrent-edit regression reproduced stale tagging and a possible false-negative
candidate; exact snapshot comparison now skips that edit and preserves legacy
result equivalence.
