# Deploy the hardening branch from the existing production Compose stack

This procedure is for the production server identified by the operator, not the
QA workspace. It uses the supplied `file-filter-bot` / `file-filter-redis`
containers, the existing Compose project, and the external Atlas Free database.
No production command in this document was executed from QA.

Target branch: `docs/production-hardening-source-of-truth-20261028`.
The branch must include startup fix `850bc31`. Local acceptance: 776 tests
passed; offline Docker setup passed. No MongoDB ownership activation, token
backfill, canonical metadata migration or global Docker prune is part of this
cutover. The older candidate image predating BUG-061 is superseded.

Run blocks in order, in the same Bash/SSH session on production. Stop at any
error. Keep the backup directory private: it contains credentials and user data.
Do not paste its contents into a chat.

## 1. Snapshot the deployment, then stop the bot

This also works if the bot was already stopped using the earlier instruction.
Inspection does not require a running container.

```bash
cd ~/Advanced-File-Filter-Bot
set -euo pipefail
umask 077

prod_branch=docs/production-hardening-source-of-truth-20261028
prod_backup="$(dirname "$PWD")/bot-cutover-backup-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 700 "$prod_backup"
cp -p .env docker-compose.yml redis.conf "$prod_backup/"
git rev-parse HEAD > "$prod_backup/git-before"

sudo docker inspect file-filter-bot > "$prod_backup/container-before.json"
sudo docker inspect file-filter-redis > "$prod_backup/redis-before.json"
sudo docker logs --tail 300 file-filter-bot > "$prod_backup/bot-before.log" 2>&1

prod_project=$(sudo docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' file-filter-bot)
prod_old_image=$(sudo docker inspect --format '{{.Image}}' file-filter-bot)
prod_old_image_name=$(sudo docker inspect --format '{{.Config.Image}}' file-filter-bot)
prod_redis_volume=$(sudo docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{if eq .Type "volume"}}{{.Name}}{{end}}{{end}}{{end}}' file-filter-redis)
test -n "$prod_project"
test "$prod_project" != '<no value>'
test -n "$prod_redis_volume"
test "$(sudo docker volume inspect --format '{{index .Labels "com.docker.compose.project"}}' "$prod_redis_volume")" = "$prod_project"
test "$(sudo docker volume inspect --format '{{index .Labels "com.docker.compose.volume"}}' "$prod_redis_volume")" = redis-data

printf '%s\n' "$prod_project" > "$prod_backup/project"
printf '%s\n' "$prod_old_image" > "$prod_backup/old-image-id"
printf '%s\n' "$prod_old_image_name" > "$prod_backup/old-image-name"
printf '%s\n' "$prod_redis_volume" > "$prod_backup/redis-volume"
sudo docker image save "$prod_old_image" | gzip -1 > "$prod_backup/old-image.tar.gz"

sudo docker compose -p "$prod_project" stop -t 60 file-filter-bot
sudo docker cp file-filter-bot:/usr/src/app - | gzip -1 > "$prod_backup/old-app.tar.gz"
printf 'Backup directory: %s\n' "$prod_backup"
```

The stopped container is retained until replacement. The app archive includes
the usual working-directory session files and mounted application directories.
If the configured bot session lives elsewhere, preserve that location too before
removing the container. Keep the same production bot token/API credentials.
Record the downtime interval for channel-history catch-up after deployment.

## 2. Back up Atlas while writers are stopped

Keep all other writers to this database stopped too. The following reads the
current container's effective credentials from the private snapshot, without
putting the URI in command arguments. It fails rather than guessing a missing
database name. MongoDB Tools accepts JSON as YAML configuration.

```bash
python3 - "$prod_backup" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
snapshot = json.loads((root / 'container-before.json').read_text())[0]
values = dict(item.split('=', 1) for item in snapshot['Config']['Env'] if '=' in item)
if not values.get('DATABASE_URI') or not values.get('DATABASE_NAME'):
    raise SystemExit('Stop: confirm the existing DATABASE_URI and DATABASE_NAME; do not guess.')
(root / 'mongodump.yml').write_text(json.dumps({'uri': values['DATABASE_URI']}))
(root / 'database-name').write_text(values['DATABASE_NAME'])
for name in ('mongodump.yml', 'database-name'):
    (root / name).chmod(0o600)
PY
prod_database=$(cat "$prod_backup/database-name")
sudo docker run --rm --user "$(id -u):$(id -g)" --memory 512m --cpus 1 \
  -v "$prod_backup:/backup" mongo:7 mongodump \
  --config=/backup/mongodump.yml --db "$prod_database" \
  --archive=/backup/atlas.archive.gz --gzip
test -s "$prod_backup/atlas.archive.gz"
sudo chown "$(id -u):$(id -g)" "$prod_backup/atlas.archive.gz"
sudo chmod 600 "$prod_backup/atlas.archive.gz"
```

Atlas Free does not support `mongodump --oplog` or `mongorestore --oplogReplay`.
Verify the dump before proceeding; never restore a validation dump over Atlas.
The example below needs RAM/disk for a temporary MongoDB and can instead be run
on a separate approved restore-test host. It uses no network interfaces or host
ports, mounts the backup read-only, restores to container-local loopback and
removes only its own container/anonymous volumes on exit:

```bash
prod_verify_restore() (
  set -euo pipefail
  prod_verify_id=
  trap 'if test -n "$prod_verify_id"; then sudo docker rm -f -v "$prod_verify_id" >/dev/null 2>&1 || true; fi' EXIT
  prod_verify_id=$(sudo docker run -d --network none --memory 1g --cpus 1 \
    -v "$prod_backup:/backup:ro" mongo:8 --wiredTigerCacheSizeGB 0.25)
  prod_verify_ready=false
  for prod_attempt in $(seq 1 60); do
    if sudo docker exec "$prod_verify_id" mongosh --quiet \
      --eval 'quit(db.adminCommand({ping:1}).ok ? 0 : 1)' >/dev/null 2>&1; then
      prod_verify_ready=true
      break
    fi
    sleep 1
  done
  test "$prod_verify_ready" = true
  sudo docker exec --user "$(id -u):$(id -g)" --workdir /tmp "$prod_verify_id" \
    mongorestore --host 127.0.0.1 --archive=/backup/atlas.archive.gz --gzip --stopOnError
  sudo docker exec -e QA_RESTORE_DB="$prod_database" "$prod_verify_id" mongosh --quiet \
    --eval 'const d=db.getSiblingDB(process.env.QA_RESTORE_DB); printjson(d.getCollectionNames().map(n=>({collection:n,count:d.getCollection(n).countDocuments({})})))'
)
prod_verify_restore
```

Compare the restored important collection counts with the stopped-source backup
log/known production counts. A successful dump or nonempty file alone is not a
restore rehearsal. If this phase cannot finish, the original container can be
resumed with `sudo docker start file-filter-bot`.

## 3. Fetch and select the new branch

```bash
test -z "$(git status --porcelain --untracked-files=no)"
git fetch origin "$prod_branch"
if git show-ref --verify --quiet "refs/heads/$prod_branch"; then
  git switch "$prod_branch"
else
  git switch --track -c "$prod_branch" "origin/$prod_branch"
fi
git merge --ff-only "origin/$prod_branch"
git merge-base --is-ancestor 850bc31 HEAD
git log -1 --oneline
```

Do not use `git reset --hard` or `git clean` to get past a failure. The existing
`.env` is retained. The new branch updates Compose with the second, optional
Redis service and its private network.

## 4. Set the initial production configuration

Edit `.env` with `nano .env`. Preserve the production Atlas URI/name, bot token,
API credentials, admins and real channels/groups. Set these keys once, removing
any duplicate active definitions:

```dotenv
DATABASE_URIS=
DATABASE_NAMES=
DATABASE_GLOBAL_OWNER_REGISTRY=false
REDIS_STATE_URI=redis://redis-state:6379/0
AUTO_UPDATE=false
UPDATE_ON_START=false
UPDATE_BRANCH=docs/production-hardening-source-of-truth-20261028
FEATURE_INDEXED_MEDIA_SEARCH=false
FEATURE_CANONICAL_MEDIA_METADATA=false
FEATURE_QUOTA_DELIVERY_LEDGER=false
PROCESSING_DURABLE_INDEXING=false
PROCESSING_DURABLE_SAVED_SEARCH_ALERTS=false
```

The primary `DATABASE_URI` / `DATABASE_NAME` remain unchanged. Keep existing
user-feature and premium/access choices. Existing managed `bot_settings` records
override environment initialization: confirm `FEATURE_INDEXED_MEDIA_SEARCH` is
off in that collection too if its record already exists. Redis clearing does
not reset database settings, users, premium status or daily quota counters.
Daily quota rollover in this version is 00:00 UTC.

Do not enable token backfill/new optional indexes while the Free cluster is
nearing its limit. The initial release needs no bulk media rewrite; startup can
initialize missing settings and declared indexes, so inspect index errors and
Atlas storage before admitting traffic.

```bash
chmod 600 .env
chmod 644 redis.conf redis-state.conf
sudo docker compose -p "$prod_project" --profile protected-state config --quiet
sudo docker compose -p "$prod_project" --profile protected-state build file-filter-bot

# Setup must not install packages or need package-index access.
sudo docker compose -p "$prod_project" --profile protected-state run --rm --no-deps \
  --entrypoint bash file-filter-bot start.sh --setup
sudo docker compose -p "$prod_project" --profile protected-state run --rm --no-deps \
  --entrypoint python file-filter-bot -m pip check
sudo docker compose -p "$prod_project" --profile protected-state run --rm --no-deps \
  --entrypoint python file-filter-bot -c \
  'import importlib.metadata as m; print({p:m.version(p) for p in ("wzgram","motor","pymongo","redis","aiohttp")})'
```

The validated runtime used wzgram 3.1.5, Motor 3.7.1, PyMongo 4.19.0, Redis
client 8.1.0 and aiohttp 3.14.5. A fresh native build may resolve newer packages;
if these differ, validate that build before starting it. The QA image archive is
another option only when its platform matches the production architecture.

## 5. Reset only Redis and start the new version

This preserves `bot-data`, `bot-logs`, `bot-backups` and Atlas. The previous bot
is stopped, and the Redis volume was identified and checked in phase 1.

```bash
sudo docker compose -p "$prod_project" --profile protected-state down
sudo docker volume rm "$prod_redis_volume"
sudo docker compose -p "$prod_project" --profile protected-state up -d --no-build \
  --wait --wait-timeout 120 redis redis-state
sudo docker compose -p "$prod_project" --profile protected-state up -d --no-build \
  --wait --wait-timeout 180 file-filter-bot
sudo docker compose -p "$prod_project" --profile protected-state ps
sudo docker compose -p "$prod_project" --profile protected-state exec -T file-filter-bot \
  sh -c 'curl -fsS "http://127.0.0.1:${PORT:-8000}/health"; printf "\n"; curl -fsS "http://127.0.0.1:${PORT:-8000}/ready"; printf "\n"'
```

On the supplied old stack no protected-state Redis volume exists yet, so the new
one starts empty. If an earlier attempted deployment created it, inspect that
volume before deciding to reset it too; do not guess its name or globally prune.
Never append `-v` to `down` in this procedure. Review the new bot's logs locally
for index failures even if health is green.

Smoke-test `/start`, `/verify`, an existing file link, search, next/back, a file
delivery, Send All, subscription and premium/quota checks with controlled
accounts. Catch up channel indexing over the downtime interval. Old Redis-backed
menus/sessions expire and users may need to search/reopen links again.

After BUG-062, the bot's container `/restart` command reloads the deployed image
through graceful process shutdown and the existing `unless-stopped` policy. It
does not fetch/reset Git or switch branches. Deploy new source with a host-side
Git checkout and Docker rebuild/recreation. `sudo docker compose --profile
protected-state restart file-filter-bot` also reloads database-backed settings;
use recreation when changing the container environment.

## Rollback

Before phase 5 removes the old container, `sudo docker start file-filter-bot`
resumes that preserved container. If it was already replaced:

```bash
sudo docker compose -p "$prod_project" --profile protected-state stop -t 60 file-filter-bot
sudo docker compose -p "$prod_project" --profile protected-state down
sudo docker volume rm "$prod_redis_volume"
sudo docker image load --input "$prod_backup/old-image.tar.gz"
sudo docker image tag "$prod_old_image" "$prod_old_image_name"
git switch --detach "$(cat "$prod_backup/git-before")"
cp -p "$prod_backup/.env" .env
cp -p "$prod_backup/docker-compose.yml" docker-compose.yml
cp -p "$prod_backup/redis.conf" redis.conf
sudo docker compose -p "$prod_project" up -d --no-build
```

The unused protected-state volume is retained; its container is stopped/removed
by the new Compose teardown. Do not restore the old Atlas dump after accepting
new writes without reconciling them.
Keep optional incompatible persistence modes off for this initial rollback
strategy. The general [cutover plan](PRODUCTION_CUTOVER.md) covers later
two-source activation and its different rollback requirements.

References: [Compose up/wait](https://docs.docker.com/reference/cli/docker/compose/up/),
[Compose volume preservation](https://docs.docker.com/reference/cli/docker/compose/down/),
[mongodump configuration](https://www.mongodb.com/docs/database-tools/mongodump/),
[Atlas Free restrictions](https://www.mongodb.com/docs/atlas/reference/free-shared-limitations/).
