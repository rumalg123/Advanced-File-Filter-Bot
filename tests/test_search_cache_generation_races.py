"""PH-011: stale generation reads must never be served after detected writes."""
from unittest.mock import AsyncMock
import pytest

from core.database.errors import SearchBackendUnavailableError
from repositories.media import MediaRepository


class GenerationCache:
    def __init__(self):
        self.version = 90
        self.data = {}
        self.flip_on_cache_hit = False
        self.flip_on_set = False

    async def ensure_search_generation(self, key, initial):
        return self.version

    async def advance_search_generation(self, key, initial):
        self.version += 1
        return self.version

    async def get(self, key):
        item = self.data.get(key)
        if item is not None and self.flip_on_cache_hit:
            self.version += 1
            self.flip_on_cache_hit = False
        return item

    async def set(self, key, value, expire=None):
        self.data[key] = value
        if self.flip_on_set:
            self.version += 1
            self.flip_on_set = False
        return True

    async def delete(self, key):
        self.data.pop(key, None)
        return True


def repository(cache):
    repo = MediaRepository(None, cache)
    repo.find_many = AsyncMock(return_value=[])
    repo.count = AsyncMock(return_value=0)
    return repo


@pytest.mark.asyncio
async def test_generation_change_during_count_discards_stale_result_and_retries():
    cache = GenerationCache()
    repo = repository(cache)
    calls = 0

    async def count(_filter, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            await repo.cache_invalidator.increment_search_cache_version()
        return 0

    repo.count.side_effect = count
    assert await repo.search_files("doctor x") == ([], 0, 0)
    assert calls == 2
    # The first (old generation) result never entered the cache.
    assert len(cache.data) == 1
    assert any(f":v{cache.version}" in key for key in cache.data)


@pytest.mark.asyncio
async def test_generation_change_during_cached_hit_forces_new_db_query():
    cache = GenerationCache()
    repo = repository(cache)
    assert await repo.search_files("doctor x mafia") == ([], 0, 0)
    assert repo.count.await_count == 1

    cache.flip_on_cache_hit = True
    assert await repo.search_files("doctor x mafia") == ([], 0, 0)
    assert repo.count.await_count == 2
    assert any(f":v{cache.version}" in key for key in cache.data)


@pytest.mark.asyncio
async def test_generation_change_during_cache_set_retries():
    cache = GenerationCache()
    cache.flip_on_set = True
    repo = repository(cache)
    assert await repo.search_files("doctor x") == ([], 0, 0)
    assert repo.count.await_count == 2
    assert any(f":v{cache.version}" in key for key in cache.data)


@pytest.mark.asyncio
async def test_continuous_mutations_fail_safely_after_bounded_attempts():
    cache = GenerationCache()
    repo = repository(cache)

    async def count(_filter, **kwargs):
        await repo.cache_invalidator.increment_search_cache_version()
        return 0

    repo.count.side_effect = count
    with pytest.raises(SearchBackendUnavailableError, match="changed repeatedly"):
        await repo.search_files("doctor x")
    assert repo.count.await_count == 3
    assert cache.data == {}


@pytest.mark.asyncio
async def test_generation_unavailable_prevents_cache_hit_or_database_query():
    cache = GenerationCache()
    repo = repository(cache)
    cache.ensure_search_generation = AsyncMock(return_value=None)
    with pytest.raises(SearchBackendUnavailableError, match="generation"):
        await repo.search_files("doctor x")
    repo.count.assert_not_awaited()
