"""PH-013: cheap liveness and bounded, cached dependency readiness.

Do not add database statistics to probes: their purpose is to answer
quickly under partial outages, not to gather operational diagnostics.
Existing /metrics and /performance collection remains unchanged.
"""
import asyncio
import time
from typing import Any

from aiohttp import web


class ReadinessProbe:
    """Single-flight bounded MongoDB/Redis pings, including optional state Redis."""

    def __init__(self, db_pool: Any, cache: Any, *, timeout: float = 0.75,
                 healthy_ttl: float = 5.0, failed_ttl: float = 2.0,
                 multi_db_manager: Any = None):
        self.db_pool = db_pool
        self.cache = cache
        self.multi_db_manager = multi_db_manager
        self.timeout = timeout
        self.healthy_ttl = healthy_ttl
        self.failed_ttl = failed_ttl
        self._lock = asyncio.Lock()
        self._cached = None
        self._expires_at = 0.0

    async def _ping_mongodb(self, pool) -> bool:
        # Avoid execute_with_retry and dbStats. This is one bounded ping.
        try:
            client = pool.client
            await asyncio.wait_for(client.admin.command("ping"), self.timeout)
            return True
        except Exception:
            return False

    async def _ping_redis(self, redis_client: Any) -> bool:
        if redis_client is None:
            return False
        try:
            return bool(await asyncio.wait_for(redis_client.ping(), self.timeout))
        except Exception:
            return False

    async def _measure(self) -> dict:
        dependencies = {
            "mongodb": self._ping_mongodb(self.db_pool),
            "redis": self._ping_redis(self.cache.redis),
        }
        if self.multi_db_manager is not None:
            sources = self.multi_db_manager.databases
            if not sources:
                dependencies['mongodb_media'] = self._ping_mongodb(None)
            for index, source in enumerate(sources, 1):
                pool = source.pool if source.is_active else None
                dependencies[f'mongodb_media_{index}'] = self._ping_mongodb(pool)
        if getattr(self.cache, "protected_state_enabled", False):
            dependencies["redis_state"] = self._ping_redis(
                getattr(self.cache, "state_redis", None)
            )
        names = list(dependencies)
        results = await asyncio.gather(*dependencies.values(), return_exceptions=True)
        states = {
            name: ("ok" if value is True else "unavailable")
            for name, value in zip(names, results)
        }
        ready = all(value == "ok" for value in states.values())
        return {"status": "ready" if ready else "not_ready",
                "dependencies": states}

    async def check(self) -> dict:
        """Cache checks and coalesce concurrent HTTP requests into one probe."""
        now = time.monotonic()
        if self._cached is not None and now < self._expires_at:
            return dict(self._cached)
        async with self._lock:
            now = time.monotonic()
            if self._cached is not None and now < self._expires_at:
                return dict(self._cached)
            measured = await self._measure()
            self._cached = measured
            ttl = self.healthy_ttl if measured["status"] == "ready" else self.failed_ttl
            self._expires_at = time.monotonic() + ttl
            return dict(measured)


def register_probe_routes(app: web.Application, bot: Any) -> None:
    """Attach cheap liveness, bounded readiness and legacy detailed stats.

    / and /health remain the standard Docker liveness paths, no auth or
    bind/CORS changes. ?details=1 gives old /health response on demand.
    """

    probe = ReadinessProbe(bot.db_pool, bot.cache,
                           multi_db_manager=getattr(bot, 'multi_db_manager', None))
    app["readiness_probe"] = probe

    async def detailed_health() -> web.Response:
        try:
            report = await bot.maintenance_service.get_system_health_data()
            state = report.get("status", "unhealthy")
            return web.json_response({
                "status": state,
                "bot_username": bot.bot_username,
                "stats": report.get("stats", {}),
                "meta": report.get("meta", {}),
            }, status=200 if state in ("healthy", "degraded") else 503)
        except Exception:
            # No exception text/credentials in HTTP error response.
            return web.json_response({"status": "unhealthy"}, status=503)

    async def health(request: web.Request) -> web.Response:
        if request.query.get("details") == "1":
            return await detailed_health()
        return web.json_response({
            "status": "alive",
            "bot_username": bot.bot_username,
        })

    async def ready(request: web.Request) -> web.Response:
        result = await probe.check()
        status = 200 if result["status"] == "ready" else 503
        return web.json_response(result, status=status,
                                 headers={"Cache-Control": "no-store"})

    async def health_details(request: web.Request) -> web.Response:
        return await detailed_health()

    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_get("/live", health)
    app.router.add_get("/ready", ready)
    app.router.add_get("/health/details", health_details)
