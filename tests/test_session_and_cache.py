import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from core.cache.config import CacheKeyGenerator
from core.cache.invalidation import CacheInvalidator
from core.cache.redis_cache import cache_premium_status
from core.session.manager import SessionType, UnifiedSessionManager


class MemoryCache:
    def __init__(self):
        self.values = {}
        self.deleted = []
        self.set_calls = []

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, expire=None):
        self.values[key] = value
        self.set_calls.append((key, value, expire))
        return True

    async def delete(self, key):
        self.deleted.append(key)
        self.values.pop(key, None)
        return True


@pytest.mark.asyncio
async def test_session_lifecycle_does_not_delete_live_sessions():
    cache = MemoryCache()
    manager = UnifiedSessionManager(cache)
    session_id = await manager.create_session(42, SessionType.SEARCH, {"query": "matrix"})

    task = asyncio.create_task(manager._cleanup_expired_sessions())
    await asyncio.sleep(0)

    session = await manager.get_session(42, SessionType.SEARCH, session_id)
    assert session is not None
    assert session.data["query"] == "matrix"

    manager._shutdown_event.set()
    await task


@pytest.mark.asyncio
async def test_premium_invalidator_deletes_the_dedicated_key():
    cache = MemoryCache()
    invalidator = CacheInvalidator(cache)

    assert await invalidator.invalidate_premium_status(99)
    assert cache.deleted == [CacheKeyGenerator.premium_status(99)]


@pytest.mark.asyncio
async def test_positive_premium_cache_never_outlives_subscription():
    cache = MemoryCache()

    class PremiumChecker:
        def __init__(self):
            self.cache = cache

        @cache_premium_status(ttl=600)
        async def check(self, user):
            return True, "active"

    user = SimpleNamespace(
        id=7,
        premium_expiry_date=datetime.now(UTC) + timedelta(seconds=30)
    )
    assert (await PremiumChecker().check(user))[0] is True
    assert 0 < cache.set_calls[-1][2] <= 30
