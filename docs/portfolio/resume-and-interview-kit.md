# Resume and Interview Kit

## Resume Bullets (Ready to Use)

- Architected and shipped a production-style asynchronous Telegram media platform in Python, with layered handlers/services/repositories and centralized lifecycle management.
- Built a multi-database write routing subsystem with circuit breaker protection, real-time capacity checks, and manual/automatic failover controls.
- Implemented Redis-backed rate limiting, session management, and cache invalidation strategies, including versioned search cache keys for efficient global invalidation.
- Eliminated quota race conditions in bulk file delivery by introducing atomic quota reservation and compensating quota release logic.
- Improved indexing throughput by replacing N+1 duplicate checks with batch duplicate detection and bulk persistence paths.
- Designed queue backpressure controls for channel ingestion using bounded queues, overflow buffering, dynamic batch sizing, and operational alerting.
- Developed resilient Telegram API integration with FloodWait-aware retry behavior and semaphore-based domain concurrency control.
- Added operations tooling for runtime health, metrics, broadcast control, cache analysis/cleanup, and secure update/rollback workflows.

## 30-Second Pitch

I built an advanced Telegram media indexing and search platform as a single-developer project. The system handles ingestion, retrieval, quota enforcement, rate limiting, and admin operations with production-oriented reliability patterns like circuit breakers, retries, and graceful shutdown. The codebase is structured in clean service and repository layers and is deployable with Docker.

## 60-Second Pitch

This project started as a media search bot but evolved into a backend system design exercise. It includes asynchronous message handling, Redis-backed caching and session state, MongoDB persistence, and optional multi-database write failover. I focused on correctness and resilience: atomic quota reservation for bulk sends, cache versioning for scalable invalidation, and centralized Telegram API retry/flood control. I also added operational features like health/metrics endpoints, maintenance jobs, broadcast orchestration, and secure update/rollback support.

## 120-Second Deep-Dive Pitch

The architecture is intentionally layered: handlers parse Telegram updates, services enforce business policy, repositories encapsulate persistence and cache behavior, and cross-cutting modules provide concurrency, session, and error handling. For scale and stability, I implemented a multi-database manager that tracks capacity and health with circuit breaker states and smart write-database selection. On the data correctness side, bulk file delivery uses atomic quota reservation to prevent concurrent oversubscription, then releases unused quota if sends fail. Search caching uses versioned keys and throttled global invalidation to avoid expensive wildcard deletes and cache stampedes. Channel indexing uses bounded queues and overflow handling to absorb bursts without blocking the main update pipeline. The result is not just feature-rich; it is engineered for predictable behavior under load and failure.

## Interview Walkthrough Topics

- Architecture layering and dependency wiring (`bot.py`, `core/services/*`, `repositories/*`).
- Reliability strategy (retry wrappers, circuit breakers, fallback paths).
- Data consistency under concurrency (quota reservation, guarded updates).
- Cache design and invalidation tradeoffs.
- Operational controls and observability.

## High-Value Technical Tradeoffs To Discuss

- Why versioned invalidation was preferred over mass key deletion.
- Why circuit breaker state is per database instance.
- Why broadcast state is persisted in Redis and not memory-only.
- Why quota is reserved before send-all instead of counted afterward.
- Why dynamic queue batching is tied to queue depth.

## Quick Q and A Practice

- Q: How do you prevent race conditions in bulk file send?
  A: Atomic quota reservation with guarded `find_one_and_update`, plus unused quota release.

- Q: How do you handle partial database failures?
  A: Per-db circuit breaker with OPEN/HALF_OPEN/CLOSED transitions and active pool routing.

- Q: How do you avoid cache stampedes on global invalidation?
  A: Search cache version bump and throttled invalidation calls.

- Q: What happens on restart during long broadcast?
  A: Broadcast state is persisted; recovery checks detect stale active state and allow controlled reset.
