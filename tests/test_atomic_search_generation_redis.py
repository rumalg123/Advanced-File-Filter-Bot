"""PH-011: real Redis atomic generation / reset semantics, localhost CI only."""
import asyncio
import os
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest

from core.cache.redis_cache import CacheManager
from core.cache.routed_cache import RoutedCacheManager
from core.cache.invalidation import CacheInvalidator
from repositories.media import MediaRepository
from urllib.parse import urlsplit


def is_local(uri: str, port: int) -> bool:
    parsed = urlsplit(uri)
    return (parsed.scheme == "redis"
            and (parsed.hostname or "").lower() in ("127.0.0.1", "localhost")
            and parsed.port == port
            and parsed.username is None and parsed.password is None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_redis_concurrent_increment_and_nonexpiring_generation():
    uri = os.getenv("TEST_REDIS_CACHE_URI")
    if not uri:
        pytest.skip("Requires local CI Redis")
    assert is_local(uri, 6379)
    cache = CacheManager(uri)
    await cache.initialize()
    key = f"cache:search:version:ph011:{uuid4().hex}"
    try:
        before = await cache.ensure_search_generation(key, 555000)
        assert before == 555000
        assert await cache.redis.ttl(key) == -1
        # Simulate a legacy version key that still has a 1-year expiration.
        await cache.redis.expire(key, 60)
        assert await cache.ensure_search_generation(key, 888000) == 555000
        assert await cache.redis.ttl(key) == -1
        versions = await asyncio.gather(*(
            cache.advance_search_generation(key, 777000) for _ in range(100)
        ))
        assert all(isinstance(v, int) for v in versions)
        assert len(set(versions)) == 100
        assert min(versions) == 555001
        assert max(versions) == 555100
        assert await cache.ensure_search_generation(key, 991000) == 555100

        # Invalid counter cannot be silently deleted and turned into v1.
        await cache.redis.set(key, b"not-an-integer")
        assert await cache.ensure_search_generation(key, 123456) is None
        assert await cache.advance_search_generation(key, 123456) is None
        assert await cache.redis.get(key) == b"not-an-integer"

        # A reset/missing value gets a fresh unpredictable generation.
        await cache.redis.delete(key)
        assert await cache.ensure_search_generation(key, 991111) == 991111
        assert await cache.advance_search_generation(key, 222222) == 991112
        assert await cache.redis.ttl(key) == -1
    finally:
        await cache.redis.delete(key)
        await cache.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_split_redis_generation_stays_on_protected_instance_and_cache_misses_after_reset():
    disposable_uri = os.getenv("TEST_REDIS_CACHE_URI")
    state_uri = os.getenv("TEST_REDIS_STATE_URI")
    if not disposable_uri or not state_uri:
        pytest.skip("Requires both local CI Redis services")
    assert is_local(disposable_uri, 6379)
    assert is_local(state_uri, 6380)
    disposable = CacheManager(disposable_uri)
    protected = CacheManager(state_uri)
    routed = RoutedCacheManager(disposable, protected)
    await routed.initialize()
    marker = f"cache:search:version:ph011:{uuid4().hex}"
    query = f"doctor x mafia {uuid4().hex}"
    repo = MediaRepository(None, routed)
    repo.cache_invalidator.SEARCH_CACHE_VERSION_KEY = marker
    repo.count = AsyncMock(return_value=0)
    repo.find_many = AsyncMock(return_value=[])
    try:
        assert await repo.search_files(query) == ([], 0, 0)
        first_generation = await repo.cache_invalidator.get_search_cache_version()
        assert await protected.redis.exists(marker) == 1
        assert await disposable.redis.exists(marker) == 0
        assert repo.count.await_count == 1

        # The current search is served from cached results before state loss.
        assert await repo.search_files(query) == ([], 0, 0)
        assert repo.count.await_count == 1

        # Lose just the generation key (not a FLUSHDB, not user sessions).
        await protected.redis.delete(marker)
        assert await repo.search_files(query) == ([], 0, 0)
        second_generation = await repo.cache_invalidator.get_search_cache_version()
        assert second_generation != first_generation
        assert repo.count.await_count == 2
    finally:
        await protected.redis.delete(marker)
        # Keep the CI Redis test services isolated; only this query's cached
        # page keys were written, and they are short-lived.
        await routed.close()
