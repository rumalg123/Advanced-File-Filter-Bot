# PH-013: Lightweight liveness, bounded readiness and diagnostic separation

**Status:** code and regression tests committed on the existing hardening branch
and Draft PR #4. Production has not been changed or deployed.

## What was wrong

The original `GET /health` and `GET /` called
`MaintenanceService.get_system_health_data()` on **every request**.
That collects user statistics, file counts, cache TTLs and MongoDB
storage statistics (`dbStats`), potentially involving multiple network
operations and expensive aggregations. An outage could make liveness slow,
and the Docker healthcheck could trigger restarts even while the Python
HTTP event loop was functioning.

Kubernetes recommends separating **liveness** (is the process alive?)
from **readiness** (can its dependencies serve requests?).
See [Liveness, Readiness, Startup Probes](https://kubernetes.io/docs/concepts/workloads/pods/probes/)
and [Docker Compose health checks](https://docs.docker.com/compose/how-tos/startup-order/).

## New API behavior

| GET path | Behavior | Status |
|---|---|---|
| `/` and `/health` | **Cheap liveness**: static process/bot identity only; no DB, Redis, user counts or `dbStats` | HTTP 200 while HTTP server responds |
| `/live` | Alias for cheap liveness | HTTP 200 |
| `/ready` | Bounded MongoDB `ping`, Redis `PING` and protected-state Redis `PING` if enabled; no statistics or document reads | HTTP 200 if all required connections work, otherwise 503 |
| `/health/details` | Legacy detailed user/media/database-storage health report; collected **only on explicit request** | Preserves old healthy/degraded 200 and unhealthy 503 semantics |
| `/health?details=1` | Backward-compatible on-demand detailed report at the original URL | As above |
| `/metrics`, `/performance` | **Unchanged**, including PH-006 search telemetry | Existing behavior |

**Compatibility note:** response bodies at `/health` and `/` are intentionally
now lightweight and no longer include `stats` or `meta`. Existing
dashboards that parse those fields must switch to `/health/details` or
`/health?details=1`. Existing callers which only require an HTTP 200
healthcheck continue to work. An HTTP 200 at `/health` does **not**
mean the bot's MongoDB or Redis services are available; use `/ready`
for that distinction.

## Safety / cost controls

- MongoDB uses a **single direct `ping`**, not `dbStats`,
  `get_file_stats` or a retrying database helper.
- Redis uses a direct `PING`. The optional PH-003 protected-state backend
  is also checked independently and cannot silently fall back to disposable
  cache Redis.
- All dependency pings run **concurrently**, each with a **0.75-second
  application timeout**. A missing connection returns `unavailable`.
- Readiness checks are **single-flight**, so concurrent HTTP requests reuse
  the same measurement. A ready result is cached for **5 seconds** and a
  failed result for **2 seconds** to limit load while recovering promptly.
  Probe error text and connection URIs are never returned to HTTP clients.
- Dockerfile, production Compose, and staging Compose **continue using
  `/health`**, not `/ready`, for their container health checks. This
  avoids restarting the application during a transient MongoDB/Redis
  outage. Compose itself does not automatically route real Telegram
  polling traffic based on readiness, so `/ready` is an operational
  signal, not an actual traffic-draining mechanism.
- The expensive legacy diagnostic path remains available only
  **on demand**. `MaintenanceService` and its statistics code are not
  modified, and monitoring credentials, CORS, listening host/port and
  `/metrics` are unchanged. PH-004 endpoint authentication remains
  **deferred by operator** under the existing secure-network assumption.

### What these checks do **not** guarantee

- HTTP liveness cannot prove Telegram API connectivity or that all bot
  workers are responding. The web server only starts after the bot's
  initial Telegram client startup and handler installation.
- A green readiness response is a recent, at-most-5-second-old observation,
  not a transaction or continuous guarantee of DB/Redis availability.
- Readiness checks the primary MongoDB connection only. Multi-database
  partial availability and search degradation are future PH-027 work.
- The 0.75-second timeout may need tuning under real-world network
  latency in staging; too-small timeouts can cause false negatives.
- Explicit `/health/details` requests still perform legacy statistics
  collection and may be slow. They must not be configured as a frequent
  liveness or readiness probe.

## Staging verification

- [ ] Full Python suite, HTTP handler tests, MongoDB/Redis integration
  and Docker preflight pass on the exact branch SHA.
- [ ] In isolated staging, `curl -f http://127.0.0.1:8000/health`
  remains fast while MongoDB/Redis are unavailable.
- [ ] `GET /ready` shows HTTP 503 during a forced Mongo/Redis outage,
  with `dependencies.mongodb` / `dependencies.redis` statuses,
  then recovers to 200 on reconnection.
- [ ] When `REDIS_STATE_URI` is configured, a state-only outage must
  mark readiness 503 without treating cache Redis as a fallback.
- [ ] `/health/details` and `/health?details=1` preserve previous
  on-demand diagnostic fields. Existing monitors parsing the old
  `/health` JSON are migrated before rollout.
- [ ] Repeated/concurrent `/ready` requests avoid database-statistics
  work and remain bounded. Capture real p95 timing instead of assuming
  the test 0.75-second timeout is appropriate for Atlas latency.
- [ ] Verify bot restart and successful Telegram search, file delivery,
  callback handling and pagination after transient outages.
- [ ] Record rollback to the prior reviewed image; rollback reintroduces
  expensive `/health` behavior and can cause restart storms during
  storage outages.

**No MongoDB collection/index/document changes, Redis key migrations,
Redis flush, Telegram button format changes, port/bind changes, automatic
deployment or GitHub merge occur in this phase.**
