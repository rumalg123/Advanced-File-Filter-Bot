# PH-027: Fail-visible partial failures in multi-database reads

**Status:** Code and disposable regression tests committed to the existing hardening branch and Draft PR #4. Full CI and isolated staging pending. Production still has exactly **one MongoDB database**.

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

This gives **all-or-error responses**, not a complete distributed snapshot, consistent count/page pair, replica freshness version, or a partial data mode. A document can change between independent database reads. The existing cache cannot prove global cross-database snapshot freshness. An opt-in partial-result UI with completeness/freshness metadata would require a separate public contract and explicit non-cacheable response type; **it is not enabled by this phase**. Multi-DB delete helpers remain separate potentially dangerous operations and should stay disabled in operational workflows pending an ownership strategy.

## Validation

- [ ] Full Python regression and disposable MongoDB/dual Redis and Docker/Compose CI pass at exact code SHA.
- [ ] Local-only two-DB fixture: count=2, find and aggregate complete when both are available; one forced failing pool causes explicit errors for all read helpers rather than partial results.
- [ ] Active and inactive circuits, cursor error, duplicate-owner read, and failing collection discovery never return a valid zero or a partial result.
- [ ] Inject network partition and recovery under staging concurrency. Verify upstream callback retry errors, no Redis search-cache poisoning, stale-results telemetry and cache-generation behavior.
- [ ] Review all multi-DB consumers and their exception handling before enabling a second DB; benchmark all-or-error availability impact.

**Rollback:** previous approved image reintroduces partial failures in optional multi-DB mode. No schema/backfill, index/Redis mutation, deployment or PR merge is part of this change.
