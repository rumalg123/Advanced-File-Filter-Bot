"""PH-023: rate limiter does not fail open under unsplit Redis loss."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.utils.rate_limiter import RateLimitConfig, RateLimiter


def broken_cache(*, protected=False, raises=False):
    async def ttl(_key):
        if raises:
            raise ConnectionError("redis unavailable")
        return -1

    async def increment_with_expiry(_key, _amount, _seconds):
        if raises:
            raise ConnectionError("redis unavailable")
        return None

    return SimpleNamespace(
        ttl=ttl,
        increment_with_expiry=increment_with_expiry,
        protected_state_enabled=protected,
    )


@pytest.mark.parametrize("raises", [True, False])
@pytest.mark.asyncio
async def test_redis_outage_bounded_local_window_and_cooldown(monkeypatch, raises):
    clock = [100.0]
    monkeypatch.setattr("core.utils.rate_limiter.time.monotonic", lambda: clock[0])
    limiter = RateLimiter(broken_cache(raises=raises))
    limiter.configs["search"] = RateLimitConfig(
        max_requests=2, time_window=10, cooldown_time=20
    )
    assert await limiter.check_rate_limit(42, "search") == (True, None)
    assert await limiter.check_rate_limit(42, "search") == (True, None)
    assert await limiter.check_rate_limit(42, "search") == (False, 20)
    clock[0] = 108.0
    assert await limiter.check_rate_limit(42, "search") == (False, 12)
    clock[0] = 120.1
    assert await limiter.check_rate_limit(42, "search") == (True, None)
    assert limiter.local_fallback_metrics()["fallback_events"] == 5


@pytest.mark.asyncio
async def test_outage_fallback_concurrency_never_overadmits():
    limiter = RateLimiter(broken_cache())
    limiter.configs["file_request"] = RateLimitConfig(
        max_requests=5, time_window=120
    )
    results = await asyncio.gather(*[
        limiter.check_rate_limit(27, "file_request") for _ in range(50)
    ])
    assert sum(allowed for allowed, _ in results) == 5
    assert limiter.local_fallback_metrics()["entries"] == 1


@pytest.mark.asyncio
async def test_outage_independent_users_actions_and_protected_state():
    limiter = RateLimiter(broken_cache())
    limiter.configs["search"] = RateLimitConfig(1, 100)
    limiter.configs["file_request"] = RateLimitConfig(1, 100)
    assert await limiter.check_rate_limit(1, "search") == (True, None)
    assert await limiter.check_rate_limit(1, "search") == (False, 100)
    assert await limiter.check_rate_limit(2, "search") == (True, None)
    assert await limiter.check_rate_limit(1, "file_request") == (True, None)
    protected = RateLimiter(broken_cache(protected=True))
    assert await protected.check_rate_limit(1, "search") == (
        False, protected.configs["search"].cooldown_time
    )
    assert protected.local_fallback_metrics()["entries"] == 0


@pytest.mark.asyncio
async def test_outage_local_memory_capacity_fails_closed(monkeypatch):
    limiter = RateLimiter(broken_cache())
    limiter.LOCAL_MAX_ENTRIES = 3
    limiter.configs["search"] = RateLimitConfig(
        max_requests=1, time_window=100, cooldown_time=10
    )
    for user in range(3):
        assert await limiter.check_rate_limit(user, "search") == (True, None)
    # Cannot drop the first active user entry just to admit a fourth one.
    assert await limiter.check_rate_limit(3, "search") == (False, 10)
    assert await limiter.check_rate_limit(0, "search") == (False, 100)
    assert limiter.local_fallback_metrics()["capacity_denials"] == 1
    assert limiter.local_fallback_metrics()["entries"] == 3

    clock = [1000.0]
    monkeypatch.setattr("core.utils.rate_limiter.time.monotonic", lambda: clock[0])
    # Recreate a fresh limiter under a deterministic clock.
    limiter = RateLimiter(broken_cache())
    limiter.LOCAL_MAX_ENTRIES = 1
    limiter.configs["search"] = RateLimitConfig(2, 10, 10)
    assert (await limiter.check_rate_limit(1, "search"))[0]
    clock[0] = 1011.0
    assert (await limiter.check_rate_limit(2, "search"))[0]
    assert limiter.local_fallback_metrics()["entries"] == 1


@pytest.mark.asyncio
async def test_healthy_redis_path_is_unchanged_and_outage_recovery_uses_redis():
    cache = SimpleNamespace(
        protected_state_enabled=False,
        ttl=AsyncMock(return_value=-2),
        increment_with_expiry=AsyncMock(side_effect=[1, 2, 3]),
        set=AsyncMock(return_value=True),
    )
    limiter = RateLimiter(cache)
    limiter.configs["search"] = RateLimitConfig(2, 60, 10)
    assert await limiter.check_rate_limit(55, "search") == (True, None)
    assert await limiter.check_rate_limit(55, "search") == (True, None)
    assert await limiter.check_rate_limit(55, "search") == (False, 60)
    cache.set.assert_awaited_once()
    assert limiter.local_fallback_metrics()["fallback_events"] == 0
    cache.increment_with_expiry.side_effect = [None, 1]
    assert await limiter.check_rate_limit(56, "search") == (True, None)
    assert await limiter.check_rate_limit(56, "search") == (True, None)
    assert limiter.local_fallback_metrics()["fallback_events"] == 1


@pytest.mark.asyncio
async def test_reset_clears_local_and_remote_invalidation():
    limiter = RateLimiter(broken_cache())
    limiter.cache_invalidator.invalidate_rate_limit = AsyncMock()
    assert (await limiter.check_rate_limit(12, "search"))[0]
    assert limiter.local_fallback_metrics()["entries"] == 1
    await limiter.reset_rate_limit(12, "search")
    assert limiter.local_fallback_metrics()["entries"] == 0
    limiter.cache_invalidator.invalidate_rate_limit.assert_awaited_once_with(
        12, "search"
    )
