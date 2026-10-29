"""PH-013: liveness stays cheap; readiness pings bounded and single-flight."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from core.services.health_probes import ReadinessProbe, register_probe_routes


def fake_bot(*, split=False):
    mongodb_command = AsyncMock(return_value={"ok": 1})
    redis_ping = AsyncMock(return_value=True)
    state_ping = AsyncMock(return_value=True)
    database = SimpleNamespace(
        client=SimpleNamespace(admin=SimpleNamespace(command=mongodb_command))
    )
    cache = SimpleNamespace(
        redis=SimpleNamespace(ping=redis_ping),
        protected_state_enabled=split,
        state_redis=SimpleNamespace(ping=state_ping),
    )
    diagnostics = AsyncMock(return_value={
        "status": "healthy", "stats": {"files": {"total": 19}},
        "meta": {"components": {"users": {"ok": True}}}
    })
    bot = SimpleNamespace(
        db_pool=database, cache=cache, bot_username="test_bot",
        maintenance_service=SimpleNamespace(get_system_health_data=diagnostics),
    )
    return bot, mongodb_command, redis_ping, state_ping, diagnostics


@pytest.mark.asyncio
async def test_liveness_routes_do_not_ping_db_or_gather_stats():
    bot, mongo, redis, state, details = fake_bot()
    app = web.Application()
    register_probe_routes(app, bot)
    async with TestClient(TestServer(app)) as client:
        for path in ("/", "/health", "/live"):
            res = await client.get(path)
            assert res.status == 200
            data = await res.json()
            assert data == {"status": "alive", "bot_username": "test_bot"}
    mongo.assert_not_awaited()
    redis.assert_not_awaited()
    state.assert_not_awaited()
    details.assert_not_awaited()


@pytest.mark.asyncio
async def test_readiness_concurrent_checks_coalesce_and_cache():
    bot, mongo, redis, state, details = fake_bot()
    app = web.Application()
    register_probe_routes(app, bot)
    async with TestClient(TestServer(app)) as client:
        responses = await asyncio.gather(
            *[client.get("/ready") for _ in range(18)]
        )
        for res in responses:
            assert res.status == 200
            assert await res.json() == {
                "status": "ready",
                "dependencies": {"mongodb": "ok", "redis": "ok"}
            }
            assert res.headers["Cache-Control"] == "no-store"
        # No duplicate expensive probes from many concurrent HTTP requests.
        assert mongo.await_count == 1
        assert redis.await_count == 1
        state.assert_not_awaited()
        details.assert_not_awaited()
        again = await client.get("/ready")
        assert again.status == 200
        assert mongo.await_count == 1


@pytest.mark.asyncio
async def test_redis_failure_marks_not_ready_but_liveness_succeeds():
    bot, mongo, redis, state, details = fake_bot()
    redis.side_effect = ConnectionError("redis password must not be disclosed")
    app = web.Application()
    register_probe_routes(app, bot)
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/ready")
        assert resp.status == 503
        data = await resp.json()
        assert data["status"] == "not_ready"
        assert data["dependencies"] == {"mongodb": "ok", "redis": "unavailable"}
        assert "password" not in str(data)
        assert (await client.get("/health")).status == 200
    details.assert_not_awaited()


@pytest.mark.asyncio
async def test_timeout_is_bounded_and_recovery_uses_new_probe():
    bot, mongo, redis, state, details = fake_bot()
    async def slow_ping():
        await asyncio.sleep(1)
    redis.side_effect = slow_ping
    probe = ReadinessProbe(bot.db_pool, bot.cache, timeout=0.025,
                           healthy_ttl=0, failed_ttl=0)
    before = asyncio.get_running_loop().time()
    assert (await probe.check())["status"] == "not_ready"
    assert asyncio.get_running_loop().time() - before < 0.5
    redis.side_effect = None
    redis.return_value = True
    assert (await probe.check())["status"] == "ready"
    assert mongo.await_count == 2


@pytest.mark.asyncio
async def test_split_redis_protected_state_is_required():
    bot, mongo, redis, state, details = fake_bot(split=True)
    state.side_effect = ConnectionError("state down")
    app = web.Application()
    register_probe_routes(app, bot)
    async with TestClient(TestServer(app)) as client:
        res = await client.get("/ready")
        assert res.status == 503
        assert await res.json() == {
            "status": "not_ready",
            "dependencies": {
                "mongodb": "ok", "redis": "ok", "redis_state": "unavailable"
            },
        }
    assert mongo.await_count == 1
    assert redis.await_count == 1
    assert state.await_count == 1
    details.assert_not_awaited()


@pytest.mark.asyncio
async def test_heavy_legacy_report_is_explicit_only():
    bot, mongo, redis, state, details = fake_bot()
    app = web.Application()
    register_probe_routes(app, bot)
    async with TestClient(TestServer(app)) as client:
        for path in ("/health?details=1", "/health/details"):
            response = await client.get(path)
            assert response.status == 200
            report = await response.json()
            assert report["stats"]["files"]["total"] == 19
            assert report["meta"]["components"]["users"]["ok"] is True
    assert details.await_count == 2
    mongo.assert_not_awaited()
    redis.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_diagnostics_failure_returns_safe_503():
    bot, *_other, details = fake_bot()
    details.side_effect = RuntimeError("secret mongodb://user:password@example")
    app = web.Application()
    register_probe_routes(app, bot)
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/health/details")
        assert response.status == 503
        assert await response.json() == {"status": "unhealthy"}


def test_docker_liveness_does_not_use_dependency_readiness():
    root = Path(__file__).resolve().parents[1]
    for path in ("Dockerfile", "docker-compose.yml",
                 "docker-compose.staging.yml"):
        text = (root / path).read_text()
        assert "/health" in text
        assert "/ready" not in text
    bot = (root / "bot.py").read_text()
    assert "register_probe_routes(app, self)" in bot
    assert "app.router.add_get('/metrics', performance_metrics)" in bot
    assert "app.router.add_get('/performance', performance_metrics)" in bot
