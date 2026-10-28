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
| PH-004 | **P1** | Open | Code-confirmed exposure surface: [`bot.py`](bot.py) `_start_web_server`, [`docker-compose.yml`](docker-compose.yml) | Health/metrics/performance endpoints have no app authorization; bot binds all interfaces and Compose publishes port 8000. Actual Internet reachability is **unverified**. | Restrict detailed metrics to private/authenticated access; keep liveness minimal; verify firewall/port exposure from outside. |
| PH-005 | **P1** | Open | Code-confirmed: [`handlers/channel.py`](handlers/channel.py) `handle_channel_media` | Full in-memory primary and overflow queues discard the oldest item; crash can lose unprocessed indexing events. | Durable recovery/checkpoints, idempotent replay, alerts on loss, and test for overload/restart recovery; no silent loss. |
| PH-006 | **P1** | Open | Needs measurement: [`core/utils/search_matcher.py`](core/utils/search_matcher.py), [`repositories/media.py`](repositories/media.py) | Case-insensitive regex, multi-token lookaheads, and exact counts may scan many media records for uncached searches. | Capture representative `explain("executionStats")`, docs examined, p50/p95/p99, cache hit ratio, and compare an indexed candidate strategy before implementing new fields. |
| PH-007 | **P1** | Open | Code-confirmed: [`repositories/media.py`](repositories/media.py) `delete_files_by_keyword`, [`core/database/base.py`](core/database/base.py) `find_many` | Broad deletion first materializes matching records, potentially without a limit, then invalidates every file cache. | Add bounded, resumable, preview/confirm delete workflow with permission checks, audit trail, and dry-run; test on a large fixture. |
| PH-008 | **P1** | In progress | Repo observation: no `.github/workflows` in baseline tree; `main` not protected at observation | The GitHub Actions compile/pytest workflow exists and passes on this branch. `main` is not yet protected and MongoDB/Redis integration tests and required checks remain pending. | Add automated lint, tests, MongoDB/Redis integration tests, PR branch protection where permitted, and smoke test before deploy. |
| PH-009 | **P1** | Open | Conditional: [`core/cache/serialization.py`](core/cache/serialization.py) `_deserialize_pickle`, `_deserialize_legacy_data` | Legacy Redis deserialization still invokes `pickle.loads`; unsafe when cache content may be influenced by an attacker. | Inventory real legacy keys, design safe compatibility transition, remove unsafe unpickling, and regression-test malformed values. |
| PH-010 | **P1** | Open | Conditional: [`redis.conf`](redis.conf), [`docker-compose.yml`](docker-compose.yml) | Redis is configured without a password and binds all container interfaces. Compose does **not** publish Redis publicly by default, so risk depends on Docker-network isolation. | Confirm actual network reachability/credentials, restrict clients, provide authentication and rotation plan, and avoid embedding secrets in repo. |
| PH-011 | **P1** | In progress | Conditional: [`core/cache/invalidation.py`](core/cache/invalidation.py), [`core/cache/config.py`](core/cache/config.py) | The split-state path now initializes a random positive cache generation and separates new search cache keys, but state reset/invalidation races still need integration validation; single-Redis legacy behavior is unchanged. | Make generation identity robust to eviction/restarts; test missing-counter and concurrent-write scenarios without global Redis flush. |
| PH-012 | **P1** | Investigating | Operational evidence missing | Backup, restore, recovery time, and production environment parity have not been verified in this audit. **Not** a claim that backups do not exist. | Record backup retention, encrypted access, restoration rehearsal, recovery goals, and roll-forward/rollback procedure. |
| PH-013 | **P2** | Open | Code-confirmed: [`core/services/maintenance.py`](core/services/maintenance.py) `get_system_health_data`, [`bot.py`](bot.py) health endpoint | Liveness requests perform application/database statistics work; heavy or failing stats can impact health checks. | Split lightweight liveness, bounded readiness probes, and separately authenticated diagnostic metrics. |
| PH-014 | **P2** | Open | Code-confirmed: [`repositories/media.py`](repositories/media.py) `search_files`; [`core/database/base.py`](core/database/base.py) `find_many` | Every uncached search performs count + page read, with offset pagination and sort on `indexed_at` alone. Deep pages can slow and equal timestamps can be unstable. | Benchmark deep pages; add stable secondary sort; evaluate keyset/cursor pagination with backwards-compatible button semantics. |
| PH-015 | **P2** | Open | Code-confirmed: [`core/utils/media_factory.py`](core/utils/media_factory.py), [`core/utils/search_matcher.py`](core/utils/search_matcher.py) | `resolution` mixes dimensions (`960x540`) and quality labels (`540p`); fallback matching fixes searches, not canonical data semantics. | Define stable width/height/quality semantics; preserve legacy reads; any backfill must be optional, dry-run, and reversible. |
| PH-016 | **P2** | Open | Code-confirmed: [`repositories/media.py`](repositories/media.py) `create_indexes`, [`core/database/indexes.py`](core/database/indexes.py) | Two code paths create media indexes; the screenshot shows 18 on `media_files`. Some are potentially overlapping and some search indexes may not help regex queries. | Inventory actual `getIndexes()` and `$indexStats`; reconcile ownership and query plans; **never auto-drop indexes** based on guesses. |
| PH-017 | **P2** | Open | Code-confirmed, flag-dependent: [`repositories/features.py`](repositories/features.py) `get_active_saved_searches` | Saved-search notification matching inspects only the newest 500 active searches. Beyond that, older active searches are ignored. | Paginate/target candidate searches and verify every eligible subscriber under >500 fixtures, without unbounded per-file work. |
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
- Added regression suites `tests/test_protected_redis_state.py` and `tests/test_redis_state_migration.py`; full CI verification and staging migration/load/outage drills remain necessary before considering this feature production-ready.
- **Compatibility:** no MongoDB record, collection, schema, or index change. Default Redis config and existing key locations are **unchanged**. The split-mode cutover requires explicit Redis state migration and a tested rollback.
- **Open work:** PH-011 generation/invalidation races, PH-010 Redis authentication/TLS beyond the isolated Compose network, PH-023 unsplit rate limiting fail-open, and operational state memory sizing. Do **not** mark PH-003 Verified or enable production automatically.

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
| AD-08 | Heavy operational metrics and liveness share one HTTP surface | Separate public liveness, private readiness, admin/ops diagnostics | PH-004, PH-013 |

## 5. Delivery plan and dependencies

### Phase 0: baseline, safety and verification

- [ ] Capture production environment topology **without secrets**: MongoDB version/tier, Redis version, bot replicas, current flags and resources.
- [ ] Collect **read-only** workload evidence: media count, current `getIndexes()`, `$indexStats`, common query `explain("executionStats")`, slow-query samples, app p50/p95/p99, MongoDB CPU/memory, Redis memory and evictions, indexing queue depth/drops.
- [ ] Confirm backup/restore procedures on an **isolated non-production restore**. Do not copy secrets or exposed user data into GitHub.
- [ ] Establish smoke tests covering the exact previously failing Doctor X S01E03 filename, short title, season/episode, resolution, pagination and button delivery.
- [ ] Set up a staging environment and CI gate: PH-008 and PH-012.
- [ ] Record actual SLO baseline before proposing latency thresholds. Suggested metrics are **targets to define**, not measured facts.

### Phase 1: correctness/security before scaling

- [x] PH-001: central banned/unknown-user gate added and unit regression tests committed on this branch. **Verification:** full pytest and compilation passed in [GitHub Actions run 40704480842](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40704480842); staging, real Telegram workflows, and runtime configuration combinations remain pending; status remains In review.
- [x] PH-002 code and error-injection regression tests committed for **single-database media search**. **Verification pending**: CI result, staging MongoDB failure/recovery drill and real Telegram callbacks. Multi-DB mode remains deferred as PH-027.
- [ ] PH-004, PH-010: restrict monitoring and Redis access after reachability assessment.
- [x] PH-003 and initial PH-011 code committed: optional dedicated Redis operational-state routing, `noeviction` state config, safe migration/rollback utility, unique protected search generation and failure checks. **Not deployed or verified:** staging cutover, persistence/load test, rollback drill, memory sizing, and full required CI. PH-003 In review, PH-011 In progress.
- [ ] PH-009: remove unsafe deserialization after compatibility assessment.
- [ ] PH-007: bound and audit destructive deletion operations.
- [ ] PH-022, PH-023: quota and outage recovery tests.

### Phase 2: capacity and reliability

- [ ] PH-006 and PH-014: representative uncached search profiling and pagination redesign decision.
- [ ] PH-016: inspect and rationalize indexes (no drops before measured proof).
- [ ] PH-005: indexing checkpoints, overflow recovery and replay.
- [ ] PH-013: lightweight health endpoints.
- [ ] PH-017 and PH-018: saved-search workload fan-out and notification reliability.
- [ ] PH-019, PH-020, PH-024: concurrency correctness and Telegram throttling.
- [ ] PH-015, PH-021: metadata and daily quota policy.
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
