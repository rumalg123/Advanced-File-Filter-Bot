"""A cached decision cannot override the current user's flag and expiry."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from ban_support import Cache
from core.cache.config import CacheKeyGenerator
from core.cache.redis_cache import cache_premium_status
from core.utils.validators import is_premium_valid


@pytest.mark.asyncio
@pytest.mark.parametrize('flag,days,cached', [
    (True, -1, True), (False, 1, True), (True, 1, False),
])
async def test_stale_premium_cache_cannot_override_current_entitlement(flag, days, cached):
    cache = Cache()
    cache.values[CacheKeyGenerator.premium_status(42)] = [cached, 'old decision']
    calls = []

    class Checker:
        @cache_premium_status()
        async def check(self, user):
            calls.append(user.id)
            return is_premium_valid(user.is_premium, user.premium_expiry_date), 'current decision'

    checker = Checker()
    checker.cache = cache
    user = SimpleNamespace(id=42, is_premium=flag,
                           premium_expiry_date=datetime.now(UTC)+timedelta(days=days))
    assert await checker.check(user) == (flag and days > 0, 'current decision')
    assert calls == [42]


@pytest.mark.asyncio
@pytest.mark.parametrize('cached', [(True,), ['true', 'active'], {'active': True}, 'active', 42])
async def test_malformed_premium_cache_is_recomputed(cached):
    cache = Cache()
    cache.values[CacheKeyGenerator.premium_status(42)] = cached

    class Checker:
        @cache_premium_status()
        async def check(self, user):
            return True, 'current decision'

    checker = Checker()
    checker.cache = cache
    user = SimpleNamespace(id=42, is_premium=True,
                           premium_expiry_date=datetime.now(UTC)+timedelta(days=1))
    assert await checker.check(user) == (True, 'current decision')
