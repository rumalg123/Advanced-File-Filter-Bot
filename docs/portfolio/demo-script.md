# Demo Script (Portfolio Recording)

Use this script for a 8-12 minute technical demo.

## Goal

Show that this project is engineered as a reliable backend system, not only a bot with commands.

## Pre-Demo Setup

- Prepare `.env` with valid Telegram, MongoDB, and Redis credentials.
- Start dependencies (`docker-compose up -d` or managed services).
- Start bot (`python bot.py` or container runtime).
- Keep logs visible in a terminal.

## Demo Flow

1. Architecture positioning (1 minute)
- Open `docs/architecture/diagrams.md`.
- Explain system context and runtime container diagram.
- Mention handler -> service -> repository layering.

2. Core user journey: search and delivery (2 minutes)
- Show a normal search.
- Show paginated results and file callback.
- Explain cache/session path from diagram.

3. Reliability and correctness deep dive (2-3 minutes)
- Open `docs/portfolio/engineering-issues-solved.md`.
- Walk through atomic quota reservation issue and fix.
- Walk through multi-db circuit breaker flow.

4. Operational controls (2 minutes)
- Demonstrate `/performance`, `/cache_stats`, `/dbstats`, `/dbinfo`.
- Show `/health` and `/metrics` endpoints.

5. Ingestion pipeline under load (1-2 minutes)
- Explain queue and overflow design from `handlers/channel.py`.
- Describe dynamic batch sizing and alert behavior.

6. Maintenance and lifecycle (1 minute)
- Explain daily maintenance and premium cleanup jobs.
- Explain graceful shutdown and handler/task cleanup strategy.

## Demo Narrative Tips

- Keep the narrative around problems solved under real constraints.
- Use concrete file references while presenting.
- Highlight tradeoffs and why each solution was chosen.

## Evidence Files To Keep Open

- `bot.py`
- `core/database/multi_pool.py`
- `repositories/user.py`
- `handlers/callbacks_handlers/file.py`
- `core/cache/invalidation.py`
- `handlers/channel.py`
- `handlers/manager.py`

## Optional Recording Cut

If you want a shorter 5-minute version:
1. 1 minute architecture.
2. 2 minutes search + delivery + quota correctness.
3. 2 minutes failover + operations.
