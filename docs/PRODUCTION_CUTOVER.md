# Production cutover with an empty Redis start

Decision recorded 2026-10-29: the operator accepts up to 24 hours of downtime,
stopping the whole bot and recreating Redis empty while retaining production
MongoDB. The current workspace/server is QA, not production. The initial
decision used one MongoDB; the operator subsequently reported adding one
secondary. Verify the actual topology when using this runbook. No production
server was accessed or changed from QA.

## Readiness and recommended scope

The branch is a release candidate for a controlled single-MongoDB rollout.
The latest bounded QA passed 1,163 tests and 18 real-account multiple-channel
and invite checks on wzgram 3.1.6. Whole-tree source-matched coverage is 70.37%
lines / 57.32% branches. Sustained production load, cloud
restore and production-specific configuration/index checks remain release
gates; 100% coverage is not the sole definition of production readiness.
See [the QA evidence](qa/coverage-expansion/STATUS.md).

Recommended initial scope:

- Retain the current production MongoDB and existing enabled user features.
- Start fresh, separate cache and protected-state Redis instances.
- Keep multi-database ownership and new durable/metadata write modes disabled
  for this first cutover.
- Keep indexed search off until production storage headroom is measured: its
  token fields and two optional indexes consume additional quota. With sufficient
  headroom, validate backfill/plans during maintenance before enabling it.
- Release a validated application image and dependency set, retaining an archive
  outside Docker for rollback. The earlier QA image is no longer on this QA
  host. The earlier `file-filter-bot:cutover-candidate-v2-20261029` passed 776 tests. Its
  [identity and checks](qa/coverage-expansion/cutover-candidate-checks.json) and
  archive checksum are recorded. A build against unpinned requirements may
  resolve different dependencies and needs new QA.

The latest QA build is `file-filter-bot:qa-multisub-20261030`, image
`8ea67dde9ec1`, application source `b2fcb38`. It was rebuilt after the earlier
local image disappeared, and its complete suite and live checks passed on
wzgram 3.1.6. Historical candidate checks/archive identify their original
source and dependencies; they do not certify this newer application. See the
[current round evidence](qa/coverage-expansion/round8-multisub.json).

For the exact two-service stack supplied by the operator, use the
[production command sequence](PRODUCTION_FROM_EXISTING_COMPOSE.md), including
private Atlas credentials, native build and rollback commands.

## Before stopping production

1. Identify the actual bot deployment, all replicas/indexers, its MongoDB
   URI/name, Redis instances and volume mounts. Privately verify the production
   bot identity, admins and channel/group IDs. QA credentials/destinations and
   copied databases must not replace production configuration. The QA workspace
   Compose project is not a verified production deployment target.
2. Preserve the current image, production configuration, Telegram bot session
   files and application data volumes as a rollback set. Record image IDs,
   settings, media/user counts and channel history boundaries without exposing
   credentials. Check disk/RAM and MongoDB index-creation permissions.
3. Review production `bot_settings`. Existing stored keys override environment
   initialization for the settings managed there. Clearing Redis does not reset
   them. Retain valid existing business settings and user-feature choices;
   explicitly review new flags rather than importing the QA settings collection.
4. Stop every old bot, indexer and other application writer. Let active work
   finish where practical; record unfinished work and per-channel message IDs
   for a bounded indexing catch-up after downtime. Do not rely on Redis clearing
   or Telegram reconnection to reconstruct missed work.
5. Take a consistent production MongoDB backup after writes stop. Restore it
   into a separate isolated database and verify important records/counts and
   legacy reads. Preserve the backup independently of the containers being
   replaced. Check the actual cloud restore procedure before changing data.

## MongoDB changes

Force-subscription changes need no manual MongoDB migration. Existing single
`AUTH_CHANNEL` values remain readable; missing invite settings seed defaults
of 15 minutes and one member. `/bsetting` now accepts multiple channels/groups
and validates bot administrator/Invite Users rights before saving interactive
target edits. Restart to apply settings. Existing issued links retain their
original expiry; changing settings does not revoke them. Review all required
targets and bot permissions before enabling ordinary-user access. If rolling
back to code that only supports one channel, first save a compatible scalar
channel configuration for that version. See the [configuration guide](../README.md#channels-groups-and-authorization).

### Single database, indexed search off

No bulk media/user rewrite or reindex of all Telegram files is required.
Keep existing media identities, users, premium records, quota dates/counters,
channels, filters, batch links and feature records.

Startup initializes missing settings and creates missing declared indexes. It
does not drop or rename conflicting indexes. Index failures can be logged while
startup continues, so a healthy HTTP response alone does not approve indexes.
Run the read-only media index audit and resolve incompatible definitions or
uniqueness conflicts explicitly before opening traffic. Do not delete records
or drop indexes as an automatic deployment step.

Ensure the production primary does not have an activated `media_owner_control`
binding before selecting single-source mode. The QA copies were activated;
that does not imply production was activated. Never copy their ownership
collections into production.

With production values supplied privately in the process environment:

```sh
python -m scripts.audit_media_indexes --allow-remote --include-index-stats
```

The operator tools read exported environment variables; merely having a host
`.env` file is not a guarantee they received it. Run them in the reviewed image
with explicitly selected production secrets. No credentials belong in shell
history or command arguments.

### Optional indexed-search enablement

While all old writers remain stopped:

```sh
python -m scripts.backfill_search_tokens --allow-remote --limit 1000000
python -m scripts.backfill_search_tokens --allow-remote --limit 1000000 --apply
python -m scripts.backfill_search_tokens --allow-remote --limit 1000000
```

Require the final inventory to report `needs_update=0` and `truncated=false`.
If the bound is exceeded, keep the feature off and plan a complete bounded
migration rather than treating a partial scan as complete.

This adds `_search_terms_v1` and `_search_terms_version` to media records.
It does not change file IDs, filenames, user records or original media fields.
Set `FEATURE_INDEXED_MEDIA_SEARCH=true` in the effective production setting:
update its existing `bot_settings` record if present, and align the environment.
Restart the new bot and verify both optional indexes were successfully created:

- `media_search_terms_v1`
- `media_stable_page_v1`

Compare complete result identities/counts and shallow/deep plans before opening
traffic. Existing media need token backfill for the full performance benefit;
new indexed files receive tokens while the feature is enabled. See
[indexed-search operation and rollback](INDEXED_MEDIA_SEARCH.md).

The legacy `migrate_media_metadata.py` is not needed for this release and is not
a canonical width/height/quality backfill. Keep canonical metadata persistence
off unless its separate compatibility/rollback work is deliberately selected.

### Adding the second database later

An initial single-source deployment does not create ownership bindings. The
later move from one source to two is supported through explicit stopped-writer
activation; it does not require activating a one-source registry now.

1. Provision a second deployment with actual additional capacity. A second
   database name inside a cluster does not expand that cluster's storage quota.
2. Keep enough headroom on the original primary for its application data,
   indexes and the new ownership registry, which holds claims for both sources.
   Switching new media to source 2 does not move existing media or stop growth
   of the primary registry. If the primary is already near its hard limit,
   increase capacity or plan a separate data migration before activation.
3. Preserve the original primary URI/name and ordering. It remains both the
   application's main database and ownership coordinator. Simply putting an
   empty new database first would also point users/settings/channels and other
   primary repositories at that empty database.
4. Schedule another maintenance window, back up both sources, and follow the
   inventory/activation procedure below. Configure the two URI/name pairs and
   stage the saved registry toggle through `/bsetting` with indexing paused.
   Stop all writers and complete activation before restarting with it enabled.
   Existing saved settings override `.env`; confirm the effective flag, not just
   the environment line.
5. Validate old and new media delivery, owner routing, storage measurements and
   automatic write-source switching before reopening indexing.

The write-source soft limit uses MongoDB document plus index bytes. It is not a
reservation of provider capacity or a measurement of all databases in a shared
cluster. Its legacy `DATABASE_SIZE_LIMIT_GB` value uses bytes divided by 1024
cubed (GiB). Allow a margin for concurrent growth and coordinator writes, and monitor
provider-reported usage. No new cluster is provisioned automatically. Once the
two-source topology is activated, adding a third changes its binding and needs a
separate offline membership migration; no automatic membership-change tool is
implemented.

### Optional multi-database enablement

Single-source production must keep `DATABASE_GLOBAL_OWNER_REGISTRY=false` and
omit additional URI/name pairs. Do not run ownership activation on one source.

To enable multiple databases, configure and back up the complete intended
topology first, including the permanent coordinator. Stop every writer, run the
read-only inventory, resolve all alias/canonical/index conflicts, then apply the
bounded ownership activation and verify status. Privately retain the activation
token for interrupted-run recovery. Only then start the new bot with the full
topology and `DATABASE_GLOBAL_OWNER_REGISTRY=true`.

Activation creates `media_owner_control` bindings on every source and the
`media_owner_registry` with its alias uniqueness index on the coordinator. Each
source needs compatible canonical uniqueness. Existing media stays on its
original source; there is no automatic redistribution or deduplication. Budget
coordinator space for permanent identity claims across every source.

After activation, flags alone cannot return production to a single database or
an older uncoordinated writer. Membership changes and old-image rollback require
an offline migration. Follow the complete
[ownership runbook](MULTIDB_GLOBAL_IDENTITY.md).

## Fresh Redis and bot configuration

The accepted reset removes the need to run `migrate_redis_state.py`. Preserve
any desired audit copy, then use empty storage for both new Redis services.
Container recreation with the old data volume can reload the old AOF/RDB.
Identify and replace only the intended Redis storage. A blanket Compose
`down -v` can also remove application/session/backup volumes in that project.

### Scope of the proposed cleanup commands

| Command | What it removes | Deployment consequence |
|---|---|---|
| `sudo docker compose down -v` | Containers/networks for that Compose project, declared non-external named volumes and attached anonymous volumes | In this repo that includes `bot-data`, `bot-logs` and `bot-backups`, in addition to Redis data. |
| `sudo docker system prune -a -f --volumes` | Host-wide stopped containers, unused networks/images/build cache and unused anonymous volumes | It can remove the old rollback image and unrelated unused resources. It is not needed for a Redis reset. |

Neither command sends a drop operation to an external MongoDB. If MongoDB is
containerized, its local storage can be at risk depending on which project and
volumes are removed. Host bind-mounted `.env` files are not named volumes, but
configuration, session files and backups still need an independent rollback copy.

Recommended procedure: stop the verified bot project with `down` **without**
`-v`, remove only its identified Redis volumes, then start the reviewed release
with empty Redis storage. Preserve application volumes and skip the host-wide
prune. If deliberately discarding every project volume instead, first verify
that all their contents are disposable and save the required backups outside
those volumes. Do not prune the only copy of the release or rollback image.

### Bot and Redis settings

The default configs require readable non-secret Redis configuration files:

```sh
chmod 0644 redis.conf redis-state.conf
```

A separate-container network regression now verifies the default state Redis
connection; its earlier loopback-only denial was BUG-059. Neither Redis service
publishes a host port. Use the ACL overlay if authentication is required.

For this repository's reviewed Compose topology:

```dotenv
REDIS_URI=redis://redis:6379/0
REDIS_STATE_URI=redis://redis-state:6379/0
AUTO_UPDATE=false
UPDATE_ON_START=false
DATABASE_GLOBAL_OWNER_REGISTRY=false
FEATURE_CANONICAL_MEDIA_METADATA=false
FEATURE_QUOTA_DELIVERY_LEDGER=false
PROCESSING_DURABLE_INDEXING=false
PROCESSING_DURABLE_SAVED_SEARCH_ALERTS=false
```

Use deployment-specific service addresses/authentication when the actual stack
differs. Start the `protected-state` Compose profile if using this topology.
The two Redis roles must be separate instances: cache uses `allkeys-lru`, state
uses `noeviction` and AOF. Separate database numbers on one instance do not
provide eviction isolation. Size both from measured use and available RAM;
monitor protected-state write rejection/OOM and persistence failures. Bring both
Redis instances up healthy before starting the bot.

The reset invalidates old search/subscription/edit/deep-link sessions, pending
confirmations, operational Redis flags and rate-limit counters. Users may need
to search/reopen links and repeat checks. MongoDB-backed users, premium status,
daily quota counters, favorites and other persisted records remain. A Redis wipe
does not reset MongoDB quotas. Daily quota boundaries follow 00:00 UTC. Cancel/review old broadcast and delete confirmations
rather than expecting them to resume. Keep only one application version active.

### Using the validated application image

The QA release package is outside Docker at
`/home/ubuntu/qa-workspace/release-artifacts/`, with the compressed image,
checksum, manifest and `compose.release.yml`. Transfer it to a protected release
directory on production and verify the checksum before loading. Preserve the
old production image/configuration separately; the candidate is not its rollback
backup.

The release override selects the validated application image and prevents an
implicit image pull:

```yaml
services:
  file-filter-bot:
    image: file-filter-bot:cutover-candidate-v2-20261029
    pull_policy: never
```

Load it with `sudo docker image load --input file-filter-bot-cutover-v2-20261029.tar.gz`
from the directory holding the transferred archive. Use the updated, reviewed
production checkout and its non-secret Redis configs; Compose bind mounts those
configs from the host. Include the release override when starting services and
use `--no-build` to avoid rebuilding against floating dependencies. For example,
from that checkout, replacing `/secure/releases` with the actual release path:

```sh
sudo docker compose -f docker-compose.yml -f /secure/releases/compose.release.yml --profile protected-state up -d --no-build --wait --wait-timeout 120 redis redis-state
sudo docker compose -f docker-compose.yml -f /secure/releases/compose.release.yml --profile protected-state up -d --no-build file-filter-bot
```

Apply the production environment settings above before starting. These examples
assume the repository's base Compose deployment; adapt the reviewed file/project
selection to the actual deployment and include the ACL overlay if selected.


## Before reopening traffic

1. Confirm the intended production bot, MongoDB and both Redis connections;
   verify effective database-backed settings and index audit results.
2. Check `/health`, `/ready`, logs and `/verify`. A 100/100 handler score does
   not replace the functional checks or prove production data compatibility.
3. With controlled admin/normal accounts, verify an old permanent file link,
   search, next/back/deep page, one delivery, Send All, subscription enforcement,
   banned/premium/quota access and existing enabled features. Configured bot
   admins and the explicit owner retain their bypass; test ordinary-user bans
   separately, including with premium disabled, then unban and verify recovery.
4. Verify one controlled new-file ingestion, duplicate behavior and the bounded
   channel-history catch-up. Do not broadcast tests to production users.
5. Observe MongoDB latency, index errors, RAM, Redis evictions/state OOM and
   queue/backlog progress. Reopen gradually only with agreed acceptable results.

## Rollback

Stop all new writers first. For the initial single-source release with new
incompatible persistence modes kept off, retain the old image/configuration and
start Redis empty again if reverting routing. If search-token backfill was
applied, remove its two metadata fields with the bounded rollback tool and
verify completion before using an older reader that cannot ignore them. Additive
optional indexes may remain. Do not restore a pre-cutover MongoDB snapshot after
accepting new writes without accounting for the intervening data.

If registry, canonical metadata or durable modes were enabled, follow their
specific rollback runbooks and reconcile pending work. Accepted downtime and
Redis clearing do not make those MongoDB compatibility changes disappear.

## References

- [Docker Compose volume removal](https://docs.docker.com/reference/cli/docker/compose/down/)
- [Docker system prune scope](https://docs.docker.com/reference/cli/docker/system/prune/)
- [MongoDB Atlas storage usage and limits](https://www.mongodb.com/docs/atlas/reference/faq/storage/)
- [Redis persistence and reload behavior](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/)
- [MongoDB backup and isolated restore verification](https://www.mongodb.com/docs/manual/tutorial/backup-and-restore-tools/)
