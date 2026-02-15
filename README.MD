# Advanced File Filter Bot

A production-style Telegram media indexing and retrieval platform with distributed caching, multi-database fault tolerance, and operations-focused admin tooling.

This project is built as a single-developer system and is structured to demonstrate real backend engineering depth, not just bot commands.

## Portfolio Summary

Advanced File Filter Bot is an async Python system that:
- Indexes media from Telegram channels.
- Supports high-volume search with fuzzy matching and pagination.
- Enforces premium/free access policies with atomic quota control.
- Uses Redis for caching, rate limiting, and session state.
- Uses MongoDB with optional multi-database write failover.
- Provides admin operations for broadcast, performance, cache, and database management.

## Why This Project Is Portfolio-Grade

- Reliability engineering: circuit breaker database failover, retry policies, graceful shutdown cleanup.
- Concurrency design: domain-based semaphore control for Telegram API and database workloads.
- Data correctness: atomic quota reservation and race-condition-safe counters.
- Scalability patterns: cache versioning, batch duplicate checks, queue backpressure, multi-db routing.
- Operations readiness: health/metrics endpoints, maintenance jobs, dockerized deployment, update/rollback tooling.

## Architecture

Full architecture diagrams are in `docs/architecture/diagrams.md`.

Included views:
- System context.
- Runtime container architecture.
- Component and data flow.
- Search and delivery sequence flows.
- Channel indexing sequence flow.
- Circuit breaker state model.
- Data model diagram.
- Deployment topology.

## Real Engineering Issues Solved

See full write-up in `docs/portfolio/engineering-issues-solved.md`.

Highlights:
- Race conditions in quota usage during bulk file delivery.
- Cross-database pagination correctness.
- Database pool fault isolation and circuit breaker recovery.
- Cache invalidation scalability under write-heavy workloads.
- Broadcast state consistency across restarts.
- Queue overflow handling for continuous channel indexing.

## Project Scale Snapshot

Snapshot date: February 14, 2026.

- Python files: `85`
- Python LOC (approx): `23,563`
- Service modules: `11`
- Repository modules: `7`
- Handler modules (root + command + callback): `27`
- Bot command handler definitions (`filters.command(...)`): `52`

## Stack

- Language/runtime: Python 3.9+
- Telegram framework: Pyrofork/Pyrogram-compatible API usage
- Datastore: MongoDB (single or multi-database mode)
- Cache/session/rate limiting: Redis
- Async web endpoints: aiohttp
- Deployment: Docker, Docker Compose, VPS-style process runtime
- Tooling: Ruff, mypy, pytest config (project-level), structured operational scripts

## Core Technical Features

- Multi-database manager with smart write selection and circuit breaker logic.
- Indexing pipeline with batch duplicate checks to avoid N+1 query behavior.
- Versioned search cache invalidation strategy for O(1) global search cache resets.
- Unified session manager for edit/search/index workflows.
- Per-domain concurrency guardrails via semaphore manager.
- Robust Telegram API wrapper with FloodWait-aware retry behavior.

## Quick Start

### Local

```bash
git clone https://github.com/rumalg123/Advanced-File-Filter-Bot.git
cd Advanced-File-Filter-Bot
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python bot.py
```

### Docker Compose

```bash
docker-compose up -d
docker-compose logs -f file-filter-bot
```

## Operational Endpoints

- `GET /health`
- `GET /metrics`
- `GET /performance`

These are served by the internal aiohttp service started with the bot runtime.

## Repository Map

- `bot.py`: application bootstrap, dependency wiring, lifecycle management.
- `config/settings.py`: centralized typed configuration.
- `handlers/`: Telegram command, callback, indexing, search, and request handling.
- `core/services/`: business workflows.
- `repositories/`: persistence boundary and cache-aware data access.
- `core/database/`: connection pooling, multi-db manager, index optimizer.
- `core/cache/`: Redis abstraction, serialization, invalidation.
- `core/concurrency/`: global semaphore-based concurrency controls.
- `core/session/`: unified session model and cleanup.

## Portfolio Assets In This Repo

- Architecture diagrams: `docs/architecture/diagrams.md`
- Engineering issues solved: `docs/portfolio/engineering-issues-solved.md`
- Resume and interview kit: `docs/portfolio/resume-and-interview-kit.md`
- Demo walkthrough script: `docs/portfolio/demo-script.md`
- Portfolio publishing checklist: `docs/portfolio/portfolio-checklist.md`
- Portfolio docs index: `docs/portfolio/README.md`

## Author

- Name: Rumal Gunawardana
- GitHub: https://github.com/rumalg123
- Email: rumalg123@gmail.com
- Telegram: https://t.me/gunaya001

## License

MIT. See `LICENSE`.
