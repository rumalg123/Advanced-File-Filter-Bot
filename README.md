# Advanced File Filter Bot

An asynchronous Telegram file indexing, search, and delivery bot built on [wzgram](https://wzgram.rj1.dev/), MongoDB, Redis, and aiohttp.

The bot can index media from Telegram channels, search it with typo-tolerant matching, deliver single files or batches, enforce subscriptions and quotas, run group auto-filters, and provide personalized recommendations. It also includes optional, independently gated features such as saved-search alerts, favorites, advanced search, reports, request tracking, and a content dashboard.

> **Live deployment guarantee:** every newly added feature in `FEATURE_ROADMAP.md` defaults to `false`. Deploying the code does not enable those flows by itself. Enable one flag at a time, restart, and smoke-test it before enabling the next.

## Contents

- [What the bot does](#what-the-bot-does)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Docker deployment](#docker-deployment)
- [Production deployment](#production-deployment)
- [Configuration model](#configuration-model)
- [Environment variable reference](#environment-variable-reference)
- [Feature rollout flags](#feature-rollout-flags)
- [Commands](#commands)
- [Search behavior](#search-behavior)
- [Data and cache ownership](#data-and-cache-ownership)
- [Operations](#operations)
- [Testing](#testing)
- [Safe live rollout](#safe-live-rollout)
- [Troubleshooting](#troubleshooting)
- [Repository map](#repository-map)

## What the bot does

### Search and delivery

- Searches indexed Telegram media by file name and, when enabled, caption.
- Uses normalized, fuzzy, and typo-tolerant matching with paginated results.
- Supports private-chat, group, callback-pagination, and inline-query search.
- Understands common season, episode, and resolution patterns in file names.
- Suggests similar historical queries when a private search returns no files.
- Sends individual files or all files on a page with atomic quota reservation.
- Formats captions consistently and schedules configured auto-deletion.

### Indexing and file storage

- Auto-indexes configured source channels.
- Supports manual range indexing and configurable message skipping.
- Uses bounded main and overflow queues to apply backpressure.
- Performs batch duplicate checks before writes.
- Extracts media type, size, MIME type, resolution, season, and episode metadata.
- Creates shareable single-file, protected, batch, and premium-only deep links.

### Access control

- Supports free and premium access policies.
- Uses atomic daily quota counters so concurrent file callbacks cannot overspend a limit.
- Supports force subscription to a channel and multiple groups.
- Supports additional authorized users, bans, request limits, warnings, and auto-ban behavior.
- Restricts sensitive operations to configured administrators; `/bsetting` and `/shell` are primary-admin-only.

### Filters and group connections

- Lets group admins create text/media auto-filters.
- Supports private management of a connected group.
- Matches exact filter keywords first and can provide fuzzy suggestions during management.
- Can disable the entire filter/connection subsystem with `DISABLE_FILTER=true`.

### Recommendations and search history

- Tracks user and global search history in Redis sorted sets.
- Learns bidirectional query co-occurrence from consecutive searches.
- Learns file co-occurrence from result pages and successful clicks.
- Produces similar queries, history-based file suggestions, and trending suggestions.
- Falls back to RapidFuzz similarity when co-occurrence data is sparse.
- Invalidates a user's cached recommendations when new signals or feedback arrive.

### Scaling and operations

- Runs with a single MongoDB or distributes media across multiple MongoDB databases.
- Searches healthy media databases concurrently, then merges, sorts, and paginates results.
- Uses per-database circuit breakers and optional automatic write-database switching.
- Uses Redis for cache, sessions, atomic rate limiting, search history, and recommendation state.
- Exposes health and performance endpoints through aiohttp.
- Includes cache, database, broadcast, performance, log, update, and maintenance tooling.
- Tracks handlers and background tasks for graceful shutdown.

### Optional additive features

The following capabilities are implemented but disabled by default:

- Saved searches with deduplicated new-file alerts.
- Favorites and named collections.
- Structured advanced-search filters.
- Recommendation “more like this” and “less like this” feedback.
- File reports and an admin resolution queue.
- Search autocomplete from user/global history.
- Conservative grouping of likely quality/encode variants.
- Persistent content-request tracking.
- Recently delivered file history.
- Human-readable recommendation explanations.
- Admin content-health and zero-result dashboard.

Multilingual/semantic search is intentionally not included. The optional `lang:` advanced filter only matches a language token already present in indexed file names or captions.

## Architecture

The runtime follows a handler → service → repository structure:

```text
Telegram update
    -> wzgram client and handlers
    -> domain services
    -> cache-aware repositories
    -> MongoDB / Redis
```

- `bot.py` validates configuration, creates connection pools, synchronizes database-backed settings, wires dependencies, starts the Telegram client, registers handlers, and starts the HTTP server.
- `handlers/` owns Telegram commands, messages, callbacks, inline queries, and indexing events.
- `core/services/` owns business workflows such as access checks, indexing, recommendations, file-store links, broadcasts, and maintenance.
- `repositories/` owns persistence and cache invalidation.
- `core/database/` owns MongoDB pools, indexes, multi-database routing, retry behavior, and circuit breakers.
- `core/cache/` owns Redis serialization, TTLs, monitoring, key generation, and invalidation.
- `core/session/` owns expiring interaction sessions.

See the code-derived [architecture diagrams](docs/architecture/diagrams.md) for system context, startup, search, delivery, indexing, recommendations, cache, settings, multi-database, data-model, and deployment views.

### Wzgram compatibility note

The project dependency is pinned to a specific `wzgram` Git commit in `pyproject.toml` and `requirements.txt`. Wzgram exposes a Pyrogram-compatible import namespace, so source imports such as `from pyrogram import Client` are expected; they do not mean the project still installs the unmaintained upstream Pyrogram distribution.

## Requirements

- Python 3.13 or newer.
- Git, because `wzgram` is installed directly from a pinned Git revision.
- A Telegram API ID and API hash from `my.telegram.org`.
- A bot token from BotFather.
- MongoDB, either local or hosted.
- Redis, either local or hosted.
- A Telegram user ID for `ADMINS`.
- Bot admin access in every source, log, file-store, authentication, or support channel it must read or write.

Linux additionally uses `tgcrypto` and `uvloop` when installed by the project dependencies. Windows uses the standard asyncio event loop.

## Quick start

### 1. Clone the repository

```bash
git clone https://github.com/rumalg123/Advanced-File-Filter-Bot.git
cd Advanced-File-Filter-Bot
```

### 2. Create a virtual environment

Windows PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Linux or macOS:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

### 3. Configure the minimum environment

Edit `.env` and set at least:

```dotenv
API_ID=123456
API_HASH=your_telegram_api_hash
BOT_TOKEN=123456:your_bot_token

DATABASE_URI=mongodb://localhost:27017
DATABASE_NAME=PIRO
REDIS_URI=redis://localhost:6379/0

ADMINS=123456789
LOG_CHANNEL=0
```

`ADMINS` is comma-separated. Telegram chat/channel IDs usually begin with `-100`; user IDs do not.

### 4. Start the bot

```bash
python bot.py
```

On startup the application will:

1. Validate Telegram, MongoDB, and Redis settings.
2. Connect to MongoDB and Redis.
3. Seed any missing Mongo-backed bot settings from the environment/defaults.
4. Load the authoritative settings from MongoDB.
5. Create required indexes.
6. Start the wzgram client and register handlers.
7. Start background maintenance and the aiohttp server.

Check `logs/bot.txt` or the console for the bot username and startup status.

## Docker deployment

The included Compose stack runs the bot and Redis. MongoDB remains external, so `DATABASE_URI` must point to a reachable server or MongoDB Atlas cluster.

### Start

```bash
cp .env.example .env
# Edit .env before continuing
docker compose up --build -d
docker compose logs -f file-filter-bot
```

Windows PowerShell uses `Copy-Item .env.example .env` instead of `cp`.

Compose overrides the bot's `REDIS_URI` with `redis://redis:6379/0`, waits for Redis to become healthy, persists Redis data, and publishes bot port `8000` on host port `8000`.

### Check health

```bash
curl http://localhost:8000/health
curl http://localhost:8000/metrics
```

### Update a Docker deployment

For an immutable and reproducible deployment, leave `AUTO_UPDATE=false` and rebuild the image:

```bash
git pull
docker compose build --pull file-filter-bot
docker compose up -d file-filter-bot
docker compose logs -f --tail=200 file-filter-bot
```

Do not run `docker compose down -v` during a normal update; `-v` removes named Redis/log/data volumes. Do not flush Redis as part of routine deployment.

### Docker details

- `redis-data` persists Redis AOF/RDB data.
- `bot-logs` persists application logs.
- `bot-backups` and `bot-data` are mounted for operational data.
- Redis is not published to the host by Compose.
- The bot health check calls `/health`.
- If `PORT` is changed from `8000`, update the Compose port mapping and health check consistently.

## Production deployment

The `Dockerfile` can be used on a VPS or a container PaaS.

### Required services

Provision:

1. One bot container/process per Telegram bot token.
2. One MongoDB deployment, plus optional additional media databases.
3. One Redis deployment with persistence appropriate to your recovery goals.
4. An exposed HTTP port matching `PORT` for health checks.

Avoid running multiple polling replicas with the same bot token. They can compete for Telegram updates and duplicate background work.

### Generic PaaS checklist

- Deploy from the included `Dockerfile`.
- Set the required environment variables in the platform secret manager.
- Attach MongoDB and Redis services or use external connection URIs.
- Expose `PORT`, default `8000`.
- Configure the health path as `/health`.
- Keep `AUTO_UPDATE=false`; deploy new images through the platform instead.
- Persist `logs/` only if the platform does not already retain stdout logs.
- Ensure the bot can make outbound connections to Telegram, MongoDB, and Redis.
- Run only one application replica for the token.

### Native Linux service

The included startup wrapper can create a virtual environment, install dependencies, optionally update, and start the bot:

```bash
chmod +x start.sh
./start.sh --setup
./start.sh
```

Useful wrapper modes:

```bash
./start.sh --check
./start.sh --update
./start.sh --help
```

For a systemd service, set `WorkingDirectory` to the repository, load secrets with `EnvironmentFile`, and run either the virtual-environment Python executable with `bot.py` or `start.sh`. Let systemd restart the process instead of starting multiple copies.

## Configuration model

Configuration has two phases:

1. **Bootstrap environment:** Pydantic reads `.env` and process variables. Telegram credentials, `DATABASE_URI`, and `REDIS_URI` must be valid here because the app needs them to connect.
2. **Mongo-backed runtime settings:** after connecting, `BotSettingsService` inserts only missing keys into `bot_settings`, then loads all managed values and synchronizes them into runtime configuration.

This has an important consequence: after a managed setting exists in MongoDB, changing only its environment variable does **not** overwrite it. For an existing installation, use `/bsetting`, save the value, and restart the bot.

Treat these as deployment/bootstrap settings and manage them in the environment:

- `API_ID`, `API_HASH`, `BOT_TOKEN`, `SESSION`
- `DATABASE_URI`, `DATABASE_NAME`, `DATABASE_URIS`, `DATABASE_NAMES`
- `REDIS_URI`
- `PROCESSING_*`, `CONCURRENCY_*`
- Update-wrapper settings such as `AUTO_UPDATE`

Treat feature flags, limits, messages, channel IDs, and most presentation settings as Mongo-backed after their first seed. `/bsetting` explicitly reminds the admin to restart because handlers, command menus, repositories, worker counts, and optional indexes are constructed during startup.

### Environment precedence

Pydantic settings are case-insensitive. Process environment values normally override `.env` values. Mongo-backed values are then loaded later for managed runtime keys.

Never commit `.env`. The repository `.gitignore` is intended to keep secrets out of version control.

## Environment variable reference

### Required bootstrap settings

| Variable | Required | Default | Purpose |
|---|---:|---:|---|
| `API_ID` | Yes | none | Telegram application ID. Must be an integer. |
| `API_HASH` | Yes | none | Telegram application hash. |
| `BOT_TOKEN` | Yes | none | Bot token issued by BotFather. |
| `DATABASE_URI` | Yes | none | Primary MongoDB connection URI. Also stores all control/user collections. |
| `REDIS_URI` | Yes | none | Redis connection URI for cache, sessions, rate limits, histories, and recommendations. |
| `ADMINS` | Operationally yes | empty | Comma-separated Telegram user IDs allowed to use admin commands. The first ID is the primary admin. |

### Telegram and server

| Variable | Default | Purpose |
|---|---:|---|
| `SESSION` | `Media_search` | Local wzgram session name. Use a stable value per deployment. |
| `PORT` | `8000` | aiohttp port serving `/`, `/health`, `/metrics`, and `/performance`. |
| `WORKERS` | `50` | Wzgram update worker count configured when the client is constructed. |
| `ENVIRONMENT` | `production` | Marks `dev`/`development`; other values are treated as production. |
| `IN_DOCKER` | unset | Explicit Docker detection hint; Docker is also detected through `/.dockerenv`. |
| `KUBERNETES_SERVICE_HOST` | platform supplied | Presence marks the runtime as Kubernetes. Normally injected by Kubernetes rather than set manually. |
| `TZ` | `UTC` in Compose | Container/system timezone. Most persisted application timestamps use UTC. |

### MongoDB and multi-database routing

| Variable | Default | Purpose |
|---|---:|---|
| `DATABASE_NAME` | `PIRO` | Primary database name. |
| `DATABASE_COLLECTION_NAME` | `FILES` | Legacy configuration adapter value. Core repositories use explicit collection names such as `media_files`; normally leave this unchanged. |
| `DATABASE_URIS` | empty | Comma-separated **additional** MongoDB URIs for distributed media storage. The primary `DATABASE_URI` is always first. |
| `DATABASE_NAMES` | empty | Comma-separated names for the additional URIs. Missing names fall back to `DATABASE_NAME`. |
| `DATABASE_SIZE_LIMIT_GB` | `0.5` | Approximate database-size threshold used by automatic media write switching. |
| `DATABASE_AUTO_SWITCH` | `true` | Select another healthy writable media database when the current database reaches its limit. |
| `DATABASE_MAX_FAILURES` | `5` | Failures before a database circuit breaker opens. |
| `DATABASE_RECOVERY_TIMEOUT` | `300` | Seconds an open circuit waits before a half-open probe. |
| `DATABASE_HALF_OPEN_CALLS` | `3` | Maximum calls allowed while testing a half-open database. |

`COLLECTION_NAME` appears in older templates, but the current prefixed Pydantic setting is `DATABASE_COLLECTION_NAME`.

Only media operations use the optional multi-database manager. Users, settings, channels, connections, filters, links, and additive feature collections remain on the primary database.

### Channels, groups, and authorization

| Variable | Default | Purpose |
|---|---:|---|
| `LOG_CHANNEL` | `0` | Startup, maintenance, request, and operational log destination. `0` disables Telegram logging. |
| `INDEX_REQ_CHANNEL` | `0` | Destination for index requests. Set it explicitly; `0` leaves the destination unset. |
| `FILE_STORE_CHANNEL` | empty | Space-separated channel IDs used by file-store workflows. |
| `DELETE_CHANNEL` | unset | Optional channel involved in file-deletion workflows. |
| `REQ_CHANNEL` | `0` | Destination for content requests. Set it explicitly; `0` leaves the destination unset. |
| `SUPPORT_GROUP_ID` | unset | Group where messages beginning with `#request ` are handled. |
| `AUTH_CHANNEL` | unset | Force-subscription channel ID or username. |
| `AUTH_GROUPS` | empty | Comma-separated force-subscription group IDs. |
| `AUTH_USERS` | empty | Comma-separated users allowed by authorization checks; admins are appended automatically. |
| `CHANNELS` | `0` | Comma-separated numeric source-channel IDs for auto-indexing. `0` is discarded. Channels can also be managed with admin commands. |
| `PICS` | empty | Comma-separated image URLs used randomly by the start command. |

The bot must be a member and usually an administrator in each configured channel/group. Use full Telegram IDs, including the `-100` prefix for channels and supergroups.

### Established feature and access settings

| Variable | Default | Purpose |
|---|---:|---|
| `USE_CAPTION_FILTER` | `true` | Include captions in media search matching. |
| `DISABLE_PREMIUM` | `true` | Disable premium enforcement and present unlimited access. Set `false` to use premium/free limits. |
| `REQUEST_ONLY_FOR_PREMIUM` | `false` | Allow `#request` only for premium users. |
| `DISABLE_FILTER` | `false` | Disable filter and group-connection handlers/services. |
| `PUBLIC_FILE_STORE` | `false` | Allow non-admin users to create file-store links. |
| `KEEP_ORIGINAL_CAPTION` | `true` | Prefer an indexed file's original caption during delivery. |
| `USE_ORIGINAL_CAPTION_FOR_BATCH` | `true` | Prefer original captions for batch delivery. |
| `PREMIUM_DURATION_DAYS` | `30` | Number of days granted by `/addpremium`. |
| `NON_PREMIUM_DAILY_LIMIT` | `10` | Daily successful-file quota for free users. |
| `PREMIUM_PRICE` | `$1` | Display value used by `/plans`. |
| `MESSAGE_DELETE_SECONDS` | `300` | Delay before temporary result/file messages are auto-deleted. |
| `MAX_BTN_SIZE` | `12` | Maximum search-result buttons per page. |
| `REQUEST_PER_DAY` | `3` | Daily `#request` allowance before warnings. |
| `REQUEST_WARNING_LIMIT` | `5` | Request-abuse warnings before automatic ban. |

### Additive feature flags

Every value below defaults to `false`:

| Variable | Capability |
|---|---|
| `FEATURE_SAVED_SEARCH_ALERTS` | `/save_search`, `/saved_searches`, and deduplicated alerts after new media is indexed. |
| `FEATURE_FAVORITES` | Favorites, named collections, commands, and result-button actions. |
| `FEATURE_ADVANCED_SEARCH` | Structured `key:value` search filters and `/search_help`. |
| `FEATURE_RECOMMENDATION_FEEDBACK` | More/less recommendation buttons and persisted feedback. |
| `FEATURE_FILE_REPORTS` | User report buttons plus `/file_reports` and `/resolve_report` for admins. |
| `FEATURE_SEARCH_AUTOCOMPLETE` | `/suggest` using user and global search history. |
| `FEATURE_DUPLICATE_GROUPING` | Group likely encode/quality variants without discarding files. |
| `FEATURE_REQUEST_TRACKING` | Deduplicate/persist unresolved `#request` items and expose `/myrequests`. |
| `FEATURE_RECENT_FILES` | Store successful deliveries and expose `/recent` and `/clear_recent`. |
| `FEATURE_RECOMMENDATION_EXPLANATIONS` | Show a reason beside recommended files. |
| `FEATURE_CONTENT_DASHBOARD` | Persist zero-result analytics and expose `/content_dashboard` to admins. |

### Messages and presentation

| Variable | Default | Purpose |
|---|---:|---|
| `CUSTOM_FILE_CAPTION` | empty | Custom caption for normal delivery. Common placeholders include `{filename}` and `{size}`. |
| `BATCH_FILE_CAPTION` | empty | Custom caption for batch delivery. |
| `AUTO_DELETE_MESSAGE` | built-in text | Notice shown for auto-deleted content. Supports `{content_type}` and `{minutes}`. |
| `START_MESSAGE` | built-in text | Start-command template. The settings UI documents supported user/bot placeholders. |
| `SUPPORT_GROUP_URL` | empty | URL attached to support/no-result actions. |
| `SUPPORT_GROUP_NAME` | `Support Group` | Display name for the support link. |
| `PAYMENT_LINK` | project default | URL used by the premium purchase button. Set this to your own payment/support URL. |

Telegram messages use HTML-style formatting through the configured caption formatter. Test custom templates with a non-production admin account before rollout.

### Concurrency controls

| Variable | Default | Protected work |
|---|---:|---|
| `CONCURRENCY_TELEGRAM_SEND` | `10` | Concurrent Telegram send calls. |
| `CONCURRENCY_TELEGRAM_FETCH` | `15` | Concurrent Telegram fetch calls. |
| `CONCURRENCY_DATABASE_WRITE` | `20` | Repository writes and bulk mutations. |
| `CONCURRENCY_DATABASE_READ` | `30` | Repository reads and queries. |
| `CONCURRENCY_FILE_PROCESSING` | `5` | File metadata processing. |
| `CONCURRENCY_BROADCAST` | `3` | Broadcast work. |
| `CONCURRENCY_INDEXING` | `8` | Concurrent indexing operations. |

Raise these only after observing Telegram flood waits, MongoDB latency, Redis latency, CPU, and memory. More concurrency is not automatically more throughput.

### Channel-processing limits

All processing variables use the `PROCESSING_` prefix:

| Variable | Default | Purpose |
|---|---:|---|
| `PROCESSING_BATCH_SIZE_HIGH_LOAD` | `50` | Worker batch size above the high queue threshold. |
| `PROCESSING_BATCH_SIZE_MEDIUM_LOAD` | `30` | Worker batch size above the medium threshold. |
| `PROCESSING_BATCH_SIZE_LOW_LOAD` | `20` | Worker batch size at low load. |
| `PROCESSING_QUEUE_HIGH_THRESHOLD` | `500` | Queue count considered high load. |
| `PROCESSING_QUEUE_MEDIUM_THRESHOLD` | `200` | Queue count considered medium load. |
| `PROCESSING_MAX_BATCH_MESSAGES` | `10000` | Maximum messages represented by one batch link. |
| `PROCESSING_MESSAGE_QUEUE_SIZE` | `1000` | Main auto-indexing queue capacity. |
| `PROCESSING_OVERFLOW_QUEUE_SIZE` | `500` | Overflow queue capacity. |
| `PROCESSING_INTER_MESSAGE_DELAY` | `0.5` | Delay between processed messages in seconds. |
| `PROCESSING_BATCH_WAIT_TIME_HIGH` | `2` | High-load batch wait in seconds. |
| `PROCESSING_BATCH_WAIT_TIME_MEDIUM` | `3` | Medium-load batch wait in seconds. |
| `PROCESSING_BATCH_WAIT_TIME_LOW` | `5` | Low-load batch wait in seconds. |

### Startup/update wrapper

These variables are consumed by `start.sh`/`update.py`, not the normal search runtime:

| Variable | Default | Purpose |
|---|---:|---|
| `UPDATE_REPO` | project repository | Git repository used by the update wrapper. |
| `UPDATE_BRANCH` | `main` | Branch used by the update wrapper. |
| `AUTO_UPDATE` | `false` | Run the update workflow whenever `start.sh` starts. |
| `UPDATE_ON_START` | `false` | Also triggers the startup update workflow. |
| `BACKUP_ON_UPDATE` | `true` | Ask `update.py` to create its code backup before updating. |
| `CONTINUE_ON_UPDATE_FAIL` | `false` | In Docker, continue with current code when an attempted update fails. |

Use image rebuilds instead of in-container auto-update for production Docker/PaaS deployments. Code backups are not MongoDB backups.

### Settings that look supported but are not runtime controls

- `CACHE_TTL` and `MAX_CONNECTIONS` currently appear in Compose defaults, but the application does not read them. `CACHE_TIME` in `/bsetting` controls search-result cache TTL; other TTLs live in `core/cache/config.py`.
- `COLLECTION_NAME` is an older template name. The current typed variable is `DATABASE_COLLECTION_NAME`, and core collections use explicit repository names.
- `UPSTREAM_REPO` and `UPSTREAM_BRANCH` are Mongo setting keys. Their environment aliases are `UPDATE_REPO` and `UPDATE_BRANCH`.

## Feature rollout flags

For a new database, a `FEATURE_*` environment value seeds the corresponding Mongo setting. For an existing live database, change the flag through `/bsetting` and restart.

Recommended rollout order:

| Order | Flag | Minimal smoke test |
|---:|---|---|
| 1 | `FEATURE_RECENT_FILES` | Deliver one file, run `/recent`, then `/clear_recent`. |
| 2 | `FEATURE_FAVORITES` | Favorite a delivered file, list it, create/delete a named collection. |
| 3 | `FEATURE_SEARCH_AUTOCOMPLETE` | Build search history, then run `/suggest partial`. |
| 4 | `FEATURE_ADVANCED_SEARCH` | Run `/search_help`, then test type/year/size filters. |
| 5 | `FEATURE_DUPLICATE_GROUPING` | Search a title with multiple quality variants and verify every file remains accessible. |
| 6 | `FEATURE_RECOMMENDATION_EXPLANATIONS` | Build search/click history and inspect `/recommendations`. |
| 7 | `FEATURE_RECOMMENDATION_FEEDBACK` | Use more/less buttons and refresh recommendations. |
| 8 | `FEATURE_REQUEST_TRACKING` | Submit a missing `#request`, verify `/myrequests`, and test duplicate prevention. |
| 9 | `FEATURE_FILE_REPORTS` | Report a result, review `/file_reports`, then resolve it. |
| 10 | `FEATURE_SAVED_SEARCH_ALERTS` | Save a query, index a new matching file, confirm exactly one alert. |
| 11 | `FEATURE_CONTENT_DASHBOARD` | Cause a zero-result search and review `/content_dashboard`. |

If a smoke test fails, set only that flag back to `false`, restart, and keep the rest of the established bot flow unchanged.

## Commands

The bot publishes different Telegram command menus for private chats, groups, admins, and the primary admin. A command can still work even if Telegram has not refreshed the visible menu yet.

### Core user commands

| Command | Purpose |
|---|---|
| `/start` | Register/open the bot and handle deep links. |
| `/help` | Show user help and additional admin help when applicable. |
| `/about` | Show bot information. |
| `/stats` | Show users, media, file-type, and storage statistics. |
| `/plans` | Show free/premium limits and payment link. |
| `/request_stats` | Show request limits, warnings, and totals. |
| `/my_keywords` | Show the user's most searched keywords. |
| `/popular_keywords` | Show global popular searches. |
| `/recommendations` | Show similar queries, personalized files, and trending files. |

Send ordinary text with at least two characters to search. In inline mode, type the bot username and query in another chat.

### Optional user commands

| Feature | Commands |
|---|---|
| Saved searches | `/save_search movie title`, `/saved_searches` |
| Favorites | `/favorite`, `/unfavorite`, `/favorites [collection]`, `/collections`, `/collection_create name`, `/collection_delete name` |
| Recent files | `/recent`, `/clear_recent` |
| Autocomplete | `/suggest partial title` |
| Advanced search | `/search_help` |
| Request tracking | `/myrequests` |

For `/favorite`, reply to a delivered file, or use `/favorite file_unique_id [collection name]`.

### Group filters and connections

Available only when `DISABLE_FILTER=false`:

| Command | Purpose |
|---|---|
| `/connect [group_id]` | Connect the current group or connect to a group from private chat. |
| `/disconnect` | Disconnect the current group. |
| `/connections` | Manage connected groups in private chat. |
| `/add keyword` or `/filter keyword` | Add an automatic filter, using command text/reply media as content. |
| `/filters` or `/viewfilters` | List filters in the active/current group. |
| `/del keyword` | Delete one or more filters. Aliases: `/delf`, `/deletef`. |
| `/delall` | Delete all filters after confirmation. Aliases: `/delallf`, `/deleteallf`. |

Group administration checks still apply; enabling filters does not let ordinary users modify group filters.

### File-store commands

When `PUBLIC_FILE_STORE=false`, these are admin-only. When it is `true`, they are registered publicly.

| Command | Purpose |
|---|---|
| `/link` | Reply to supported media to create a normal single-file link. |
| `/plink` | Reply to supported media to create a protected single-file link. |
| `/batch first_link last_link` | Create a normal batch deep link for a Telegram message range. |
| `/pbatch first_link last_link` | Create a protected batch link. |
| `/batch_premium first_link last_link` | Create a premium-only batch. Alias: `/bprem`. |
| `/pbatch_premium first_link last_link` | Create a protected premium-only batch. Alias: `/pbprem`. |

Both batch endpoints must refer to the same source channel and the bot must be able to read it.

### Admin commands

| Area | Commands |
|---|---|
| Users/access | `/users`, `/ban user_id [reason]`, `/unban user_id`, `/addpremium user_id`, `/removepremium user_id` |
| Broadcast | `/broadcast` by replying to a message, `/stop_broadcast`, `/reset_broadcast_limit` |
| Channels/indexing | `/add_channel`, `/remove_channel`, `/list_channels`, `/toggle_channel`, `/setskip number` |
| Files | `/delete` by replying to media, `/deleteall keyword` |
| Runtime | `/log`, `/performance`, `/restart` |
| Cache | `/cache_stats`, `/cache_analyze`, `/cache_cleanup` |
| Multi-database | `/dbstats`, `/dbinfo`, `/dbswitch` |
| Optional reports | `/file_reports [open|resolved|all]`, `/resolve_report report_id` |
| Optional dashboard | `/content_dashboard` |

Primary-admin-only commands:

- `/bsetting` opens the Mongo-backed settings editor.
- `/verify` runs file-access verification.
- `/cancel` cancels an active settings operation.
- `/shell command` executes a server shell command. Treat the primary admin account as infrastructure-level access.

### Request workflow

When `SUPPORT_GROUP_ID` is configured, users submit:

```text
#request title or keywords
```

The bot searches first. If no result exists, it applies request/premium rules and forwards the request for admin handling. With request tracking enabled, pending duplicates are rejected and users can inspect `/myrequests`.

## Search behavior

### Normal search

The media repository normalizes the query, extracts common season/episode/resolution patterns, performs indexed/fuzzy matching, sorts results, and caches each page. Search pages are tied to a global cache version so media writes invalidate future reads without scanning and deleting every old Redis key.

### Advanced search

With `FEATURE_ADVANCED_SEARCH=true`, add filters after a title:

```text
matrix type:video year:1999 quality:1080p
show season:1 episode:4 maxsize:2GB
document title type:document minsize:100KB maxsize:20MB
movie lang:english
```

Supported filters:

| Filter | Accepted value |
|---|---|
| `type:` | `video`, `audio`, `document`, `photo`, `animation`, or `application` |
| `year:` | `1900` through `2100` |
| `lang:` / `language:` | A language word already present in file name/caption |
| `quality:` | `720p`, `1080p`, or dimensions such as `1920x1080` |
| `season:` | `0` through `999` |
| `episode:` | `0` through `999` |
| `minsize:` | Bytes or `KB`, `MB`, `GB`, `TB` |
| `maxsize:` | Bytes or `KB`, `MB`, `GB`, `TB` |

Quoted filter values are accepted. `minsize` cannot exceed `maxsize`.

### Similar keywords

“Did you mean?” and `/suggest` are not hard-coded keyword lists. They compare the current text against the user's history and global history with RapidFuzz. Recommendation similarity additionally uses query co-occurrence learned from real search sequences.

New installations need successful search activity before meaningful personalized or co-occurrence suggestions appear.

## Data and cache ownership

### MongoDB is authoritative

Core collections:

- `users`
- `media_files`
- `indexed_channels`
- `connections`
- `filters_<group_id>` and `global_filters`
- `batch_links`
- `bot_settings`

Feature collections are created/indexed only when at least one additive feature is enabled:

- `user_collections`
- `recent_files`
- `saved_searches`
- `saved_search_notifications`
- `recommendation_feedback`
- `file_reports`
- `content_requests`
- `search_analytics`

Back up MongoDB before upgrades that change data or indexes. The included updater's source backup is not a database backup.

### Redis responsibilities

Redis contains:

- Entity/list caches for users, media, channels, connections, filters, settings, and links.
- Versioned media search pages.
- Search pagination, settings-edit, deep-link, subscription, and other temporary sessions.
- Atomic rate-limit counters and cooldowns.
- User/global search history.
- Query/file co-occurrence, query-to-file mappings, user interactions, and cached recommendations.
- Broadcast state and temporary locks.

Search sessions and other temporary keys receive explicit TTLs. Normal maintenance lets Redis expire them; it does not delete all live Telegram sessions. A media mutation increments the search cache version, making old search pages unreachable until their TTL removes them.

Do not flush Redis during a routine deploy. A flush removes active buttons/sessions and recommendation/search-history signals even though MongoDB media remains intact.

### Default cache durations

Important defaults from `core/cache/config.py`:

| Data | TTL |
|---|---:|
| User/media/filter entity | 5 minutes |
| Search result page | 5 minutes (`CACHE_TIME` can override after restart) |
| Search callback session | 1 hour |
| User search history | 30 days |
| Global search history | 1 year |
| Query/file co-occurrence | 30 days |
| Query-to-file mapping | 7 days |
| User recommendation output | 10 minutes |
| Batch-link cache | up to 24 hours and never beyond link expiry |

## Operations

### HTTP endpoints

| Endpoint | Purpose | Status behavior |
|---|---|---|
| `GET /` | Alias of health. | `200` for healthy/degraded, otherwise `503`. |
| `GET /health` | Bot identity plus Mongo/Redis/system health data. | `200` or `503`. |
| `GET /metrics` | Process/system performance metrics. | `200`, or `500` on collection error. |
| `GET /performance` | Alias of metrics. | Same as `/metrics`. |

These endpoints currently allow broad CORS and have no authentication. Expose them only through a trusted network, firewall, or authenticated reverse proxy if the metric details are sensitive.

### Logging

- Application logs go to stdout and `logs/bot.txt`.
- `bot.txt` rotates at 5 MB and keeps five backups.
- `start.sh` also tees each run to a timestamped log and maintains `logs/current.log` when supported.
- `/log` sends the current bot log to an admin.

Never log or paste `BOT_TOKEN`, `API_HASH`, database passwords, Redis passwords, or full environment dumps.

### Maintenance

The bot schedules:

- Daily user/media/cache/link maintenance.
- Hourly premium-expiry cleanup after a short startup delay.
- Redis TTL-based cleanup for sessions and cache data.
- Graceful cancellation of tracked handler/background tasks during shutdown.

### Metadata migration

If older `media_files` documents need season, episode, or resolution metadata, preview the migration first:

```bash
python migrate_media_metadata.py --dry-run --limit 100
python migrate_media_metadata.py --dry-run
```

After reviewing the dry-run output and backing up MongoDB:

```bash
python migrate_media_metadata.py --batch-size 1000
```

### Backup and recovery

- Back up MongoDB with your provider's snapshot/backup tools; it is authoritative.
- Preserve Redis if search history, recommendations, live sessions, and rate state matter to recovery.
- Preserve `.env` through a secret manager, not inside public backups.
- Test restores against a staging bot token and separate database names.
- A source-code rollback does not automatically roll back MongoDB documents or indexes.

## Testing

Install development dependencies:

```bash
pip install -e ".[dev]"
```

Run the current test suite:

```bash
python -m pytest -q
```

The repository currently contains 70 focused tests covering access/quota behavior, batch links, cache correctness, configuration/packaging, feature rollout, channel indexing, recommendations/similarity, sessions, wzgram integration boundaries, and plain-text Telegram surfaces.

Useful additional checks:

```bash
python -m compileall -q bot.py config core handlers repositories
python -m ruff check . --select F821
python -m pip check
git diff --check
```

Tests use fakes/mocks for focused behavior and do not replace a staging smoke test against real Telegram, MongoDB, and Redis services.

## Safe live rollout

Use this sequence when the same working tree is going directly to a live system:

1. Back up MongoDB and the current deployment environment.
2. Confirm every new `FEATURE_*` flag is `false` in the authoritative `bot_settings` collection.
3. Run the test and compile checks.
4. Deploy code to a single canary bot process or a staging bot token first when possible.
5. Restart the process; do not run the old and new polling processes simultaneously.
6. Check `/health`, `/metrics`, startup logs, MongoDB connectivity, and Redis connectivity.
7. Smoke-test established flows: search, pagination, one file, Send All, subscription check, group filter, and indexing.
8. Enable one additive feature through `/bsetting`.
9. Restart and run that feature's smoke test.
10. Watch logs, database growth, Redis memory, Telegram flood waits, and callback errors before continuing.

Rollback for an additive feature is normally: set its flag to `false`, restart, and leave its additive collections in place. Disabling a flag unregisters its commands/callback behavior; it does not delete user data.

## Security notes

- Keep `.env` and session files private.
- Use separate least-privilege MongoDB credentials for production.
- Use TLS-enabled MongoDB/Redis endpoints when traffic crosses a trusted network boundary.
- Do not publish Redis port `6379`; Compose intentionally keeps it internal.
- Restrict health/metrics endpoints with network policy or a reverse proxy.
- Keep `ADMINS` minimal. The first admin can edit settings and execute `/shell`.
- Make the bot admin only in channels where it needs admin capabilities.
- Keep auto-update disabled in immutable container deployments.
- Rotate the bot token immediately if it is exposed.

## Troubleshooting

### Startup reports missing API or database values

Confirm `API_ID`, `API_HASH`, `BOT_TOKEN`, `DATABASE_URI`, and `REDIS_URI` exist in the current process or `.env`. `API_ID` must be numeric. Run commands from the repository root so Pydantic can find `.env`.

### An environment change has no effect

The setting probably already exists in MongoDB. Open `/bsetting` as the primary admin, update it there, and restart. Connection URIs remain deployment settings and must be valid before `/bsetting` can be read.

### Optional commands do not appear

Verify the corresponding `FEATURE_*` value in `/bsetting`, restart the bot, and allow Telegram time to refresh the command menu. The handler and menu are both constructed at startup.

### Redis connection fails

- Local runtime: confirm Redis is listening and `REDIS_URI` includes the correct host, port, database, username/password, and TLS scheme if required.
- Compose: use the provided service override `redis://redis:6379/0`; `localhost` inside the bot container refers to the bot container, not Redis.
- Hosted Redis: check firewall/IP allowlists and TLS requirements.

The bot intentionally fails startup if its initial Redis `PING` fails, avoiding a partially initialized cache manager.

### MongoDB connection or index creation fails

Check URI escaping, database permissions, network allowlists, TLS options, and free-tier index limits. Optional feature index failures are logged without taking down established flows, but core connectivity is required.

### Auto-indexing does not run

Confirm the bot can read the source channel, the channel is present/enabled in `/list_channels`, and the channel ID uses the full `-100...` form. Check queue/indexing logs and `/performance`.

### Force subscription always denies users

The bot must be able to inspect membership in `AUTH_CHANNEL` and every `AUTH_GROUPS` entry. Add it with the required permissions and verify the configured IDs/usernames.

### Search buttons expire

Search callback sessions last one hour by default. A process/Redis restart or cache cleanup can end them earlier. Generate a new search page instead of extending unknown stale callback state.

### Recommendations are empty or weak

Recommendations need successful searches, displayed result mappings, and file clicks. Build representative activity, then refresh `/recommendations`. User recommendation output is cached for ten minutes but is invalidated by new tracked signals and feedback.

### Docker health check fails after changing the port

`PORT`, the Docker health URL, and the host/container port mapping must agree. Leaving all three at `8000` is the simplest configuration.

## Repository map

| Path | Responsibility |
|---|---|
| `bot.py` | Entry point, configuration adapter, dependency wiring, lifecycle, command scopes, HTTP server. |
| `config/settings.py` | Typed environment configuration. |
| `handlers/` | Telegram message, command, callback, inline, request, filter, and indexing adapters. |
| `core/services/` | Domain workflows and orchestration. |
| `repositories/` | MongoDB entities, queries, caching, and invalidation. |
| `core/database/` | Pools, indexes, retries, multi-database routing, circuit breakers. |
| `core/cache/` | Redis manager, keys, TTLs, serialization, monitoring, invalidation. |
| `core/concurrency/` | Domain semaphore limits. |
| `core/session/` | Redis-backed interaction sessions. |
| `tests/` | Focused regression tests. |
| `docs/architecture/diagrams.md` | Current architecture diagrams. |
| `FEATURE_ROADMAP.md` | Additive feature scope, flags, and rollout record. |
| `CACHE_AUDIT.md` | Cache audit findings and fixes. |
| `BUG_AUDIT.md` | General bug audit findings and fixes. |
| `migrate_media_metadata.py` | Dry-run-capable media metadata migration. |
| `update.py` | Source update, backup, and rollback helper. |
| `start.sh` | Linux/container setup, health check, optional update, and startup wrapper. |
| `Dockerfile` / `docker-compose.yml` | Container image and local production-style stack. |

## Engineering source documents

- [Architecture diagrams](docs/architecture/diagrams.md)
- [Feature roadmap](FEATURE_ROADMAP.md)
- [Cache audit](CACHE_AUDIT.md)
- [Bug audit](BUG_AUDIT.md)

When behavior and documentation disagree, update the relevant source document and code together. Do not silently enable live features to make documentation examples work.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
