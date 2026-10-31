# PH-023: Bounded rate limiting when Redis is unavailable

**Status:** Full code CI passed at SHA `89fadb57` ([run 40820968179](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40820968179)); operator staging pending. Existing Draft PR #4. No production deployment, database, Redis schema or index changes.

## Root cause

`RateLimiter.check_rate_limit()` previously returned **allowed** whenever an unsplit Redis backend failed to increment a counter. An attacker could send unlimited search/file requests during outages. PH-003 already failed closed for separately protected operational Redis, but did not cover normal single-Redis deployments.

## New policy

- **Healthy Redis:** preserve atomic `increment_with_expiry`, existing action limits and cooldown semantics.
- **Unsplit Redis unavailable (exception, missing counter):** use a bounded **in-process** fixed-window count keyed by `(user_id, action)`. Monotonic time avoids wall-clock jumps. When an action exceeds its configured limit, enforce the larger of the remaining window and configured cooldown.
- **Protected operational state unavailable:** continue to **fail closed**, with no local bypass.
- **Memory bound:** max **4096 active local identities per process**. On capacity, prune only expired entries; if still full, **deny new identities** with a retry cooldown. Never evict an active counter to allow another burst.
- **Recovery:** newly healthy Redis requests use Redis's counters again. The in-memory fallback remains until expiry/admin reset. This does **not** merge Redis and local counts, and therefore recovery can have a transitional limit inconsistency.
- **Observability:** `local_fallback_metrics()` exposes only aggregate entries, fallback events, capacity denials and max capacity, no usernames or tokens. Logs omit connection secrets.
- **Explicit reset:** removes the user's fallback entry and invokes existing Redis cache invalidation.

## Important limits

Local fallback is **per process**, not cluster-wide: two bot replicas each have independent limits. An actor can use up to approximately `N × limit` through N replicas when Redis is down. This is not protection against sustained distributed floods, and service-level traffic controls remain needed. There is no Redis-to-local transactional handoff or per-IP limit. In-memory entries disappear on restart. Invalid/unknown action continues to bypass as in existing caller contracts; don't pass untrusted action names directly.

The max-entries guard is deliberately fail-closed rather than allocating unbounded memory. During a broad outage it may reject legitimate *new* users until entries expire. Operators should verify error messaging and degraded service expectations before rollout.

**Reference:** Redis publishes comparison guidance on fixed windows, token buckets and tradeoffs: https://redis.io/tutorials/howtos/ratelimiting/

## Verification

- [x] Full Python tests, local disposable MongoDB/dual Redis, compile/lint and production Docker/Compose preflight passed at code SHA `89fadb57` ([CI run 40820968179](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40820968179)). The first run exposed a test's fractional FloodWait fixture; fixed in PH-024 without changing production logic.
- [x] Simulate both Redis exceptions and missing incremental results; verify normal per-action limits/cooldowns and 50-way concurrent requests for one identity.
- [x] Check independent users/actions, protected state still fails closed, healthy Redis unchanged, and reset/health recovery.
- [x] Fill local capacity, verify new identities denied, active counters not evicted and expired windows reclaimed; verify memory.
- [ ] Isolated staging: restart, repeated outages/flapping, 1 and multiple replicas, real attack/burst traffic, acceptable user impact and metrics threshold.
- [ ] Rollback of application image requires no data migration; older image reintroduces the fail-open gap.

**PH-023 remains In review** until CI and staging signoff. Do not mark this as cluster-wide protection.

**QA reconciliation (2026-10-29):** the checked contracts above passed the current disposable MongoDB/dual-Redis regression suite. Relevant real-Telegram and remote multi-source results are recorded in the [active QA evidence](qa/coverage-expansion/STATUS.md). Unchecked operational/load/rollout gates remain pending.
