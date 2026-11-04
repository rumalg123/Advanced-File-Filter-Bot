# PH-027: Fail-visible partial failures in multi-database reads

**Status:** Complete-or-error regressions and real secondary-partition/recovery checks passed on the three authorized QA sources. Production rollout and multi-replica load acceptance remain open. See the [current QA report](qa/coverage-expansion/STATUS.md).

## Root cause

The optional multi-DB manager previously returned a partial list or incomplete zero count when an independent DB failed or its circuit breaker opened. These values could be cached as legitimate successful search results, causing false negatives and inaccurate search totals. The problem affected `count_across_all_databases`, `find_many_in_all_databases`, `find_file_in_all_databases`, aggregate helpers, and collection discovery. PH-026 already made its direct streaming search fail on unavailable sources, but other helpers remained unsafe.

## Implementation

- Added a typed `MultiDatabaseReadError` with safe operation/database-name context. It does **not** return or log MongoDB URI credentials or raw search query values.
- `_require_all_databases()` confirms every configured DB is present, active, and has a pool. A down or circuit-open source is not interpreted as empty data. A query with no configured sources is an unavailable result, not a successful zero.
- Cross-DB counts, find-many, aggregate and single-file find now fail visibly when any source errors. Count requires a valid nonnegative integer from every configured database; it no longer adds a fake zero for failed sources.
- Single-file lookup searches every configured source, so a duplicate matching media identity across independent DBs is reported as ambiguous rather than picking the first match. This also supports PH-028's identity guard.
- `get_all_databases` and `get_collection_from_all` no longer silently omit inactive/failed sources. Direct streaming search from PH-026 likewise requires all sources and propagates failures.
- The media repository's existing PH-002 search exception handling turns a read failure into an explicit retryable backend error, **without storing a partial successful result or zero-count cache entry**.

The public successful return types remain the same (`int`, list, optional entity/DB index). Failures are now exceptions in optional multi-DB mode rather than seemingly successful partial data. This behavior is intentional and must be reviewed by any caller expecting best-effort partial results.

### Limits

This gives **all-or-error responses**, not a complete distributed snapshot, consistent count/page pair, replica freshness version, or a partial data mode. A document can change between independent database reads. The existing cache cannot prove global cross-database snapshot freshness. An opt-in partial-result UI with completeness/freshness metadata would require a separate public contract and explicit non-cacheable response type; **it is not enabled by this phase**. Activated media deletion routes only to its immutable owner. Multi-source keyword bulk deletion remains unsupported; there is no automatic owner transfer.

## Validation

- [x] Full Python regression, disposable MongoDB/dual Redis and Docker/Compose preflight **passed** on code SHA `01be21f3` ([CI run 40823704857](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40823704857)).
- [x] Local-only two-DB fixture: count=2, find and aggregate complete when both are available; one forced failing pool causes explicit errors for all read helpers rather than partial results.
- [x] Active and inactive circuits, cursor error, duplicate-owner read, and failing collection discovery never return a valid zero or a partial result.
- [x] Real source-3 network partition/recovery with simultaneous liveness/readiness checks: callback retry at 8.047s, no partial page cache, successful same-callback recovery.
- [ ] Representative multi-replica contention, sustained outage/flapping load and telemetry acceptance.
- [ ] Review all multi-DB consumers and their exception handling before enabling a second DB; benchmark all-or-error availability impact.

**Rollback:** previous approved image reintroduces partial failures in optional multi-DB mode. No schema/backfill, index/Redis mutation, deployment or PR merge is part of this change.

## Batch delivery continuation, 2026-10-29

`MediaRepository.find_files_batch` now follows the same complete-or-error rule.
An activated registry resolves each immutable owner; the defensive legacy path
requires every source and rejects duplicate canonical owners. Neither publishes
partial cache entries. A real missing identity remains `None`; backend failure
raises `SearchBackendUnavailableError` so delivery cannot label an outage as a
missing file. Five added contracts and the ownership/search suites pass.

**QA reconciliation (2026-10-29):** the checked contracts above passed the current disposable MongoDB/dual-Redis regression suite. Relevant real-Telegram and remote multi-source results are recorded in the [active QA evidence](qa/coverage-expansion/STATUS.md). Unchecked operational/load/rollout gates remain pending.

Pagination callback reads now have an eight-second deadline. If a backend's
retry policy runs longer, the read is canceled and the existing safe retry alert
is answered before Telegram expires the callback. The current result message
remains available for retry; incomplete data cannot publish a new search session.
This is distinct from ordinary text searches, whose existing driver retries can
take about 49 seconds during a real secondary partition. Slow-read cancellation
and no-cache/session publication are covered by regression tests.

**Activated topology rollback:** the historical pre-registry rollback statements
above do not authorize an older writer against a bound source. Follow the
[PH-028 offline rollback procedure](MULTIDB_GLOBAL_IDENTITY.md) after activation;
keep the full topology and compatible ownership protocol until that migration.
