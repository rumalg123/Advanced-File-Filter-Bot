# PH-010: Optional authenticated Redis, network boundaries and release runbook

**Status: opt-in code and staging tests only. Not deployed, no live Redis changes.**
This phase improves Redis authentication for operators who choose to enable it.
The existing Redis connection remains unchanged by default.

## Why

Redis is meant to be accessed only by trusted clients on a restricted network.
The base Compose file currently does not publish 6379, which is good; however,
the main Redis binds 0.0.0.0 *inside its Docker network* and has no password.
Docker network isolation is useful but is not an independent authentication
boundary against compromised peers on that same network.

Redis ACL named users are preferred over legacy requirepass. For the optional
Compose overlay we use named user `filebot` with authentication and restrict
the Redis command set: `+@all -@dangerous`. This is defense in depth, not a
claim of strict least privilege for every endpoint. Revisit ACL commands if the
bot grows new Redis operations. Direct Internet exposure is not allowed.

References:
- [Redis security](https://redis.io/docs/latest/operate/oss_and_stack/management/security/)
- [Docker Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/)
- [Redis ACL guide](https://redis.io/docs/latest/operate/oss_and_stack/management/security/acl/)

## Changes in this PR

- `core/cache/auth.py` supports explicit, absolute `REDIS_PASSWORD_FILE` and
  `REDIS_STATE_PASSWORD_FILE`, and optional named ACL usernames.
- `CacheManager` connects using those **file-backed** credentials. The existing
  Redis URI remains valid when no file path is configured. Mixed URI-embedded
  and file credentials are rejected instead of choosing one unpredictably.
- Protected Redis can have **different** ACL credentials from disposable Redis.
  Existing data, Redis keys, TTLs and cache serialization are untouched.
- `scripts/migrate_redis_state.py` and `scripts/audit_redis_serialization.py`
  accept the same file-backed credentials for manual operations. State
  migration may require a separately authorized credential for `DUMP` /
  `RESTORE` if the app ACL denies those commands.
- `scripts/generate_redis_acl.py` explicitly creates four non-overwriting,
  independent secret files in a private `.secrets/` directory. Never commit
  its output; `.secrets/` is now ignored by Git.
- `docker-compose.redis-auth.yml` is an **optional** overlay with Compose
  secrets mounted only to the services that need them. It does not add
  Redis host port publishing. The bot never receives the server ACL files,
  and the Redis server never receives the bot's unrelated credentials.
- Authenticated-mode health checks treat unauthenticated Redis's `NOAUTH`
  response as evidence the server is alive with authentication enabled.
  The application still proves its actual credentials by connecting at startup.
- CI tests: file loading, malformed credentials, unique ACL generation,
  non-overwrite behavior, default compatibility, Compose overlay validation,
  and an ephemeral Redis server verifying NOAUTH / authenticated operations.

## Defaults remain unchanged

| Setting | Default | Purpose |
|---|---|---|
| `REDIS_URI` | Existing Redis URI | Primary cache connection |
| `REDIS_USERNAME` | Empty | Optional ACL username |
| `REDIS_PASSWORD_FILE` | Empty | Absolute path to optional password secret |
| `REDIS_STATE_URI` | Empty | PH-003 dedicated Redis; opt-in |
| `REDIS_STATE_USERNAME` | Empty | Separate optional state ACL username |
| `REDIS_STATE_PASSWORD_FILE` | Empty | Separate optional state password secret |

**Neither ACL file nor new credentials are automatically enabled.** Enabling
the overlay changes Redis authentication, requiring coordinated client/server
restart and tests. This is NOT safe to enable by changing a single env variable
against existing unauthenticated production Redis.

## Staging enablement (never run directly against production without approval)

1. Take a verified Redis AOF/RDB backup and record active session and limiter
   key counts. Confirm that staging is using its own Redis volumes and tokens.
2. Generate credentials **on the staging host only**, not in the repository
   checkout destined for a public artifact:

   ```bash
   python scripts/generate_redis_acl.py
   ```

   The generator prints only file names, not passwords. It refuses to
   overwrite any existing secrets. Keep the directory under 0700 permissions,
   back it up through your approved secret-management system, and rotate via
   a staged replacement process, not by editing passwords on a live container.

3. Validate Compose config with no deployment:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.redis-auth.yml \
     --profile protected-state config --quiet
   ```

4. **Stop all bot writers during the ACL activation window.** Apply the
   overlay only to an isolated staging Redis deployment:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.redis-auth.yml \
     --profile protected-state up -d redis redis-state
   docker compose -f docker-compose.yml -f docker-compose.redis-auth.yml \
     --profile protected-state up -d file-filter-bot
   ```

   If you have **not enabled PH-003**, omit `--profile protected-state` and do
   not set `REDIS_STATE_URI`. The state credentials may be prepared but not
   used. No MongoDB modification is required.

5. Verify with bot smoke tests: startup AUTH, search, file delivery, pagination,
   session reads and writes, TTLs, rate limits, subscription callbacks,
   monitoring, and safe Redis outage/fail-closed behavior.

6. Verify the Redis ports are **not published on the host**; validate Docker
   network membership/firewall rules and ensure no untrusted containers share
   the relevant bridge. A container bind address of `0.0.0.0` is not itself
   host publication; external reachability depends on network/NAT/ports.

7. For a non-Compose external Redis, enforce private network/firewall,
   authentication and TLS `rediss://` where traffic crosses an untrusted
   boundary. This PR does not generate TLS certificates or automatically
   enable TLS.

### Rollback

Do not change auth on the live server while old clients continue writing.
If staging fails, stop all bot instances, inspect Redis logs *without* dumping
credentials, restore the prior server/Compose configuration and client env
together, and verify sessions, TTLs and key generation after restart.
Redis ACL changes do not rewrite values, so no mass data migration is needed.

Disable the overlay only in a controlled, reviewed rollback. Removing ACL
authentication weakens security and must not be an automatic fallback when
authentication fails. Prefer fixing credentials/reachability instead.

## Acceptance criteria

- [x] No credential source enabled by default; existing deployments retain
  original unauthenticated Redis connection unless operator chooses ACL
- [x] Password files parsed without exposing secrets in application logs
- [x] Distinct cache/state credentials; no passwords/ACL files committed
- [x] Optional Docker Compose secret mounts; no Redis ports published
- [x] Unit tests and real authenticated-Redis smoke test added in CI
- [x] **Full CI passed** on [run 40800650194](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40800650194): pytest/MongoDB/dual Redis, Redis ACL smoke, Compose validation and production Docker build
- [ ] Real staging authenticated cutover and restart/rollback completed
- [ ] Host ingress/networks verified by operator, credential rotation planned
- [ ] PH-003 protected Redis migration interaction tested if enabled
- [ ] TLS checked separately if connecting across untrusted networks

**PH-010 stays In review until the staging gates are satisfied.**
