# PH-012: Isolated staging, recoverability, and rollback

**Status: code and disposable CI fixture tests, not a production restore rehearsal.**
**Production is one MongoDB Atlas database.** Production infrastructure, bot
token, Redis and Docker volumes were not accessed or changed during PH-012.
An actual staging VPS/Atlas target, recovery time objective (RTO), recovery point
objective (RPO), backup status and restoration success **have not been verified**.

## Risk found in the existing deployment

The production `docker-compose.yml` has fixed `container_name` values,
host-publishes port 8000 and uses named persistent volumes. Launching it a
second time on the same VPS risks container-name conflicts, host-port collisions,
and accidental sharing with production data. The repository also had no
`.dockerignore` despite a `COPY . .` Dockerfile instruction, so local `.env`
and secret directories could enter a Docker image build.

PH-012 adds a **completely independent staging Compose file** and a
`.dockerignore` excluding local environment files, Telegram session files,
credentials, Redis dumps, logs, backups and other mutable state.

Docker documents project-scoped names and resources:
[Compose project isolation](https://docs.docker.com/compose/how-tos/project-name/).

## Staging isolation contract

| Resource | Production | Staging requirement |
|---|---|---|
| Telegram | Current bot token and channels | **Different bot token**, private test channels and separate session name |
| MongoDB | Live Atlas cluster/database | **Different cluster/server** and database name beginning `staging_` |
| Redis | Existing Redis and optional protected Redis | Dedicated staging-only Compose container/volume; no host ports |
| Docker | Existing Compose project, fixed names | `advanced-file-filter-staging` project; no fixed container names; independent networks and volumes |
| Bot HTTP health | Existing port 8000 | **Not published to host**; check using `docker compose exec` |
| Auto-updates | Disabled by default | Forced off in staging |
| Profile | Production deployment | Staging bot requires explicit `staging-bot` profile |
| Existing production data | Must not be modified | All staging writes stay in disposable/non-production resources |

Staging uses the **same Dockerfile** and Redis version/config as the production
Compose deployment, but has no forced enablement of protected Redis or durable
indexing. Do not assume optional production feature flags are staged unless
you deliberately configure and test them. Exact parity requires documenting
image digest, env variable names, database version/tier, configured feature
flags and Redis persistence mode.

### Offline preflight

Copy the example locally, **not into Git**:

```bash
cp .env.staging.example .env.staging
chmod 600 .env.staging
```

Fill in a separately created Telegram test bot from BotFather, dedicated
test Telegram channels/groups, separate Atlas cluster/username/password
(with only staging authorization), and a `staging_` database name.
Set `STAGING_OPERATOR_ACK=I_HAVE_VERIFIED_ISOLATION` only after checking
them. The example intentionally fails validation until configured.

If you have a local copy of your production effective env file, run:

```bash
python scripts/staging_preflight.py \
  --production-env /secure/path/production.env \
  --staging-env .env.staging
```

This comparison is **offline**: no Telegram, MongoDB, Redis or VPS connections.
It compares bot token, MongoDB hostnames, database names and configured
Telegram channel targets, and refuses overlaps. It never prints secret values.
It **cannot detect** different DNS names pointing to the same Atlas cluster,
missing production secrets in a partial env file, runtime dynamic channels
from the production DB, or copied identities from unrelated configuration
sources. An operator must independently verify the effective production
settings and the Atlas cluster IDs.

```bash
docker compose -f docker-compose.staging.yml config --quiet
docker compose -f docker-compose.staging.yml config --format json \
  | python scripts/validate_staging_compose.py
```

Do not print the resolved Compose config publicly; it contains environment
values including staging credentials. The structural checker reads the JSON
stream and prints only a pass/fail indicator.

### Isolated staging start

The two commands below operate **only** on the named staging project:

```bash
# Starts just the fresh staging Redis, not the bot.
docker compose -f docker-compose.staging.yml up -d redis

# Start the bot ONLY after offline identity comparison has passed.
docker compose -f docker-compose.staging.yml \
  --profile staging-bot up -d --build file-filter-bot

docker compose -f docker-compose.staging.yml ps
docker compose -f docker-compose.staging.yml \
  exec file-filter-bot curl -fsS http://127.0.0.1:8000/health
```

The container starts with a second `--runtime` preflight enforcing staging
environment, acknowledgment, database prefix, test session, private Redis,
disabled updater and configured test channels. The container does **not**
receive the production env file, so it cannot repeat the full token/cluster
comparison itself. Run the offline host check before every credential or
infrastructure change. Do not use the production Compose file for staging.

Never run both production and staging bot instances with the **same Telegram
token**: they can compete for updates and duplicate indexing.

### Staging stop and cleanup

```bash
docker compose -f docker-compose.staging.yml \
  --profile staging-bot stop file-filter-bot
docker compose -f docker-compose.staging.yml \
  --profile staging-bot down
```

Do **not** use `down -v` by default. The `-v` flag removes named volumes.
The staging Compose project must be independently verified before any
intentional disposal of its staging volumes.

## MongoDB Atlas backup and restoration drill

A **green CI run does not prove production Atlas backups exist or are restorable**.
Atlas documents restoring snapshots into a **new cluster** for isolation,
and instructs operators to stop target client traffic while restoring.
Atlas cloud backup availability depends on the tier; free clusters may require
manual `mongodump`/`mongorestore` instead.

References:
- [Atlas backup and restore](https://www.mongodb.com/docs/atlas/backup-restore-cluster/)
- [Atlas restore workflow](https://www.mongodb.com/docs/atlas/backup/cloud-backup/restore-overview/)
- [MongoDB Database Tools: mongorestore](https://www.mongodb.com/docs/database-tools/mongorestore/)

Required operator verification **before actual restoration**:

1. Confirm source **cluster ID**, source database and collection names, cluster
   version/FCV, backup tier, snapshot timestamp/retention and restore access.
2. Create a **new, empty test restore cluster** (preferred) or an explicitly
   disposable `staging_restore_...` namespace on a staging-only cluster.
   Never choose the production cluster as a restore target.
3. If eligible, use Atlas Backup UI to restore a known-good snapshot to that
   *new* cluster. Keep all app writers disconnected from the target.
4. If testing an approved `mongodump`-based backup, use a restricted
   staging-only backup account and a protected, encrypted backup destination.
   Never put a URI with embedded credentials in GitHub logs or a shared
   terminal recording.

Example for staging-only databases. Supply `STAGING_MONGO_URI` through
approved local secret injection; CLI arguments can be visible in process
lists, so prefer MongoDB Database Tools' protected configuration file where
supported.

```bash
# THESE ARE EXAMPLES. Do not run until STAGING_MONGO_URI is verified as staging.
export STAGING_DB=staging_filefilter
export RESTORE_DB=staging_restore_drill_20261029
export ARCHIVE=/secure/staging-backups/staging-filefilter.archive.gz

mongodump --uri "$STAGING_MONGO_URI" --db "$STAGING_DB" \
  --gzip --archive="$ARCHIVE"
sha256sum "$ARCHIVE" > "$ARCHIVE.sha256"
sha256sum -c "$ARCHIVE.sha256"

# Review the namespace mapping without writing anything.
mongorestore --uri "$STAGING_MONGO_URI" \
  --gzip --archive="$ARCHIVE" \
  --nsInclude="$STAGING_DB.*" \
  --nsFrom="$STAGING_DB.*" --nsTo="$RESTORE_DB.*" --dryRun

# Only after verifying RESTORE_DB does not exist and is staging-only:
mongorestore --uri "$STAGING_MONGO_URI" \
  --gzip --archive="$ARCHIVE" \
  --nsInclude="$STAGING_DB.*" \
  --nsFrom="$STAGING_DB.*" --nsTo="$RESTORE_DB.*"
```

The example intentionally omits `--drop`. Never run it with a production
MongoDB URI, and never restore to the source database. The database tools
report successful/failed records; also independently compare the restored
collection document counts, index definitions, selected media IDs,
metadata, date fields, and unique constraints. A live dump without a
quiesced write window or supported oplog technique might not represent
one consistent point in time, so the recovery claim must be qualified.

## Redis backup and restoration drill

The staging Redis mounts a separate named volume and loads the existing
`redis.conf`, which currently enables both RDB snapshots and AOF.
Redis documentation states that **AOF takes precedence** when both
persistence methods exist during startup. Do not simply copy an RDB into
a container that still has an old AOF and assume it will be used.

- Use isolated staging Redis only. Confirm `INFO persistence`,
  `aof_last_write_status`, `rdb_last_bgsave_status` and recorded key counts.
- Capture a Redis snapshot on staging (`BGSAVE` / persisted RDB), then
  copy the immutable completed RDB to a protected backup location.
- Test startup from the RDB in a **fresh, disposable container** with AOF
  disabled and no existing AOF data. Never overwrite your running Redis
  volume to simulate restoration.
- Verify active session and rate-limit keys have their expected TTLs,
  search generation is present or safely reinitialized, user cache keys
  deserialize safely, and no expired sessions are resurrected.
- For PH-003 opt-in protected state, separately back up/restore its AOF
  and verify the entire operational state can survive a restart. Redis
  RDB and AOF have different recovery point and durability tradeoffs.

Reference: [Redis persistence and backup](https://redis.io/docs/latest/management/persistence/).

### CI recovery fixtures vs real backups

`tests/test_disposable_recovery_fixtures.py` checks BSON record and index
reconstruction in **two UUID-named disposable local MongoDB databases**, and
Redis `DUMP`/`RESTORE` of **one UUID-scoped test session** with TTL preservation
on the ephemeral CI Redis service. The test creates/drops only its own
disposable MongoDB databases and deletes only its own Redis keys.

**These tests are not equivalent to** an Atlas cloud snapshot restore,
`mongodump`/`mongorestore` full backup, production Redis RDB/AOF replay,
a network partition, a VPS loss, or a full Telegram end-to-end smoke test.

## Recovery test matrix (staging only)

| Scenario | Evidence required |
|---|---|
| Atlas snapshot restore into new cluster | Counts, media IDs, index inventory, actual duration |
| Redis cache volume loss | Search cache miss then rebuild, sessions behavior |
| Redis operational state restart | Sessions, TTLs, rate limits and search generation |
| MongoDB outage | Temporary search error, no false zero caches, recovery |
| Bot container/image rollback | Previous image starts with no schema downgrade |
| New media indexing | File returned, search/page invalidation, no duplicate |
| Staging Telegram bot restart | Search, callbacks, subscriptions, batches and delivery |
| Deleted/corrupted Redis generation key | New random generation, no stale cached pages |
| Wrong/expired Redis ACL credential | Denied startup, no fail-open state fallback |

Record each test result in `docs/RECOVERY_EVIDENCE_TEMPLATE.md`. Determine
realistic RPO/RTO **from measurements**, not ungrounded estimates. Keep
restore artifacts outside GitHub and Docker build contexts, encrypt them,
restrict access and test deletion/retention.

## Production release gate

Before deploying PR #4:

- [ ] Final CI jobs green for the reviewed commit
- [ ] Offline staging identity preflight, project/config checker and Docker build pass
- [ ] Distinct Telegram token, channels, MongoDB server, Redis networks and volumes confirmed
- [ ] Staging Telegram smoke tests and database outage/recovery drills complete
- [ ] One **actual** Atlas/cloud or mongodump restore into an isolated target completed
- [ ] One **actual** Redis RDB/AOF restore into an isolated instance completed
- [ ] Backup integrity checks and measured RPO/RTO recorded
- [ ] Old production image digest/restart commands and rollback triggers recorded
- [ ] GitHub required checks enforcement and explicit operator release approval
- [ ] No secrets, database dumps, Telegram sessions or backup artifacts committed

**PH-012 must remain In review until real operator-run restoration evidence exists.**
