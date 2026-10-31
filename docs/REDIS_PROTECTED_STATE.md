# Protected Redis state: design, safe cutover and rollback (PH-003)

**Operator-authorized cold restart (2026-10-29):** up to 24 hours of downtime and
full Redis state loss are accepted for the production cutover. That path can
start both instances empty and skip the state-copy migration below. It still
requires production backup/configuration checks, sizing and startup verification.
See the [production cutover runbook](PRODUCTION_CUTOVER.md). The preservation
workflow below remains applicable when operational Redis state must survive.

> **Status: staged only. Not deployed. Do not enable in production until CI, staging migration, memory measurements and rollback drills are complete.**

## Why this exists

The original Redis server in `redis.conf` uses `allkeys-lru` and a 256 MB memory cap. Any key, including search sessions, rate-limit counters and the search-cache generation, can be evicted as memory fills.

The new optional architecture separates Redis roles:

| Server | Keys | Eviction | Production default |
|---|---|---|---|
| Current `redis` | Search-result pages, media/user caches, recommendations and other disposable data | `allkeys-lru` | **Unchanged** |
| New `redis-state` | Rate limits, session pointers/data, search button sessions, subscription/deep-link sessions, operational flags and the search generation counter | `noeviction` + AOF | **Disabled until explicitly enabled** |

A separate Redis database **number** on the same Redis server is **not** an independent memory/eviction domain. `RoutedCacheManager` refuses the same host/port, even with a different database number. Use an actual separate Redis service/instance.

### What the code does

- `REDIS_STATE_URI` is empty by default, preserving the **existing** `CacheManager` and key locations.
- When set, `RoutedCacheManager` selects the backend by a fixed, audited key prefix allowlist (`STATE_PREFIXES`).
- No state action fails over to the disposable cache. The application fails startup if either configured server cannot initialize.
- Limiter writes fail closed in protected mode. Single-Redis legacy fail-open behavior remains tracked under PH-023.
- Search-cache generation is initialized to a **random high positive integer** on loss/restart. Search-result keys also include a split-mode namespace, so old page cache entries cannot be reused after cutover.
- Redis failures cannot create "successful" sessions or fake working file/pagination buttons. Failed search generation returns the existing temporary-search-unavailable response.
- Memory, policy and eviction metrics are separated by Redis instance.
- The optional `redis-state` service is on an internal-only Docker network, without published host ports.

### Separate-container startup verification

BUG-059 reproduced a loopback-only `DENIED` response with the original
`protected-mode yes` setting and no credentials. A local Redis health probe
could pass while the bot's container could not connect. The default state
config now permits connections on the private internal Compose network; it
must never be published or reused on a public network. The optional ACL overlay
continues to require authentication when enabled.

Run `bash scripts/test_redis_compose_network.sh` on a Docker-capable QA host.
It tests the committed cache/state configs from distinct containers, requires
an actual `PONG` (Redis CLI can exit zero for a denial), publishes no ports and
cleans its temporary containers/network/volumes. It failed before the fix and
passed afterward. CI container preflight now includes this check.

The Redis service user must be able to read its mounted configuration. On the
deployment host, make the two non-secret config files readable with
`chmod 0644 redis.conf redis-state.conf`. Keep `.env` and credential directories
private; do not apply that command indiscriminately to secret files.

## Release prerequisites (do not skip)

1. Obtain **read-only** Redis measurements on production, including `INFO memory` and `INFO stats`. Record `used_memory`, `maxmemory`, `maxmemory_policy` and `evicted_keys` before rollout. A 256 MB cap is **not** a recommended capacity without measurements.
2. Verify adequate RAM for two Redis processes and the bot. `noeviction` prevents Redis from deleting state to make space, **not** from rejecting writes if state memory reaches its limit.
3. Verify existing Redis AOF backups and data retention. Practice restoring them on staging. Never commit credentials or Redis datasets to GitHub.
4. Exercise `tests/test_protected_redis_state.py` and `tests/test_redis_state_migration.py` under CI and run a dedicated integration test using two **ephemeral** Redis instances, one LRU and one `noeviction`.
5. Verify the full bot on staging: search, pagination, send-all, subscription, premium batch, rate-limit expiry, cancellation and restart.
6. Test **cutover AND rollback** during staging downtime, including restoring a state version counter and ensuring Redis search keys cannot collide. Track access-denied rates and session expiry.
7. Do not change the currently deployed Redis eviction policy or flush either instance. PH-010 (Redis authentication/secret management) remains separate.

## Staging cutover with Docker Compose

These are **runbook examples** to be executed on a staging deployment only until signed off.

First start the protected state Redis service without changing the bot's current connection:

```bash
docker compose --profile protected-state up -d redis-state
docker compose --profile protected-state ps redis-state
docker compose --profile protected-state exec redis-state redis-cli INFO memory
```

From the shell where Compose is run, configure the additional backend (the existing `REDIS_URI` stays unchanged):

```bash
export REDIS_STATE_URI=redis://redis-state:6379/0
```

**Stop every instance of the bot before transferring operational state.** No writers may use the old Redis during the transfer; otherwise counters and active sessions can diverge. The helper uses raw Redis DUMP/RESTORE with PTTL preservation and copies only the allowlisted operational keys. It never deletes source keys. Credentials are read from environment variables, not passed as CLI arguments.

```bash
docker compose stop file-filter-bot

# Non-mutating inventory first
docker compose --profile protected-state run --rm --no-deps \
  --entrypoint python file-filter-bot scripts/migrate_redis_state.py

# Explicit non-destructive copy after reviewing the inventory
docker compose --profile protected-state run --rm --no-deps \
  --entrypoint python file-filter-bot scripts/migrate_redis_state.py \
  --apply --bot-stopped

# Start the bot in split mode after verifying both Redis connections
docker compose --profile protected-state up -d file-filter-bot
```

Verify `REDIS_STATE_URI` actually reached the bot container, and check that the service initializes both Redis instances successfully without publishing connection secrets. Use representative test accounts and do **not** run destructive commands.

### Cache version and old buttons

The migration preserves session pointers, search result button sessions, rate limits, cooldowns and the search cache counter. The new search-result cache namespace avoids collisions with older cached pages. Existing button callbacks retain their original identifiers and TTLs.

Any key that expired during the migration cannot be restored, which is expected. Redis session expiry should not be extended. The migrator **never** copies arbitrary user/media/search caches.

### Rollback during staging or emergency operations

**Stop all bot instances first.** A code-only rollback to a version with a single Redis backend can otherwise read stale session/rate-limit keys left in the old Redis.

After taking backups and verifying the latest state Redis, copy operational keys back **from state Redis to original Redis**. Use the bot container's environment overrides to reverse source/destination:

```bash
docker compose stop file-filter-bot

# Inspect the reverse copy first (read-only)
docker compose --profile protected-state run --rm --no-deps \
  -e REDIS_URI=redis://redis-state:6379/0 \
  -e REDIS_STATE_URI=redis://redis:6379/0 \
  --entrypoint python file-filter-bot scripts/migrate_redis_state.py

# Only during an approved rollback, overwrite old destination state
docker compose --profile protected-state run --rm --no-deps \
  -e REDIS_URI=redis://redis-state:6379/0 \
  -e REDIS_STATE_URI=redis://redis:6379/0 \
  --entrypoint python file-filter-bot scripts/migrate_redis_state.py \
  --apply --bot-stopped --replace-existing

# Unset additional backend and restart the single-Redis bot image/commit
unset REDIS_STATE_URI
docker compose up -d file-filter-bot
```

The rollback script only replaces matching operational state keys in the old Redis. It does not clear any keys that were created only on the destination or are no longer valid; test cleanup and expiry separately. It must **never run concurrently with live bot writers**.

## Operational monitoring and alerts

Record/alert separately for **both** servers:

- `used_memory / maxmemory`, fragmentation, `evicted_keys`, `maxmemory_policy`.
- State Redis denied writes / OOM errors, connection failures, `aof_last_write_status` and `rdb_last_bgsave_status`.
- Search generation failure rate and zero-result cache hit/miss behavior.
- Rate-limit failures, session creation failures, expired callback counts.
- Stateful Redis startup/recovery and backup age.

A state Redis memory cap with `noeviction` trades silent state loss for **visible write errors**. Provision headroom and test those errors, rather than assuming that noeviction guarantees availability.

## Outstanding risks and release gate

- **PH-003 remains In review**, because no live Redis metrics, staging cutover or rollback validation have been supplied.
- **PH-011 is partially addressed** by a random counter generation, but eviction/reset and invalidation races should still be integration-tested.
- **PH-010 remains open**: the internal Docker network is not a replacement for suitable authentication/TLS, secret rotation and host isolation in more exposed environments.
- **PH-023 remains open**: single-Redis legacy rate-limit behavior continues to fail open during Redis outage.
- If multiple application instances are in use, verify they all switch together during an approved maintenance window. Running mixed old/new Redis routing against active users will produce inconsistent state.
- No MongoDB schema, media records, indexes or migration scripts are touched by this change.

## References

- [Redis eviction policies](https://redis.io/docs/latest/develop/reference/eviction/)
- [Redis persistence](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/)
- [Redis DUMP/RESTORE](https://redis.io/docs/latest/commands/restore/)
