# Production Hardening Tracker

> **ACTIVE SOURCE OF TRUTH** for production reliability, correctness, security, and scaling work on Advanced-File-Filter-Bot.
>
> Established: **2026-10-28**. Baseline source commit: [`16c4bc16`](https://github.com/rumalg123/Advanced-File-Filter-Bot/commit/16c4bc16ea1ba81c9f554daeee6ecc917dadd5de).
> The production topology and document counts below were supplied by the operator. Source-code observations were reviewed against that commit. They are **not** proof of live incidents.
>
> **Important:** Do not merge fixes directly into `main`, run destructive database commands, alter indexes, or migrate records merely because they appear in this tracker.

## 1. Purpose and maintenance rules

This file owns the **current production hardening backlog and decisions**. Two existing registers remain historical evidence for their original scope:

- [`BUG_AUDIT.md`](BUG_AUDIT.md), previous Pyrogram/Wzgram bug remediation.
- [`CACHE_AUDIT.md`](CACHE_AUDIT.md), previous Redis cache correctness remediation.
- [`POTENTIAL_ISSUES.md`](POTENTIAL_ISSUES.md), older candidate issues, not automatically validated.

When work overlaps an earlier item, **link its old ID rather than silently reopening it**. An older entry marked "Fixed" means that earlier acceptance criteria were addressed; new risks may still exist in the same module.

**Statuses:** `Open` (not started), `Investigating` (gathering evidence), `In progress` (implementation branch), `In review` (PR, tests pending), `Verified` (merged and tested against acceptance criteria), `Deferred` (out of current topology/scope), `Not applicable` (dismissed with evidence).

**Evidence tags:**
- **Code-confirmed:** a specific behavior is directly observable from current source; this does not necessarily mean an incident occurred.
- **Conditional:** exploitable or impactful only if a stated configuration, load, or failure condition holds.
- **Needs measurement:** plausible bottleneck, not yet demonstrated by production metrics.
- **Future-only:** not on the production execution path while single-database mode remains enabled.

**Priority:** `P0` urgent correctness/security exposure; `P1` address before further scaling; `P2` planned maintainability/performance work; `P3` optional improvement. Priority may change after measurement. **Do not mark an item Verified solely because a PR was merged.**

Every change PR should reference one or more IDs, describe rollback, document compatibility, add regression tests, and record measurement or verification evidence. Update the table after the PR is merged **and** independently verified.

## 2. Production snapshot

**Observed 2026-10-28**, based on an operator-provided MongoDB UI screenshot and the operator's explicit confirmation that only **one MongoDB database** is currently connected.

| Metric | Observed value | Notes |
|---|---:|---|
| Database | `KDramaWorld` | Screenshot label; no connection details stored here |
| Active connected MongoDB databases | **1** | Multi-database routing is **not** presently active |
| `media_files` documents | **~97,000** | UI rounds to 97K |
| `media_files` logical data size | **80.11 MB** | Not physical storage consumption |
| `media_files` storage size | **19.28 MB** | May reflect compressed collection data |
| `media_files` average document size | **~826 B** | UI estimate |
| `media_files` indexes | **18** | Index *count*, not index size |
| `recent_files` documents | **~13,000** | Feature activity |
| `search_analytics` documents | **~2,700** | Feature activity |
| `indexed_channels` documents | **3** | Not necessarily all active |
| `bot_settings` documents | **67** | Per screenshot |
| `file_reports` documents | **7** | Per screenshot |

The screenshot does **not** establish current throughput, latency, CPU, RAM, indexes' disk usage, collection growth rate, MongoDB edition/tier, Redis utilization, real backup status, or which optional feature flags are enabled. Those are **unknown** until measured.

### What is in scope now

Single MongoDB database, current Telegram bot deployment, current Redis configuration, channel indexing, user access, file delivery, search, monitoring, security, and existing feature flags. At ~97K media records, do **not** add distributed systems or a new search service without benchmarks.

### What is deferred

Multi-database global uniqueness, routing, partial search, and merge-sort problems matter if a second database is enabled. Track them, test them, but do not disrupt single-database production to preemptively implement distributed sharding.

## 3. Work register

All items are initially **Open** unless marked Deferred. "Evidence" is a source location, not a failing integration test.

| ID | Priority | Status | Evidence | Finding and impact | Definition of done |
|---|---|---|---|---|---|
| PH-001 | **P0** | In review | Code-confirmed, conditional: [`repositories/user.py`](repositories/user.py) `can_retrieve_file`, [`handlers/callbacks_handlers/file.py`](handlers/callbacks_handlers/file.py) `handle_sendall_callback` | With `DISABLE_PREMIUM` enabled, the authorization helper returns before the banned-user check; the lower-level helper can permit banned users if their handler is not consistently protected. Note: `handle_sendall_callback` **does** already have a `@check_ban()` decorator; the prior missing-decorator allegation was incorrect. | Ban check precedes every premium/admin/quota bypass; direct link, single file, send-all and batch paths have negative tests. |
| PH-002 | **P1** | In review | Code-confirmed: [`core/database/base.py`](core/database/base.py) `find_many`/`count`; [`repositories/media.py`](repositories/media.py) `search_files` | When MongoDB fails, legacy repository methods can return empty lists/zero counts that search previously cached as valid. Strict single-DB media search now distinguishes failures; multi-DB failure handling remains PH-027. | DB timeout/error is distinguishable from zero matches, not cached, and user sees a retryable error; verify with forced failures. |
| PH-003 | **P1** | In review | Conditional: [`redis.conf`](redis.conf), [`core/cache/invalidation.py`](core/cache/invalidation.py) | Current single-Redis `allkeys-lru` can evict operational state. An opt-in dedicated `noeviction` Redis and explicit migration/rollback tooling are committed but **not activated**. | Inventory keys by durability; separate disposable vs operational state or implement equivalent protection; test memory-pressure behavior and failure handling. |
| PH-004 | **P1 if network exposure changes** | Deferred | Operator decision (2026-10-28): bot runs in a secure, network-restricted environment; application-level health/metrics endpoint hardening is not required for the current deployment. External reachability not independently verified. Source: [`bot.py`](bot.py) `_start_web_server`, [`docker-compose.yml`](docker-compose.yml) | Accept existing unauthenticated `/health`, `/metrics` and `/performance` endpoints under the stated network-isolation assumption. No HTTP endpoint code changes requested. | Reopen only if exposure, hosting, trust boundaries or monitoring requirements change; PH-013 remains separate for health-check performance. |
| PH-005 | **P1** | In review | Code-confirmed: [`handlers/channel.py`](handlers/channel.py) `handle_channel_media` | Queue overflow now applies backpressure and small queues can drain. An opt-in `channel_index_jobs` MongoDB queue adds crash recovery, retries and dead letters without changing existing collections; default remains disabled. | Durable recovery/checkpoints, idempotent replay, alerts on loss, and test for overload/restart recovery; no silent loss. |
| PH-006 | **P1** | In review | Needs measurement: [`core/utils/search_matcher.py`](core/utils/search_matcher.py), [`repositories/media.py`](repositories/media.py) | Case-insensitive regex/lookahead and exact counts can scan many media records. Added bounded process-local search telemetry, EXPLAIN profiler and CI plan tests. Production query plans/latencies remain unmeasured; matching behavior unchanged. | Capture representative `explain("executionStats")`, docs examined, p50/p95/p99, cache hit ratio, and compare an indexed candidate strategy before implementing new fields. |
| PH-007 | **P1** | In review | Code-confirmed: [`repositories/media.py`](repositories/media.py) `delete_files_by_keyword`, [`core/database/base.py`](core/database/base.py) `find_many` | Confirmed read-only preview, single-use admin token and 1000-file cap; bounded 100-ID delete batches now replace unbounded operations. Partial failure is reported; existing MongoDB structures are unchanged. | Add bounded, resumable, preview/confirm delete workflow with permission checks, audit trail, and dry-run; test on a large fixture. |
| PH-008 | **P1** | In review | Repo observation: no `.github/workflows` in baseline tree; `main` not protected at observation | Workflow now includes SHA-pinned GitHub Actions, real local MongoDB + two isolated Redis instances, coverage, high-signal Ruff, Docker Compose validation and image build checks. Both required-check candidate jobs passed CI run 40721208499; 41% measured coverage. GitHub rulesets list is empty; classic main protection cannot be read with this integration (403); branch-enforced required checks and staging gate are not yet verified. | Add automated lint, tests, MongoDB/Redis integration tests, PR branch protection where permitted, and smoke test before deploy. |
| PH-009 | **P1** | In review | Conditional: [`core/cache/serialization.py`](core/cache/serialization.py) `_deserialize_pickle`, `_deserialize_legacy_data` | PH-009 implementation removed all executable pickle codecs; legacy p/cp and complete ASCII pickle are rejected, safe JSON/MessagePack preserved, decompression bounded. Live legacy-format inventory and staging verification pending. | Inventory real legacy keys, design safe compatibility transition, remove unsafe unpickling, and regression-test malformed values. |
| PH-010 | **P1** | In review | Conditional: [`redis.conf`](redis.conf), [`docker-compose.yml`](docker-compose.yml) | Main Redis remains unauthenticated by default but unexposed on host. Added *opt-in* ACL auth with file-mounted independent cache/state secrets, no new published Redis port, staging runbook and real ACL CI smoke. Operator must verify network and cutover. | Confirm actual network reachability/credentials, restrict clients, provide authentication and rotation plan, and avoid embedding secrets in repo. |
| PH-011 | **P1** | In review | Conditional: [`core/cache/invalidation.py`](core/cache/invalidation.py), [`core/cache/config.py`](core/cache/config.py) | Atomic never-default-v1 generation for single and split Redis; no counter TTL; malformed counter fails closed. Bounded retries on in-flight cache hits/Mongo reads/cache writes with unit and real-Redis tests; staging still pending. | Make generation identity robust to eviction/restarts; test missing-counter and concurrent-write scenarios without global Redis flush. |
| PH-012 | **P1** | In review | Operational evidence missing | Added separate profile-gated Compose staging stack, secret-excluding Docker build context, offline environment isolation gate, disposable MongoDB/Redis recovery tests and detailed recovery runbooks. Automated CI checks passed; actual Atlas/Redis backup restoration, RPO/RTO and Telegram staging have not been measured. | Record backup retention, encrypted access, restoration rehearsal, recovery goals, and roll-forward/rollback procedure. |
| PH-013 | **P2** | In review | Code-confirmed: [`core/services/maintenance.py`](core/services/maintenance.py) `get_system_health_data`, [`bot.py`](bot.py) health endpoint | PH-013 code now makes / and /health cheap liveness checks and provides bounded cached /ready pings; legacy heavy stats move to explicit /health/details or ?details=1. Existing metrics remain untouched. CI and staging acceptance pending. | Separate cheap liveness, bounded coalesced readiness and opt-in legacy diagnostics; preserve PH-004 operator-deferred endpoint authentication, then verify monitoring compatibility and staging failures. |
| PH-014 | **P2** | In review | Code-confirmed: [`repositories/media.py`](repositories/media.py) `search_files`; [`core/database/base.py`](core/database/base.py) `find_many` | Every uncached search still performs exact count + offset page read. Single-DB results now use deterministic `indexed_at`/`_id` ordering and a new cache namespace, with bounded read-only deep-offset plan profiling. **Actual latency/index regressions unmeasured.** | Benchmark shallow/deep pages with legacy-vs-stable EXPLAIN; verify Telegram buttons, cache and duplicates; decide cursor only with evidence, no automatic index changes. |
| PH-015 | **P2** | In review | Code-confirmed: [`core/utils/media_factory.py`](core/utils/media_factory.py), [`core/utils/search_matcher.py`](core/utils/search_matcher.py) | Legacy `resolution` still mixes dimensions and release labels. PH-015 adds separate optional `width`, `height`, `quality` to in-memory models with read-only legacy adapter; **persisting new fields is disabled by default**, so old images remain rollback-safe. Search handles new quality and existing resolution/filename/caption, cache revision advanced. | Green CI, staging legacy/new search and delivery, demonstrate default-off rollback; any future optional backfill must be dry-run, bounded and recoverable. Explicitly gate write enablement because old dataclass readers reject new fields. |
| PH-016 | **P2** | In review | Code-confirmed: [`repositories/media.py`](repositories/media.py), [`core/database/indexes.py`](core/database/indexes.py), [audit runbook](docs/MEDIA_INDEX_AUDIT.md) | Two startup paths previously declared overlapping media indexes and hid some conflicts as successes. Consolidated 16 historic index names into one manifest, one startup owner, and a read-only drift/usage/prefix audit. No index DDL executed by this work; missing historic indexes may still be created by startup, as before. | Pass CI, inventory actual production/staging index definitions, verify uniqueness and query plans, prove no regressions, obtain explicit deployment approval. **Never automatically drop or rename indexes**. |
| PH-017 | **P2** | In review | [`repositories/features.py`](repositories/features.py) bounded keyset pages; [`core/services/features.py`](core/services/features.py) notification loop | Fixed the hard newest-500 subscriber omission: scan all active saved searches using projected 100-document `_id` keyset pages and cooperative yields. No stored-field/index changes. Total work per file still grows with active subscriptions, and durable continuation is not yet implemented. | Verify >1,200 fixture and staging delivery, inspect read plans/task backlog; PH-018 to bound/durably resume end-to-end fan-out before broad activation. |
| PH-018 | **P2** | Open | Conditional: [`core/services/features.py`](core/services/features.py) `schedule_new_media`, [`handlers/manager.py`](handlers/manager.py) | Notification tasks are created in-process; bursts may accumulate tasks and restarts can interrupt work. | Bounded background concurrency, retry and deduplication, reliable restart strategy; measure queue depth and oldest task age. |
| PH-019 | **P2** | Open | Code-confirmed: [`core/concurrency/semaphore_manager.py`](core/concurrency/semaphore_manager.py) `acquire` | `current_active` is decremented even if a coroutine is cancelled before acquisition, causing incorrect metrics. | Track acquisition state and only decrement after successful acquire; test cancellation before/during/after lock wait. |
| PH-020 | **P2** | Open | Code-confirmed: [`core/concurrency/semaphore_manager.py`](core/concurrency/semaphore_manager.py) `update_limit` | Replacing a live semaphore while old tasks still hold its predecessor can temporarily exceed intended process concurrency. | Update limits without violating global in-flight budget; test reconfiguration under active requests. |
| PH-021 | **P2** | Open | Code-confirmed, policy-dependent: [`repositories/user.py`](repositories/user.py) `reserve_quota_atomic` and `release_quota` | Daily quota uses server-local `date.today()`; reset boundaries may not match the intended user timezone. | Document explicit UTC or business-timezone policy; test midnight, UTC offset, concurrent requests and refunds. |
| PH-022 | **P2** | Investigating | Needs failure injection: [`handlers/callbacks_handlers/file.py`](handlers/callbacks_handlers/file.py), [`handlers/deeplink.py`](handlers/deeplink.py) | Delivery can succeed just before cancellation or process termination, leaving uncertain quota accounting; error paths differ among single/bulk/deep-link sends. | Introduce delivery state/idempotency tests across all entry points; verify quota refunds do not double-credit or consume undelivered files. |
| PH-023 | **P2** | Investigating | Conditional: [`core/utils/rate_limiter.py`](core/utils/rate_limiter.py) | Application rate limiter fails open when Redis is unavailable; availability-friendly, but permits unlimited requests during an outage. | Choose documented fallback with bounded local protection or safe degraded mode; outage tests cover abuse and legitimate access. |
| PH-024 | **P2** | Open | Code-confirmed: [`core/utils/telegram_api.py`](core/utils/telegram_api.py) | FloodWait retries sleep while holding a global Telegram semaphore slot; long waits can block unrelated sends. | Measure waiting tasks and adjust design to release/reacquire slots safely, without creating a retry stampede or violating Telegram limits. |
| PH-025 | **P1 on enablement** | Deferred | Future-only: [`core/database/multi_pool.py`](core/database/multi_pool.py) `update_one_across_databases` | Misleading "first matching" contract submits updates/upserts concurrently to every active database. | Before second DB: locate owning DB and do exactly one logical write; verify duplicate prevention. |
| PH-026 | **P1 on enablement** | Deferred | Future-only: [`core/database/multi_pool.py`](core/database/multi_pool.py) `search_across_all_databases` | Multi-DB pagination fetches `skip+limit` from each database then globally merges/sorts, growing work with offset and DB count. | Before second DB: bounded distributed cursor/merge plan and stable tie-breaker; load-test deep pages. |
| PH-027 | **P1 on enablement** | Deferred | Future-only: [`core/database/multi_pool.py`](core/database/multi_pool.py) `count_across_all_databases` and search helpers | Partial DB failures can produce incomplete counts/results silently. | Before second DB: explicit partial-failure responses, freshness metadata and no partial-result cache poisoning. |
| PH-028 | **P1 on enablement** | Deferred | Future-only: [`core/database/indexes.py`](core/database/indexes.py), [`core/database/multi_pool.py`](core/database/multi_pool.py) | Per-database unique indexes do not enforce global uniqueness across databases. | Before second DB: global identity/ownership strategy with duplicate and failover tests. |

### PH-001 implementation record (2026-10-28)

**Branch:** `docs/production-hardening-source-of-truth-20261028`; **PR:** [#4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4).

- Moved the ban decision and user-existence check to the start of `UserRepository.can_retrieve_file()` before premium-disabled, administrator/owner or premium/quota shortcuts.
- The access policy now **fails closed when no user record is available**, including when premium is disabled. This intentionally changes prior permissive behavior: users must run `/start` and have a readable user record before retrieving media.
- Removed the `@check_ban()` administrator bypass for commands/callbacks. Note that the send-all callback already used this decorator before this work.
- Premium batch links retain separate premium eligibility rules, but now deny banned users **before** checking batch eligibility.
- Added `tests/test_production_authorization.py` covering denial/allowed behavior, callback and service entry points, absent users and premium batches.
- Added a basic compile/pytest GitHub Actions workflow as initial work towards PH-008. Branch protection, MongoDB/Redis integration tests, and staging rollout are not complete.
- **Compatibility:** no MongoDB fields, indexes, document values, Redis keys, cache TTLs or collection names changed.
- **Verification:** full project pytest and Python compilation passed on [GitHub Actions run 40704480842](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40704480842). Production/staging Telegram integration smoke tests and required-check branch protection are still pending. The CI workflow was subsequently upgraded to current Node24-compatible GitHub Actions and retriggered. Keep PH-001 In review and PH-008 In progress until acceptance criteria are verified. No production deployment occurred.

### PH-002 implementation record (2026-10-28)

**Branch:** `docs/production-hardening-source-of-truth-20261028`; **PR:** [#4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4).

- Added an opt-in `raise_on_error` argument to `BaseRepository.count()` and `BaseRepository.find_many()`. **All other callers retain previous default behavior**; only single-database media search uses strict reads.
- `MediaRepository.search_files()` now converts failed MongoDB count/page retrieval to `SearchBackendUnavailableError` **before caching**, so Redis will not store a false zero-result or partial page after a single-DB query fails.
- `FileAccessService.search_files_with_access_check()` handles the typed exception and returns its existing five-element result structure with `has_access=False` and a generic retry message, without exposing MongoDB connection information. A **genuine** zero-result query remains `has_access=True, total=0` and retains its 45-second negative-cache behavior.
- Group search, inline search and pagination now show a retryable temporary-outage message instead of incorrectly telling the user that files are absent or access is forbidden. Group search exits before filter/zero-result analytics when media search itself failed.
- Added `tests/test_search_backend_failure.py` covering forced count and page-read errors, Redis pollution, unchanged legacy-method defaults, successful empty searches and Telegram error paths.
- **Not changed:** the optional multi-database manager may still suppress per-database failures. This is explicitly deferred under **PH-027**, since production has one connected database. Do not claim multi-DB failure handling is fixed.
- **Compatibility:** no collections, MongoDB documents, indexes, migrations, Redis key schemas, TTLs or Telegram callback formats changed. Only the search failure semantics change.
- **Rollback:** revert code commit(s) and redeploy the previous image; no database rollback is required. Previously cached search entries are not flushed.
- **Verification:** full Python compilation and pytest suite passed on [GitHub Actions run 40705992474](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40705992474), including the new failure-injection tests. Staging MongoDB outage/recovery and real Telegram smoke tests are still required before marking PH-002 Verified. Keep PR #4 in Draft and PH-002 In review.

### PH-003 implementation record (2026-10-28)

**Branch:** `docs/production-hardening-source-of-truth-20261028`; **PR:** [#4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4). **Runbook:** [`docs/REDIS_PROTECTED_STATE.md`](docs/REDIS_PROTECTED_STATE.md).

- Added a **disabled-by-default** `REDIS_STATE_URI` and `RoutedCacheManager`. Without that variable the existing cache and operational Redis keys stay exactly where they are today.
- With separate state Redis explicitly enabled, exact known operational key families (rate limits, cooldowns, sessions, search button references, deep-link/subscription sessions, broadcast state and search-cache generation) route to the protected instance. Disposable search/media/user/recommendation caches stay on the existing `allkeys-lru` instance.
- An optional `redis-state` Docker Compose service (profile `protected-state`) uses its own internal network, own persistent volume, a `noeviction` policy and AOF. Its default 256 MB cap is **not** validated sizing; it must be measured before deployment.
- Added independent Redis monitoring for memory cap, eviction policy and evictions; a protected state outage never silently switches keys back to the evicting cache. In split mode the rate limiter denies requests when its protected backend is unavailable.
- Unified session creation, search button rendering, query references and pagination now check operational state write results rather than reporting success with dead links.
- Addressed the version-reset collision in split mode: initialize the counter with a random positive generation and include a split-state namespace in cached pages. If generation cannot be initialized/read, search fails closed rather than returning potentially stale results.
- Added a **non-destructive dry-run-by-default state migration** script `scripts/migrate_redis_state.py`, requiring `--apply --bot-stopped`. It copies selected Redis keys via raw DUMP/RESTORE, preserves PTTL, and never deletes source keys. Advanced reverse/rollback migration requires explicit `--replace-existing` and all writers stopped.
- Added regression suites `tests/test_protected_redis_state.py` and `tests/test_redis_state_migration.py`. Python compilation and the **full pytest suite passed** in [GitHub Actions run 40709170782](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40709170782). Separate two-Redis integration, staging migration/load/outage and rollback drills remain necessary before considering this feature production-ready.
- **Compatibility:** no MongoDB record, collection, schema, or index change. Default Redis config and existing key locations are **unchanged**. The split-mode cutover requires explicit Redis state migration and a tested rollback.
- **Open work:** PH-011 generation/invalidation races, PH-010 Redis authentication/TLS beyond the isolated Compose network, PH-023 unsplit rate limiting fail-open, and operational state memory sizing. Do **not** mark PH-003 Verified or enable production automatically.

### PH-004 deployment decision (2026-10-28)

- **Decision:** skip application-level hardening of `/health`, `/metrics`, and `/performance` because the operator confirms the bot runs in a secure environment.
- **Scope:** do not modify monitoring routes, bind addresses, authentication, firewall/Compose rules, or scrape behavior under PH-004. This does not claim external reachability was independently verified.
- **Accepted condition:** access to management endpoints must remain limited by the existing infrastructure/network boundary. Guidance permits network restrictions as an alternative to authenticating every probe when appropriately enforced.
- **Reopen trigger:** moving hosting, publishing the service externally, changing ingress/firewalls, introducing untrusted workloads on the same network, or new compliance requirements.
- **Separate issue:** PH-013 concerns the cost of heavy health checks, not network exposure. It stays Open for future performance evidence rather than being modified now.
- **Changes:** tracker only; no application code or infrastructure modification.

### PH-005 implementation record (2026-10-28)

**Branch:** `docs/production-hardening-source-of-truth-20261028`; **PR:** [#4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4). **Runbook:** [`docs/INDEXING_RELIABILITY.md`](docs/INDEXING_RELIABILITY.md).

- Fixed a definite in-memory overflow bug: oldest queued items are no longer intentionally discarded when both buffers are full. The producer now waits for capacity. Repaired fixed watermark calculations that could prevent draining of small queues.
- Added disabled-by-default `PROCESSING_DURABLE_INDEXING` (default false) and a new `ChannelIndexJobRepository` used only by channel auto-indexing. Opt-in creates **a new** `channel_index_jobs` MongoDB collection with deterministic channel-message IDs, pending/processing/done/dead status, leases, retries, manual replay and TTL retention for acknowledged jobs.
- Existing `media_files` documents, indexes, collection names, existing Redis keys and Telegram callback contracts are untouched. No existing database backfill or migration is required.
- Added a single background worker that atomically claims jobs, saves through the existing media repository, acknowledges on success/duplicate, reclaims expired leases, retries bounded failures and retains dead letters for inspection.
- Added `tests/test_durable_channel_indexing.py` covering duplicate enqueue, race-safe claims, stale lease tokens, crash reclamation, dead letters/manual replay, legacy overflow, durable handler snapshots, worker success/errors and queue-outage propagation. Added `tests/test_durable_channel_indexing_mongo.py` for atomic claims/leases/dead letters/indexes against a local-only ephemeral MongoDB service in GitHub Actions, with an explicit remote-host safety guard.
- **Known limitations:** the default in-memory mode remains crash-volatile; the opt-in durable mode uses additive MongoDB storage and indexes. A MongoDB outage during enqueue can still lose the original Telegram update, and successful media writes are not transactional with auxiliary channel counters or saved-search notifications. Longer downtime requires an authorized manual backfill or future checkpoint/reconciliation functionality. These are not misrepresented as fully solved.
- **Validation:** Python compile/pytest previously passed; the GitHub Actions workflow now also provisions a temporary local MongoDB service for integration tests. **CI with ephemeral MongoDB passed** on [run 40711957585](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40711957585), including atomic queue lease/recovery, TTL index and dead-letter scenarios. Separate staging process-kill recovery, actual Telegram burst testing, backlog monitoring and rollback remain mandatory before marking Verified.
- **Safety:** opt-in only; no production deployment and no changes to existing MongoDB data or indexes. Turning the flag off disables the new worker without dropping the queued records. Do not delete the new collection during rollback.

### PH-006 implementation record (2026-10-28)

**Branch:** `docs/production-hardening-source-of-truth-20261028`; **PR:** [#4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4). **Runbook:** [`docs/SEARCH_PERFORMANCE_BASELINE.md`](docs/SEARCH_PERFORMANCE_BASELINE.md).

- Added `core/utils/search_observability.py` with bounded per-process telemetry: cache hits/misses and hit ratio; count/page/search stage timings; failures; p50/p95/p99 bucket upper bounds, averages and maxima. No raw query texts, filenames, chat IDs, secrets or unbounded latency buffers are retained.
- Added `metrics.media_search` to existing `/metrics` and `/performance` responses. No modifications to network security/authentication (PH-004 remains operator-deferred).
- Added privacy-safe slow-query logging for count/page/total search stages at a **1000 ms** default threshold. This is a diagnostic, not a production latency benchmark.
- Added `scripts/profile_media_search.py`: read-only MongoDB `explain("executionStats")` with the existing search filter builder, existing index inventory, optionally `$indexStats` and explained count cost. Limits per-query execution and requires explicit `--allow-remote` for non-local DB targets. No DDL, data writes, new indexes or automatic production run.
- Removed redundant duplicate-token lookaheads in `core/utils/search_matcher.py`; search matches, episode, quality, caption, ordering, caching and all existing MongoDB document structures remain backwards-compatible.
- Added unit tests `tests/test_search_performance_telemetry.py` and local-only ephemeral MongoDB integration `tests/test_search_performance_mongo.py`. They check full-filename episode correctness, execution statistics, index reporting, no writes from profiling, bounded histograms and failure-safe metrics. **Full compileall, pytest and ephemeral MongoDB integration passed** on [GitHub Actions run 40717162699](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40717162699).
- **Scope limit:** Existing regex/metadata query planning is still potentially expensive. Actual production performance has not been measured. Do not claim this completed a search-engine redesign, replaced MongoDB regex with indexed search, or proved acceptable p95 on ~97K production files.
- **Remaining verification:** successful final CI run, representative read-only production/staging profiling with operator consent, cold/warm p50/p95/p99, scan-to-return ratios, cache-hit share, count-vs-page cost and a documented decision on PH-014/PH-016 follow-up.

### PH-007 implementation record (2026-10-28)

**Branch:** `docs/production-hardening-source-of-truth-20261028`; **PR:** [#4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4). **Runbook:** [`docs/SAFE_BULK_DELETION.md`](docs/SAFE_BULK_DELETION.md).

- Replaced unbounded keyword deletion with `MediaBulkDeletion`: MongoDB preview performs a strict exact count and retrieves a maximum of five sample file names. No data is deleted by preview.
- Prevents empty/short requests and refuses more than **1000 matches per confirmation**. Current **single-DB** production only. Multi-DB mass deletion is explicitly blocked until PH-025..PH-028 are solved.
- `/deleteall` is admin-only with a one-time 90-second Redis nonce and count-bound confirmation. Atomic consume protects against repeated/cross-admin callback executions. User filenames are escaped in Telegram previews.
- On confirmation, recount and verify the exact preview count before deleting. Delete only projected file identifiers, with batches of at most **100** and no offset/skip. Check shutdown between batches; report acknowledged partial counts on failure and require new preview to resume.
- Fixed delete-channel queue overflow to wait for capacity instead of dropping pending deletion requests. This remains volatile on crash.\n- Invalidate relevant media keys and search-cache generation **after every committed batch**. Cache-generation failure stops further deletion and is visible rather than silently returning success.
- Audit logger and optional Telegram log channel report admin, hashed keyword, expected and acknowledged counts, completion status. Do not log raw search keywords or database credentials in routine logs.
- Added `tests/test_safe_bulk_deletion.py` and isolated localhost-only `tests/test_safe_bulk_deletion_mongo.py` for preview, limits, stale/replayed callback, partial Mongo failure, interruption, invalidation and 215-file real database deletion. **Python compilation, the full pytest suite and ephemeral local MongoDB integration tests passed** in [GitHub Actions run 40719343995](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40719343995).
- **Safety:** no changes to existing MongoDB documents, index definitions, collection names or Redis search button sessions during deployment. Only transient confirmation records change shape; old pending confirmations expire naturally.
- **Operational limitation:** this is not a distributed transaction and does not guarantee exactly-once acknowledgments on network failure. After interruption, compare remaining MongoDB matches; do not blindly assume reported count covers unknown in-flight deletes. A separate data backup or Telegram reindex is required for restoration. No production deployment or destructive commands executed.
- **Release gate:** full CI, real Telegram preview/callback smoke test, backup/restoration evidence, and forced failure/recovery drill required before marking Verified.

### PH-008 CI and release gate implementation (2026-10-28)

**Branch:** `docs/production-hardening-source-of-truth-20261028`; **PR:** [#4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4). **Runbook:** [`docs/CI_CD_RELEASE_GATES.md`](docs/CI_CD_RELEASE_GATES.md).

- Updated `.github/workflows/python-tests.yml` to use read-only token permissions and **immutable full-SHA pinned** official checkout, Python setup and artifact upload actions. No pull_request_target or automatic publishing/deployment.
- The stable **`pytest`** check now exercises full Python 3.13 regression tests, Python compilation including scripts, a focused Ruff undefined-name gate, `pip check`, and XML coverage reporting for a measured baseline (no ungrounded fail-under threshold).
- The test job provisions **local-only ephemeral MongoDB and two separate Redis instances**. New integration tests in `tests/test_redis_services_integration.py` verify split cache/state routing, TTLs, rate-limit counters, `allkeys-lru` vs `noeviction` and protected search version initialization/reset.
- The separate stable **`container-preflight`** job validates production Compose including the optional Redis profile with **inert test placeholders**, builds the existing production Dockerfile to the ephemeral runner, and inspects nonroot runtime/disabled automatic updater defaults. It does not run the Telegram bot, publish an image, contact production or deploy.
- Added `tests/test_ci_release_contract.py`, a structured `.github/PULL_REQUEST_TEMPLATE.md`, and the release-gate runbook. No database, Redis, Docker host or GitHub repository settings were changed by this task.
- **Branch rules status:** GitHub repository ruleset lookup returned `[]`. The connected GitHub integration returned **403** for the classic `main` branch-protection endpoint, so classic protection is **unknown**, not claimed to be disabled. An administrator must verify and require checks **`pytest`** and **`container-preflight`**, then demonstrate a failing PR is blocked. No repo rules mutated automatically.
- **Verification:** both CI jobs, `pytest` and `container-preflight`, completed **successfully** on [GitHub Actions run 40721208499](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40721208499). Full regression suite includes ephemeral MongoDB and dual Redis; compiled source, Ruff undefined-name lint, `pip check`, Compose validation and Docker image build passed. **Coverage baseline: 41%** (14,022 statements; 8,340 uncovered) across `core`, `handlers` and `repositories`. This is a baseline, not a sufficient quality level or an enforced threshold. Staging Telegram/bot/database/Redis smoke and rollback and GitHub-required status check enforcement still prevent declaring PH-008 fully Verified.
- **Release safety:** no production deployment, no GitHub branch/PR merge, no existing MongoDB fields/index/document changes and no Redis key migrations were performed.

### PH-009 implementation record (2026-10-28)

**Branch:** `docs/production-hardening-source-of-truth-20261028`; **PR:** [#4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4). **Runbook:** [`docs/SAFE_REDIS_SERIALIZATION.md`](docs/SAFE_REDIS_SERIALIZATION.md).

- **Root cause:** although new writes defaulted to JSON/MessagePack, `core/cache/serialization.py` had executable `pickle.loads` calls for tagged `p` / `cp` values and fallback unprefixed legacy data. Python officially documents code execution risks when unpickling untrusted values.
- **Code fix:** removed the runtime `pickle` import and all pickle load/dump execution. Existing safe serialized formats `j`, `m`, `cj`, `cm` and safe unprefixed JSON/MessagePack remain readable with unchanged Redis key names, TTLs and existing wire bytes. Deprecated pickle hints now always select safe MessagePack; even a changed historical `PICKLE_DISABLED` flag cannot permit pickle again.
- **Legacy:** tagged pickle and recognized complete ASCII-protocol pickle are cache misses, not executed or automatically rewritten. Other untagged binary pickle cannot execute and generally becomes a miss. The decoder does not silently purge or flush state. Old pickle-backed user sessions or callbacks may become unavailable; this requires staged inventory and a controlled transition, not unsafe in-process unpickling.
- **Bounds:** encoded payload limit 16 MiB, decoded compressed limit 32 MiB, bounded zlib expansion, rejection of malformed streams, aggregate rejection statistics without user data. The cache memory-size estimator no longer invokes pickle.
- **New read-only tool:** `scripts/audit_redis_serialization.py` uses bounded Redis SCAN, TYPE, GETRANGE for two-byte format tags and PTTL. It outputs approximate aggregate format/TTL counts, no key names or values. Remote instances require explicit `--allow-remote`. No operator-approved production scan has run.
- **Tests:** `tests/test_safe_redis_serialization.py` covers malicious tagged, unprefixed binary and ASCII pickle, safe codec roundtrips, compression bombs, cache manager read semantics, and non-destructive behavior. `tests/test_redis_serialization_audit.py` verifies the audit never accesses full values. Existing ephemeral Redis integration test extended to validate live safe/legacy mixed entries and preserved TTLs. **Both `pytest` and `container-preflight` passed** on [CI run 40723920782](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40723920782), including real Redis+MongoDB integrations, malicious pickle regression tests, focused lint and Docker build. Overall Python coverage: 41% (14,043 statements, 8,319 uncovered).
- **Compatibility:** no MongoDB schema/data/index changes; no production Redis writes, key migration or flush; no Telegram callback contract change and no deployment. PH-003 protected Redis routing remains optional/unchanged.
- **Rollout gate:** full CI, read-only production/staging legacy-format inventory, staging Telegram active session, pagination, subscription, rate-limit and callback checks, and approved handling of any important persistent pickle entries before marking Verified.
- **Security rollback caveat:** rolling code back would reintroduce unsafe pickle, so repairing/recreating affected state is preferable to restoring the vulnerable deserializer.

### PH-010 implementation record (2026-10-29)

**Branch:** `docs/production-hardening-source-of-truth-20261028`; **PR:** [#4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4). **Runbook:** [`docs/REDIS_ACCESS_SECURITY.md`](docs/REDIS_ACCESS_SECURITY.md).

- Audited original `redis.conf`: binds `0.0.0.0` on its container interfaces, `requirepass ""`, and deliberately renames destructive commands. The existing Compose file has no Redis `ports` mapping, so host-level exposure is not implied by that bind alone. Redis is reachable by trusted containers sharing its network; exposure cannot be independently verified without the host's network/firewall data.
- Added optional `REDIS_USERNAME` / `REDIS_PASSWORD_FILE` and `REDIS_STATE_USERNAME` / `REDIS_STATE_PASSWORD_FILE`, all **empty by default**, and `core/cache/auth.py` credential file validation. Legacy URI-only connections remain unchanged; mixed URI-embedded and file credentials are refused rather than silently overridden.
- `CacheManager` and bot initialization pass independent credentials for disposable Redis and optional `REDIS_STATE_URI`. Manual Redis state-copy and serialized-key audit scripts accept the same file-backed credentials, subject to separate ACL grants needed for `DUMP`/`RESTORE`.
- Added [`docker-compose.redis-auth.yml`](docker-compose.redis-auth.yml) with Compose file-backed secrets granted only to the receiving service, ACL-protected Redis startup/healthchecks and **no host Redis ports**. Overlay is not part of the default deployment command.
- Added explicit, non-overwriting, private-directory credential generator [`scripts/generate_redis_acl.py`](scripts/generate_redis_acl.py), plus `.secrets/` gitignore and updated example environment variables. ACL named user `filebot` with `-@dangerous` restriction is defense in depth, **not claimed to be exhaustively least privilege**. TLS remains the operator's responsibility if crossing untrusted networks.
- Added [`tests/test_redis_acl_security.py`](tests/test_redis_acl_security.py) and Compose/real-Redis ACL CI smoke: reject unauthenticated PING, authenticate and GET/SET using a generated secret, validate network/secret overlay config. **Both CI jobs passed** on [run 40800650194](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40800650194), including Docker Compose ACL overlay validation, an authenticated Redis service refusing unauthenticated PING and accepting authenticated PING/GET/SET, complete pytest/MongoDB/dual Redis integration and Docker image build.
- **Compatibility:** no MongoDB documents/indexes/collections, Redis keys/values/TTLs, Telegram callback formats, data migration, Docker production containers or live credentials have been changed. Authentication requires an explicit, coordinated staging cutover/restart; do **not** enable blindly against an existing unauthenticated production server.
- **Release gate:** full CI, actual Docker network/host reachability inspection, non-production ACL cutover and rollback rehearsal, session/rate-limit/cache-version smoke, credential rotation design, TLS decision for remote connections. PH-010 remains In review.

### PH-011 implementation record (2026-10-29)

**Branch:** `docs/production-hardening-source-of-truth-20261028`; **PR:** [#4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4). **Runbook:** [`docs/SEARCH_CACHE_GENERATION.md`](docs/SEARCH_CACHE_GENERATION.md).

- **Root cause:** missing single-Redis generation previously returned `v1`. In split mode a malformed counter could be deleted non-atomically. A cached page or DB search could also return even after a concurrent invalidation advanced its generation.
- Added atomic Redis Lua `ensure_search_generation`/`advance_search_generation` in `CacheManager` and separate-state routing, with random generation when missing, no fallback to 1, malformed-key fail-closed handling, no risky deletion, and atomic removal of legacy one-year TTL via `PERSIST`. Existing key name `cache:search:version` and cache page key formats remain unchanged. Single Redis `allkeys-lru` can still evict the counter, but fresh random generation avoids predictable reuse.
- `MediaRepository.search_files` now checks generation after cached hits, completed DB count/page reads and page cache SET. A changed generation causes a fresh search, with **maximum three attempts** before returning a retryable error, never intentionally presenting known-stale pages.
- New `tests/test_search_cache_generation_races.py` and `tests/test_atomic_search_generation_redis.py` verify mid-request indexing races, cached reads, cache SET races, bounded retries, unavailable generation, raw Redis 100-way concurrent increments, malformed counter refusal, TTL removal and split-instance recovery. Existing fake-cache and PH-003 tests updated for atomic generation semantics.
- **Compatibility:** no MongoDB collection/document/index changes, no Redis FLUSH or key migration, no Telegram callback/pagination wire-format changes, no deployment. Lua requires Redis EVAL/INCR/PERSIST permissions, already available to the default Redis connection; an opt-in Redis ACL deployment must also permit those operations.
- **Limitations:** this detects writes that successfully increment the generation; does not provide multi-database transaction/snapshot isolation, protect against out-of-band MongoDB changes without invalidation, or guarantee freshness for mutations happening after the final read.
- **Verification:** both GitHub Actions CI jobs passed on [run 40803258303](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40803258303), including full pytest, real Redis/MongoDB, concurrent generation/invalidation regression tests, Python compilation, Ruff and Docker/Compose preflight. Staging Telegram search/indexing bursts, Redis loss/restore, cache hit, pagination, session integrity and controlled rollback remain before marking Verified. PH-011 is In review.

### PH-012 implementation record (2026-10-29)

**Branch:** `docs/production-hardening-source-of-truth-20261028`; **PR:** [#4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4). **Runbook:** [`docs/STAGING_AND_RECOVERY.md`](docs/STAGING_AND_RECOVERY.md); **evidence:** [`docs/RECOVERY_EVIDENCE_TEMPLATE.md`](docs/RECOVERY_EVIDENCE_TEMPLATE.md).

- **Confirmed deployment hazard:** production `docker-compose.yml` declares global `container_name` values and publishes port 8000, which would collide with a same-host staging stack; the Dockerfile copied the whole build context without a `.dockerignore`, risking inclusion of local secrets and sessions. These were identified without connecting to live services.
- Added independent [`docker-compose.staging.yml`](docker-compose.staging.yml) with a unique project, no fixed container names, no published ports, distinct named volumes/network, staging Redis persistence, no auto-updates, and a **profile-gated** Telegram bot with an extra container startup guard. The existing production Compose file is unchanged.
- Added `.dockerignore` to exclude `.env*`, `.secrets/`, sessions, Redis dumps, logs, backups, other mutable state from production and staging Docker build context. Real credentials are never committed.
- Added [`scripts/staging_preflight.py`](scripts/staging_preflight.py): **offline** comparison of explicitly supplied production/staging env files, requiring different Telegram bot token, separate MongoDB host/cluster, `staging_` database name, dedicated channels, no extra media DB and no update or external Redis state settings. Host comparison makes no network requests and prints no credentials. The `--runtime` check blocks staging startup without staging-only configuration and explicit operator acknowledgment; it does **not** independently know production secrets.
- Added [`scripts/validate_staging_compose.py`](scripts/validate_staging_compose.py) to check the **resolved** Compose project/service profile, no host ports/fixed names/external networks, isolated volumes, and safe environment values without exposing resolved configs. CI uses synthetic, inert credentials.
- Added [`tests/test_staging_isolation.py`](tests/test_staging_isolation.py) and [`tests/test_disposable_recovery_fixtures.py`](tests/test_disposable_recovery_fixtures.py). The latter uses only ephemeral localhost MongoDB/Redis, two UUID-named databases and UUID-scoped Redis keys, testing logical BSON/index reconstruction and Redis per-key DUMP/RESTORE TTLs. **This is not proof that Atlas snapshots, full mongodump archives or Redis RDB/AOF recovery work.**
- Created [staging/restore runbook](docs/STAGING_AND_RECOVERY.md) and blank [recovery evidence template](docs/RECOVERY_EVIDENCE_TEMPLATE.md): cluster/server separation, backup integrity, real isolated Atlas/mongorestore and Redis restoration rehearsals, Telegram smoke tests, RPO/RTO measurements and code rollback triggers.
- **Not done:** no staging VPS/Telegram bot/cluster was provisioned, no production database or Redis was accessed, no real Atlas/Redis full backup was restored, no recovery duration was measured, and no application was deployed/merged. **Both CI jobs passed** ([run 40805561186](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40805561186)): Python compilation, full pytest/MongoDB/Redis recovery fixture integration, safe offline staging comparison, staging Compose structural checks, Docker build and opt-in Redis ACL test. PH-012 remains In review until actual operator-run backup restorations and staging Telegram tests.

### PH-013 implementation record (2026-10-29)

**Branch:** `docs/production-hardening-source-of-truth-20261028`; **PR:** [#4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4). **Runbook:** [`docs/HEALTH_PROBES.md`](docs/HEALTH_PROBES.md).

- **Root cause:** `bot.py` connected HTTP `/` and `/health` directly to `MaintenanceService.get_system_health_data()`, which collects user/file aggregates, Redis TTLs, `dbStats` and other database storage statistics every 30-second Docker liveness check. A slow DB or cache could make the Docker bot container unhealthy and restart the process during a dependency outage.
- **New liveness:** `/`, `/health` and `/live` return HTTP 200 with `status=alive` and bot identity without Redis/MongoDB/maintenance calls. Dockerfile and both Compose stacks retain `/health`, reducing dependency-induced restart storms. **Contract change:** `/health` no longer includes `stats`/`meta`; legacy clients must request `/health/details` or `/health?details=1`.
- **New readiness:** `/ready` uses one direct primary-MongoDB `ping`, disposable Redis `PING` and optional PH-003 protected state Redis `PING` in parallel. Each is bounded to **0.75 seconds**; ready responses cached 5 seconds, unavailable 2 seconds; concurrent readiness calls coalesce under an async lock. Response only returns generic dependency status, not URI or error text.
- **Heavy diagnostics:** unchanged `MaintenanceService.get_system_health_data()` is invoked only via explicit `/health/details` or `/health?details=1`. Existing `/metrics` and `/performance` collection, endpoint binding, CORS and authentication behavior are **unchanged**. PH-004 security hardening remains operator-deferred; PH-013 does not add credentials or alter network reachability.
- **Tests:** [`tests/test_health_probes.py`](tests/test_health_probes.py) covers cheap liveness, 18 concurrent readiness requests, cached probes, Mongo/Redis outage/timeout, isolated protected Redis failure, legacy detailed stats and safe error responses; static contract checks verify Compose/Docker liveness remains separate. **Both CI jobs passed** on [run 40808093133](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40808093133): full Python tests (including aiohttp concurrency/readiness/outage regression tests), MongoDB/dual Redis integration, Ruff/compile and Docker/Compose/Redis ACL preflight. Real Telegram/Atlas/Redis staging failure drills and monitoring compatibility acceptance remain pending.
- **Limitations:** a healthy HTTP listener does not prove Telegram polling/worker health, readiness is a cached snapshot and checks only the primary MongoDB (future PH-027 multi-DB), and explicit legacy diagnostics can still be expensive. If existing monitoring systems rely on legacy `/health` JSON, migrate them before release.
- **Safety:** no MongoDB schema/index/document or Redis key changes, no cache flush, Telegram callback changes, production Docker restart/deployment or PR merge. PH-013 stays In review until final CI and staging fault drills.

### PH-014 implementation record (2026-10-29)

**Branch:** `docs/production-hardening-source-of-truth-20261028`; **PR:** [#4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4). **Runbook:** [`docs/PAGINATION_PERFORMANCE.md`](docs/PAGINATION_PERFORMANCE.md).

- **Ordering fix:** single-DB `MediaRepository.search_files` now sorts by descending `indexed_at`, then unique descending `_id`; repeatable offset pages on unchanged records cannot arbitrarily shuffle equal timestamps. Multi-DB merge remains deferred. The existing `(files, next_offset, total)` API and numeric Telegram pagination buttons are unchanged.
- **Cache safety:** single-DB search keys include an ordering namespace to avoid mixing old equal-timestamp pages with the new deterministic order during deploy. No Redis flush/migration, no generation reset. Old cached entries expire.
- **Read-only measurements:** extended PH-006 EXPLAIN profiler with repeated `--offset`, optional `--compare-legacy-sort`, at most six offsets and 24 page EXPLAINs, and per-command `maxTimeMS`. Reports only hashed query identifiers, counts, plan stages, indexes and aggregate execution timings; does not store queries/filenames. Remote DB access remains opt-in.
- **Tests:** [`tests/test_pagination_stability.py`](tests/test_pagination_stability.py) covers stable sort passed to the database, cache namespace isolation, unchanged numeric offsets and page totals, parameter bounds, and ephemeral localhost MongoDB equal-timestamp non-overlap/read-only profiler comparisons.
- **Measured facts:** no production query plan, deep-offset p95, new-sort `SORT` cost or compound index suitability is yet established. A unique tie-breaker may alter MongoDB index/sort planning, so any regression must be measured in staging before rollout. No index is automatically added/dropped.
- **Cursor decision:** defer changing Telegram button contracts until a demonstrated deep-offset bottleneck and a reviewed back-compatible cursor/session mapping. Existing `indexed_at` string/legacy shapes and mutation-between-page semantics need explicit handling.
- **Safety:** changes are confined to the existing branch; no deployment, production database queries, index DDL, persisted media schema change, or PR merge. **PH-014 remains In review** despite green [CI run 40809408684](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40809408684) (both pytest and container-preflight); real staging/search and EXPLAIN evidence remain missing.

### PH-015 implementation record (2026-10-29)

**Branch:** `docs/production-hardening-source-of-truth-20261028`; **PR:** [#4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4). **Runbook:** [`docs/MEDIA_METADATA_CONTRACT.md`](docs/MEDIA_METADATA_CONTRACT.md).

- **Code-confirmed drift:** `MediaFileFactory` put native pixel dimensions or a filename quality label into the same legacy `resolution` string. `960x540` and `540p` are not interchangeable.
- **Canonical contract:** `width` and `height` require a valid pair from Telegram-native media attributes; `quality` is an explicit `Np` label from filename (preferred) or caption, not guessed from pixel height. `resolution` and stored season/episode semantics remain unchanged.
- **Backwards-compatible reads:** `MediaFile` accepts missing optional fields; `display_quality` resolves new labels or existing legacy quality/filename tags on demand without modifying MongoDB documents. Search adds the `quality` branch alongside prior `resolution`/filename/caption fallbacks and advances search algorithm cache revision to 3.
- **Critical rollback protection:** the previous image's `MediaFile(**data)` rejects new unknown keys. The central serializer now omits all three additional fields unless `FEATURE_CANONICAL_MEDIA_METADATA=true` is explicitly enabled. The setting is **false by default**. This applies to ordinary and durable indexing snapshots. Enabling writes requires separately validated old-image rollback compatibility or recoverable removal/backups; disabling the feature after writing does not undo documents.
- **Tests:** [`tests/test_media_metadata_contract.py`](tests/test_media_metadata_contract.py) covers parsing, actual dimensions, no inference, default-off writes, opt-in serialization, legacy document reads, and localhost-only ephemeral real MongoDB mixed-schema query equivalence. Existing search predicate field allowlist updated.
- **Safety:** no new indexes, automatic backfill, data edits, Redis flush, Telegram callback changes, production deployment or merge. The legacy `migrate_media_metadata.py` is **not** a PH-015 backfill and must not be run as one. **Both CI jobs passed** on [run 40811505457](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40811505457) at code SHA `40b4a5da`, including full pytest with real ephemeral MongoDB/Redis, compile/lint, Compose and Docker image preflight. Operator staging and enabled-write rollback design remain pending; **PH-015 stays In review, not Verified.**

### PH-016 implementation record (2026-10-29)

**Branch:** `docs/production-hardening-source-of-truth-20261028`; **PR:** [#4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4). **Runbook:** [`docs/MEDIA_INDEX_AUDIT.md`](docs/MEDIA_INDEX_AUDIT.md).

- **Root cause:** `MediaRepository.create_indexes` (12 declarations) and `IndexOptimizer._create_media_indexes` (12 declarations) were both invoked during primary and secondary database startup. Their combined registry had 16 distinct names, excluding MongoDB's builtin `_id_`; operator screenshot showed 18 existing indexes and has not yet been reconciled with an actual `listIndexes` export.
- **Reconciliation:** `core/database/media_indexes.py` contains the single legacy manifest, and `IndexOptimizer` is now the only startup owner. Repository `create_indexes` is retained as a compatibility delegator. No new index names or key patterns, no drop/hide/rename paths. Existing definitions are compared to the manifest rather than recreated. Conflicts are reported **False**, not hidden as successes.
- **Read-only operator audit:** `scripts/audit_media_indexes.py` enumerates bounded `listIndexes` data, material options, missing/definition-drift/unmanaged names, prefix relationships and optional per-node `$indexStats` with sanitization. Localhost-only unless `--allow-remote` is explicitly passed. It never runs index DDL or reads content documents.
- **Operational nuance:** media index startup retains prior behavior of creating **missing historic indexes** for fresh installations; this should not be confused with the read-only audit. Any startup missing-index creation remains a database write, and the true staging/production inventory must be checked before deploying. `$indexStats` zero-use counters are not drop evidence because they reset and are node-local.
- **Tests:** [`tests/test_media_index_audit.py`](tests/test_media_index_audit.py) exercises manifest stability, Mongo text-index representation, conflict detection, read-only safety, and isolated local MongoDB audit; full CI and staging pending.
- **Safety:** no live MongoDB or Redis operations, no production Docker image update, no schema migration, no automatic index drop and no PR merge. **PH-016 In review**, despite both CI jobs passing on [run 40812661483](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40812661483) at SHA `65da6746`. Actual index inventory, query-plan and staging evidence are still required.

### PH-017 implementation record (2026-10-29)

**Branch:** `docs/production-hardening-source-of-truth-20261028`; **PR:** [#4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4). **Runbook:** [`docs/SAVED_SEARCH_FANOUT.md`](docs/SAVED_SEARCH_FANOUT.md).

- **Root cause:** flagged saved-search notification code read only the newest 500 `active` searches and silently excluded older active subscribers. This was a correctness bug under growth.
- **Fix:** `FeatureRepository.get_active_saved_search_page` now reads ≤100 projected records per page with an immutable string `_id` keyset; the service iterates all pages, yields cooperatively and retains the prior token-matching, message format, claim/release and deduplication behavior.
- **Tests:** `tests/test_saved_search_pagination.py` includes 1,253 synthetic subscriptions and 1,205 active records in a local-only disposable MongoDB test, ensuring all expected matching subscribers are seen after the former cutoff, with bounded page sizes, unique ordering and error detection. Prior alert regression mock updated.
- **Boundaries:** total work and Telegram sends per file are not capped. The process-local background task can be interrupted; there is no durable continuation or retry across page errors, and ID-keyset traversal is not an isolation snapshot under concurrent activate/delete/create events. Existing unique hex-string IDs are assumed. End-to-end throttling, durable job checkpoints and queue/backpressure belong to PH-018 and must precede broad opt-in deployment. No index/collection/schema change or live MongoDB/Redis operation.
- **Release gate:** CI, actual staging read plans, Telegram notification/flood-wait behavior and operator-approved performance thresholds are pending. **PH-017 remains In review.**

## 4. Architecture drift register

These are design divergences, **not** independent production incidents. Any remediation should reference its linked PH items.

| Drift ID | Drift | Current decision | Linked work |
|---|---|---|---|
| AD-01 | Search queries use regex/lookaheads while the repository maintains text and metadata indexes | Measure query plans first, then choose normalized/indexed candidate search; no premature new service | PH-006, PH-014, PH-016 |
| AD-02 | Multiple indexing/metadata representations for quality and filenames | Establish a canonical search/metadata contract without breaking legacy records | PH-015 |
| AD-03 | Redis stores disposable cache entries and state that controls correctness | Separate durability classes, document TTL/eviction and failure modes | PH-003, PH-011, PH-023 |
| AD-04 | Background work is coupled to bot-process lifetime | Start with checkpoints and bounded workers; a separate broker only when measured reliability requires it | PH-005, PH-018 |
| AD-05 | Feature paths implement overlapping permission, quota, send and refund logic | Centralize delivery authorization and observable delivery state | PH-001, PH-022 |
| AD-06 | Index creation is owned by both repository and optimizer | One reviewed index manifest and migration/rollback policy | PH-016 |
| AD-07 | The optional multi-DB manager acts as manual sharding, not coordinated storage | Keep OFF; revisit only with proven single-DB capacity problem | PH-025..PH-028 |
| AD-08 | Heavy operational metrics and liveness share one HTTP surface | PH-013 separates cheap liveness, bounded readiness and on-demand legacy diagnostics; PH-004 authentication/networks remain deferred | PH-004, PH-013 |

## 5. Delivery plan and dependencies

### Phase 0: baseline, safety and verification

- [ ] Capture production environment topology **without secrets**: MongoDB version/tier, Redis version, bot replicas, current flags and resources.
- [ ] Collect **read-only** workload evidence: media count, current `getIndexes()`, `$indexStats`, common query `explain("executionStats")`, slow-query samples, app p50/p95/p99, MongoDB CPU/memory, Redis memory and evictions, indexing queue depth/drops.
- [ ] Confirm backup/restore procedures on an **isolated non-production restore**. Do not copy secrets or exposed user data into GitHub.
- [ ] Establish smoke tests covering the exact previously failing Doctor X S01E03 filename, short title, season/episode, resolution, pagination and button delivery.
- [x] PH-008 workflow/code committed: Python compile, tests, coverage, Ruff undefined-name gate, ephemeral MongoDB and two Redis integration services, Compose validation, non-root Docker image build, SHA-pinned Actions and PR template. **Both CI jobs passed** ([run 40721208499](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40721208499)), Python coverage baseline 41%; **required branch protection and actual staging not verified.**
- [x] PH-012 staging/recovery **code** committed: separate Compose project without published ports or fixed names, unique staging volumes, Docker secret exclusion, offline prod-vs-stage token/cluster/channel comparison, fail-closed staging-only container guard, disposable real MongoDB BSON/Redis DUMP recovery fixture tests, and CI Compose validation. **CI passed** ([run 40805561186](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40805561186)), including actual CI MongoDB/Redis recovery fixtures and safe staging Compose checks; **operator-run staging Telegram, Atlas snapshot, Redis RDB/AOF restores, measured RTO/RPO and approval remain pending.**
- [ ] Record actual SLO baseline before proposing latency thresholds. Suggested metrics are **targets to define**, not measured facts.

### Phase 1: correctness/security before scaling

- [x] PH-001: central banned/unknown-user gate added and unit regression tests committed on this branch. **Verification:** full pytest and compilation passed in [GitHub Actions run 40704480842](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40704480842); staging, real Telegram workflows, and runtime configuration combinations remain pending; status remains In review.
- [x] PH-002 code and error-injection regression tests committed for **single-database media search**. **Verification pending**: CI result, staging MongoDB failure/recovery drill and real Telegram callbacks. Multi-DB mode remains deferred as PH-027.
- [x] PH-004: **Deferred by operator**, based on secure network isolation. No endpoint hardening; revisit if deployment exposure changes.
- [x] PH-010 opt-in code committed: file-backed Redis ACL credentials, independent state/cache secrets, generated non-overwriting ACL files, optional Compose overlay, no Redis port publication, auth unit tests and ephemeral real-Redis CI smoke. **Default deployment remains unchanged; CI passed ([run 40800650194](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40800650194)), staging cutover/network/rotation checks pending.**
- [x] PH-003 protected state integration remains opt-in. PH-011 code now implements atomic Redis generation on both unsplit and split deployments, no v1 fallback, fail-closed invalid counters, and bounded retries for in-flight search races. Unit and local real-Redis tests added. **CI passed ([run 40803258303](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40803258303)); staging Redis restart/mutation tests pending**; PH-003 and PH-011 In review.
- [x] PH-009 implementation committed: remove all Redis pickle load/dump paths, reject tagged/ASCII legacy pickle without executing, retain safe JSON/MessagePack wire formats, bound compressed payloads, add read-only aggregate Redis prefix+TTL inventory, malicious-payload and local Redis tests. **CI passed (run 40723920782); actual legacy-key inventory and staging session compatibility pending**; status In review.
- [x] PH-007 code and tests committed: 5-file preview, max 1000 matches per confirmation, 90-second one-time admin token, bounded 100-ID batches, strict pre-delete recount, per-batch search version invalidation, interrupted-run reconciliation and audit logging. **CI passed** ([run 40719343995](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40719343995)); real Telegram staging verification is pending; status remains In review.
- [ ] PH-022, PH-023: quota and outage recovery tests.

### Phase 2: capacity and reliability

- [x] PH-006 code/diagnostics committed: fixed-memory cache/latency histograms, existing monitoring endpoint integration, read-only MongoDB EXPLAIN/index-usage profiler, safe redundant lookahead deduplication, and unit/real-MongoDB tests. **CI passed** ([run 40717162699](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40717162699)); **production p95/cache-hit/EXPLAIN baseline pending**.
- [x] PH-014 stable single-DB sort (`indexed_at`, unique `_id`), isolated cache namespace, bounded repeated-offset/legacy comparison in PH-006 read-only EXPLAIN profiler, and unit/ephemeral MongoDB regression tests **committed**. Cursor callback migration deferred until measurement. [Runbook](docs/PAGINATION_PERFORMANCE.md). **Both CI jobs passed ([run 40809408684](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40809408684)); staging/production measurements remain outstanding. In review, not Verified.**
- [x] PH-016 central media index manifest, single startup owner, conflict detection, read-only bounded `listIndexes`/`$indexStats` auditing, and ephemeral MongoDB tests committed. [Runbook](docs/MEDIA_INDEX_AUDIT.md). **Both code CI jobs passed ([run 40812661483](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40812661483)); staging and actual index inventory still pending. In review.**
- [x] PH-005 implementation and regression tests committed: no deliberate overflow drops, corrected small-queue draining, opt-in durable MongoDB job queue with leases/backoff/dead letters and read-only monitoring. **Staging integration, restart/recovery and production enabling are pending**, so PH-005 remains In review.
- [x] PH-013 code committed: lightweight `/`, `/health`, `/live` (no DB calls), optional legacy detail `/health/details`/`?details=1`, separate bounded `/ready` MongoDB/Redis+protected-state checks, 5s/2s single-flight readiness caching; Docker healthcheck remains liveness, monitoring auth unchanged. **CI passed ([run 40808093133](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40808093133)); staging outage/monitoring compatibility checks pending; status In review.**
- [x] PH-017 code committed: 100-document projected `_id` keyset paging covers active subscribers beyond 500 without materializing an unbounded list; >1,200 fixture tests and local-only MongoDB integration added. [Runbook](docs/SAVED_SEARCH_FANOUT.md). **CI/staging pending; per-file O(N) remains and PH-018 must add durable bounded fan-out before large-scale activation.**
- [ ] PH-018: bounded durable background task admission, checkpoint/restart, fan-out and delivery retry.
- [ ] PH-019, PH-020, PH-024: concurrency correctness and Telegram throttling.
- [x] PH-015 code and regression tests committed: canonical optional width/height/quality, legacy read/search compatibility, cache revision 3, **default-off** `FEATURE_CANONICAL_MEDIA_METADATA` persistence to protect old-image rollback. [Runbook](docs/MEDIA_METADATA_CONTRACT.md). **Both CI jobs passed ([run 40811505457](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40811505457)); staging remains pending; In review.**
- [ ] PH-021: decide and test daily quota timezone policy.
- [ ] Repeat load tests and check that search functionality and metadata remain backwards compatible.

### Phase 3: growth trigger, **not scheduled now**

- [ ] Re-evaluate search infrastructure only if observed p95 latency, CPU/IO, or scans exceed agreed limits under representative traffic.
- [ ] Re-evaluate multi-database work (PH-025..PH-028) **only before enabling a second DB**.
- [ ] Do not assume that 97K records require microservices, sharding, or a separate search engine.

## 6. Release safety contract

1. **MongoDB schema safety:** preserve collection names, existing fields, `file_unique_id`, `file_id`, `file_ref`, and current records. Any additive index/field must have a separate explicit proposal and rollback path.
2. **Redis safety:** never run `FLUSHALL`, `FLUSHDB` or delete active search sessions as a general deployment step. Preserve existing TTL/callback contracts unless explicitly changed and tested.
3. **No silent data loss:** do not treat DB errors, queue overflow, missing Redis counters, or partial cross-DB failures as successful zero-result operations.
4. **Access safety:** banned users must not retrieve files regardless of premium mode, link type or handler.
5. **Deployment:** changes go through reviewed PR, focused tests + full suite, staging, limited rollout and production metrics. No direct production DB changes in documentation-only work.
6. **Rollback:** document application image/commit rollback, possible cache-key transition, and whether DB migration or restoration is necessary.
7. **Secrets/privacy:** do not commit production URIs, tokens, API hashes, user identifiers, screenshots containing secrets, or raw production dumps.
8. **Evidence:** code review findings cannot be marked Verified without reproducible tests and, where needed, production/staging measurements.

## 7. Verification template for each fix

Copy this section into the PR or issue discussion for any ID.

| Field | Value |
|---|---|
| Tracker ID(s) | PH-XXX |
| Root cause and reproduction | TBD |
| Code paths changed | TBD |
| Data compatibility | No schema change / explicit reviewed migration |
| Tests added | Unit + integration + regression |
| Failure/rollback rehearsal | TBD |
| Staging verification | TBD |
| Production verification | TBD |
| Before/after metrics | TBD |
| Final status and commit/PR | Update after verification |

## 8. Metrics and scaling decision gates

The following measurements are required **before choosing a new database/search architecture**:

| Metric | Why it matters | Source |
|---|---|---|
| Search p50/p95/p99 and max duration, cache hit vs miss | User-perceived speed vs actual MongoDB cost | Application metrics |
| Query `totalDocsExamined`, `totalKeysExamined`, `nReturned`, `executionTimeMillis` | Determine if indexes help or queries scan most records | MongoDB `explain("executionStats")` |
| Regex search frequency and distinct-query cardinality | Predict cache efficiency and cache stampede risk | Safe aggregated search telemetry |
| `used_memory`, `maxmemory`, `evicted_keys`, `keyspace_hits`, `keyspace_misses` | Show eviction and caching health | Redis `INFO` |
| Index count, index bytes and usage | Avoid redundant write/storage overhead | MongoDB `getIndexes()`, `$indexStats` |
| Queue depth, overflow, oldest queued age, dropped messages | Detect unrecoverable indexing gaps | Bot metrics |
| File delivery attempts, successes, failures, quota reservations/refunds | Detect accounting drift | Application metrics |
| Notification queue depth and delivery lag | Detect saved-search fan-out problems | Application metrics |
| Backup restore test result, age of last good backup | Verify recoverability | Operational records |

**Suggested investigation trigger (not a current measured SLA):** sustained non-zero indexing drops; any unauthorized file delivery; repeatable false "no results" on DB outage; Redis evictions affecting operational keys; significant growing query scan ratios and latency. Set numeric latency thresholds only after collecting a real baseline.

## 9. Previously merged search/cache changes

Current baseline already includes:

- [PR #1](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/1): backward-compatible filename, episode, season and quality matching; tests added.
- [PR #2](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/2): algorithm-aware Redis cache keys, normalized query keys and shorter zero-result TTL.
- [PR #3](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/3): additional merged search branch integration.

These are **merged**, not proof that full project tests, load tests or a production smoke-test suite passed. Keep their compatibility contract while addressing future issues. The code baseline is a repository snapshot, not a read of the running production container.

## 10. External references

- [MongoDB query explain results](https://www.mongodb.com/docs/manual/reference/explain-results/)
- [MongoDB cursor skip and range-based pagination](https://www.mongodb.com/docs/manual/reference/method/cursor.skip/)
- [MongoDB query performance and index considerations](https://www.mongodb.com/docs/manual/administration/query/)
- [Redis key eviction policies](https://redis.io/docs/latest/develop/reference/eviction/)
- [Python pickle security warning](https://docs.python.org/3/library/pickle.html)

## 11. Change log

| Date (UTC+05:30) | Change | Reference |
|---|---|---|
| 2026-10-28 | Initialized production-specific source-of-truth tracker for one MongoDB database (~97K media records). Prioritized active security/reliability issues, preserved older registers, and deferred multi-DB risks. | Documentation PR |
| 2026-10-28 | Began PH-001: centralized ban checks and fail-closed unknown users, tests and PH-008 initial GitHub Actions CI. Corrected previous assumption about send-all decorator. No DB/Redis changes. | [PR #4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4) |
| 2026-10-28 | Full pytest suite and compileall passed on first completed GitHub Actions run. Updated Actions runtime to Node24-compatible current versions; staging smoke checks remain pending. | [CI run 40704480842](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40704480842) |
| 2026-10-28 | Implemented PH-002 typed single-DB media search failure handling, protected Redis from false zero-result cache entries, added retry messaging and outage regression tests. Multi-DB partial-failure handling remains PH-027. | [PR #4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4) |
| 2026-10-28 | PH-002 full regression suite and Python compilation passed; status remains In review pending staging database outage and Telegram recovery test. | [CI run 40705992474](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40705992474) |
| 2026-10-28 | Implemented opt-in protected state Redis, key routing, fail-closed operational writes, distinct search-cache generation, memory/eviction monitoring, and non-destructive migration/rollback utility. No production activation. | [PH-003 runbook](docs/REDIS_PROTECTED_STATE.md), [PR #4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4) |
| 2026-10-28 | PH-003 compileall and full pytest completed successfully; keep In review until dedicated Redis staging test and rollback rehearsal. | [CI run 40709170782](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40709170782) |
| 2026-10-28 | Operator deferred PH-004 HTTP monitoring endpoint hardening under existing secure-network assumption. PH-013 health-check performance remains distinct and open. | [PR #4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4) |
| 2026-10-28 | PH-005: fixed legacy overflow dropping and small-queue drain, added opt-in MongoDB durable channel indexing with leases/retries/dead-letter recovery, CI tests and staging runbook. Not enabled in production. | [Runbook](docs/INDEXING_RELIABILITY.md), [PR #4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4) |
| 2026-10-28 | Added localhost-only ephemeral MongoDB integration coverage for PH-005 queue leases, acknowledgments, retries, TTL indexes and dead letters. Full pytest and compilation passed with MongoDB CI service. PH-005 stays In review pending staging crash/recovery and Telegram burst tests. | [CI run 40711957585](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40711957585) |
| 2026-10-28 | PH-006: implemented bounded search telemetry, existing metrics integration, slow-query logging, read-only MongoDB EXPLAIN profiler, redundant regex lookahead optimization, and unit/ephemeral MongoDB tests. Performance baseline remains to be collected. | [Profiling runbook](docs/SEARCH_PERFORMANCE_BASELINE.md), [PR #4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4) |
| 2026-10-28 | PH-006 code passed full Python compilation, pytest and real ephemeral MongoDB EXPLAIN/index tests. Histogram overflow correctly reports >10000 ms. PH-006 remains In review until representative production performance data is collected. | [CI run 40717162699](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40717162699) |
| 2026-10-28 | PH-007: bounded 100-ID bulk deletions, 1000-match guard, preview, one-time admin confirmation, audit/partial recovery, delete-channel backpressure, unit and local MongoDB tests. Full CI passed with delete-channel backpressure changes; staging confirmation tests remain. | [Runbook](docs/SAFE_BULK_DELETION.md), [PR #4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4) |
| 2026-10-28 | PH-007 final source and regression tests passed Python compileall, full pytest, and ephemeral MongoDB integration. PH-007 remains In review until staging real-Telegram confirmation, failure and restore tests. | [CI run 40719343995](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40719343995) |
| 2026-10-28 | PH-008: SHA-pinned least-privilege CI, MongoDB+dual Redis integration, coverage and targeted lint, Compose and production Dockerfile build preflight, PR/release checklists. Admin branch protection read returned 403; no repo settings changed. Final CI pending. | [Release runbook](docs/CI_CD_RELEASE_GATES.md), [PR #4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4) |
| 2026-10-28 | PH-008 both CI jobs passed, including dual Redis+MongoDB integration, static lint, coverage, production Dockerfile build and Compose validation. Initial Python coverage baseline: 41% (14,022 statements, 8,340 uncovered). Remains In review until admin-enforced checks and staging. | [CI run 40721208499](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40721208499) |
| 2026-10-28 | PH-009: removed executable Redis pickle paths, retained safe cache formats, bounded decompression, added safe legacy-format audit and malicious-payload/Redis regression tests. No migration/deployment. CI and live-format inventory pending. | [Runbook](docs/SAFE_REDIS_SERIALIZATION.md), [PR #4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4) |
| 2026-10-28 | PH-009 unsafe-pickle remediation passed full Python tests, real Redis+MongoDB integration, lint and Docker build after correcting MessagePack decoder limits. 41% baseline coverage; no production migration. Phase remains In review until read-only inventory/staging smoke. | [CI run 40723920782](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40723920782) |
| 2026-10-29 | PH-010 opt-in file-backed Redis ACL auth with separate cache/state passwords, secure Compose overlay, read-only credentials in app tools, ACL generator and tests; no production activation. CI and staging validation pending. | [Runbook](docs/REDIS_ACCESS_SECURITY.md), [Draft PR #4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4) |
| 2026-10-29 | PH-010 complete CI passed: Python regression and real Redis/MongoDB tests, optional authenticated Redis ACL NOAUTH/authorized smoke, Compose overlay checks and Docker build. No production activation; PH-010 In review pending staged network/secret cutover. | [CI run 40800650194](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40800650194) |
| 2026-10-29 | PH-011 atomic non-expiring Redis generation, fail-closed resets, bounded in-flight search retries, real Redis concurrency/reset tests and source-of-truth runbook. CI/staging pending. | [Runbook](docs/SEARCH_CACHE_GENERATION.md), [Draft PR #4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4) |
| 2026-10-29 | PH-011 full CI passed after preserving exact Redis 64-bit integer generations in Lua results and aligning concurrency test pool sizes. Both pytest/MongoDB/Redis and container-preflight green. No deployment; staging Redis restart/indexing load test pending. | [CI run 40803258303](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40803258303) |
| 2026-10-29 | PH-012 separate staging Compose project, Docker secret exclusion, offline production/staging identity preflight and container guard, disposable Mongo/Redis fixture recovery tests, staging and backup/restore runbook. No live infrastructure touched; CI and operator-run RTO/RPO restore evidence pending. | [Runbook](docs/STAGING_AND_RECOVERY.md), [Draft PR #4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4) |
| 2026-10-29 | PH-012 full CI passed: staging env comparison/Compose checks, Docker build and disposable Mongo BSON/index and Redis DUMP/RESTORE fixture tests. Real Atlas backup, Redis RDB/AOF restore, Telegram staging, RTO/RPO and operator approval remain outstanding. | [CI run 40805561186](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40805561186) |
| 2026-10-29 | PH-013: cheap /health and /live, bounded coalesced /ready MongoDB/Redis pings, legacy stats only on demand; Docker liveness unchanged. Regression suite and migration runbook added. CI/staging pending; PH-004 auth deferral preserved. | [Runbook](docs/HEALTH_PROBES.md), [PR #4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4) |
| 2026-10-29 | PH-013 both CI jobs passed: cheap liveness, cached bounded readiness, preserved explicit legacy diagnostic JSON and unchanged metrics. Staging compatibility and outage tests remain pending; PH-004 auth deferral preserved. | [CI run 40808093133](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40808093133) |
| 2026-10-29 | PH-014 single-DB deterministic offset sort and cache namespace, bounded legacy-vs-stable deep-offset EXPLAIN profiling, MongoDB regression test fixture, cursor decision and staging gates. No live database changes; CI and measured p95 pending. | [Runbook](docs/PAGINATION_PERFORMANCE.md), [Draft PR #4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4) |
| 2026-10-29 | PH-014 CI gate passed after correcting the test fixture's 24-operation edge case (24 permitted, more rejected). Both full pytest/MongoDB/Redis and Docker/Compose preflight passed on code SHA f838be99; no live DB tests. Staging ordering/callback tests, legacy-vs-new EXPLAIN and p95 still pending. | [CI run 40809408684](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40809408684) |
| 2026-10-29 | PH-015 canonical optional dimensions/quality, legacy read/search adapter, search cache rev 3, default-off storage write flag, isolated MongoDB regression and zero-migration/rollback runbook. No production data touched; CI and staging pending. | [Runbook](docs/MEDIA_METADATA_CONTRACT.md), [Draft PR #4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4) |
| 2026-10-29 | PH-015 full CI passed after repairing a pre-existing Wzgram dependency-manifest drift: `requirements.txt` now pins the same upstream commit as `pyproject.toml` and the packaging contract. Both pytest/MongoDB/Redis and Docker container-preflight passed at SHA `40b4a5da`. Feature flag remains default-off; no deployment or database mutation. | [CI run 40811505457](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40811505457), [Runbook](docs/MEDIA_METADATA_CONTRACT.md) |
| 2026-10-29 | PH-016 removed duplicate media index startup passes, consolidated historic declarations without new index names, added fail-visible drift checks and a bounded read-only operator index audit. Actual MongoDB index inventory and query plans not obtained; CI and staging pending. | [Runbook](docs/MEDIA_INDEX_AUDIT.md), [Draft PR #4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4) |
| 2026-10-29 | PH-016 full Python pytest and ephemeral MongoDB/dual-Redis tests, compile/lint and Docker/Compose preflight **passed** at code SHA `65da6746`. First run exposed unsupported PyMongo list_indexes(maxTimeMS), corrected to supported API with bounded client socket timeout. No production index DDL was run. Staging index inventory and measured query plans remain mandatory. | [CI run 40812661483](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40812661483), [Runbook](docs/MEDIA_INDEX_AUDIT.md) |
| 2026-10-29 | PH-017 replaced newest-500 alert omission with projected 100-item keyset pages, stable `_id` ordering, cooperative yielding, error visibility, >1,200 regression fixture and disposable MongoDB integration; no schema/index/data changes. CI and staging pending; PH-018 durable fan-out outstanding. | [Runbook](docs/SAVED_SEARCH_FANOUT.md), [Draft PR #4](https://github.com/rumalg123/Advanced-File-Filter-Bot/pull/4) |
