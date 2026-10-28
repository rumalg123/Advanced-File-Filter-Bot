"""PH-003: protected operational Redis and safe failure handling.

All tests are self-contained and do not connect to production Redis.
"""
import fnmatch
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.cache.config import CacheKeyGenerator
from core.cache.errors import OperationalStateUnavailableError
from core.cache.invalidation import CacheInvalidator
from core.cache.redis_cache import CacheManager
from core.cache.routed_cache import RoutedCacheManager
from core.database.errors import SearchBackendUnavailableError
from core.services.search_results import SearchResultsService
from core.session.manager import SessionType, UnifiedSessionManager
from core.utils.pagination import create_search_query_reference
from core.utils.rate_limiter import RateLimiter
from repositories.media import MediaRepository


class FakeBackend:
    def __init__(self, host: str, *, set_success=True, initialized=True):
        self.redis_url = f"redis://{host}:6379/0"
        self.redis = SimpleNamespace()
        self.data = {}
        self.calls = []
        self.set_success = set_success
        self.initialized = initialized
        self.closed = False
        self.increment_succeeds = True
        self.ensure_succeeds = True

    async def initialize(self):
        if not self.initialized:
            raise ConnectionError("State Redis is down")
        self.calls.append(("initialize",))

    async def close(self):
        self.closed = True

    async def get(self, key):
        self.calls.append(("get", key))
        return self.data.get(key)

    async def set(self, key, value, expire=None):
        self.calls.append(("set", key, expire))
        if not self.set_success:
            return False
        self.data[key] = value
        return True

    async def delete(self, key):
        self.calls.append(("delete", key))
        self.data.pop(key, None)
        return True

    async def exists(self, key):
        return key in self.data

    async def mget(self, keys):
        self.calls.append(("mget", tuple(keys)))
        return [self.data.get(key) for key in keys]

    async def increment(self, key, amount=1):
        self.calls.append(("increment", key))
        if not self.increment_succeeds:
            return None
        self.data[key] = int(self.data.get(key, 0)) + amount
        return self.data[key]

    async def ensure_counter_initialized(self, key, initial):
        self.calls.append(("initialize_counter", key))
        if not self.ensure_succeeds:
            return None
        self.data.setdefault(key, int(initial))
        return self.data[key]

    async def increment_with_expiry(self, key, amount, seconds):
        if not self.increment_succeeds:
            return None
        return await self.increment(key, amount)

    async def ttl(self, key):
        return 60 if key in self.data else -2

    async def expire(self, key, seconds):
        return key in self.data

    async def delete_if_value(self, key, expected_value):
        if self.data.get(key) == expected_value:
            self.data.pop(key)
            return True
        return False

    async def delete_pattern(self, pattern):
        self.calls.append(("delete_pattern", pattern))
        keys = [k for k in self.data if fnmatch.fnmatch(k, pattern)]
        for k in keys:
            self.data.pop(k)
        return len(keys)

    async def zadd(self, key, score, member):
        self.calls.append(("zadd", key))
        return True

    async def zincrby(self, key, amount, member):
        self.calls.append(("zincrby", key))
        return 1.0

    async def zrevrange(self, key, start=0, end=-1, with_scores=False):
        self.calls.append(("zrevrange", key))
        return []

    async def get_cache_stats(self):
        return {
            "redis_info": {"used_memory": 123, "evicted_keys": 0,
                           "maxmemory_policy": "noeviction"},
            "connection_info": {"is_connected": True},
        }


def routed(cache=None, state=None):
    cache = cache or FakeBackend("cache")
    state = state or FakeBackend("protected")
    return RoutedCacheManager(cache, state), cache, state


@pytest.mark.asyncio
async def test_key_families_route_to_independent_backends():
    manager, disposable, protected = routed()

    for key in (
        "rate_limit:42:search",
        "rate_limit:42:search:cooldown",
        "session:search:42",
        "search_results_42_abcd1234",
        "checksub_session:abc",
        "deeplink_42_abc",
        "deleteall_pending:42",
        "broadcast:state",
        "last_counter_reset_date",
        "recent_settings_edit:42",
        "cache:search:version",
    ):
        assert manager.backend_for_key(key) is protected, key
        assert await manager.set(key, "protected", expire=60)
        assert key in protected.data and key not in disposable.data
        assert await manager.get(key) == "protected"

    for key in (
        "search:doctor x:None:0:10:True:algo2:v1",
        "media:unique-file",
        "user:42",
        "premium_status:42",
        "query_cooccurrence:doctor x",
    ):
        assert manager.backend_for_key(key) is disposable, key
        assert await manager.set(key, "cache", expire=60)
        assert key in disposable.data and key not in protected.data

    assert manager.state_redis is protected.redis
    assert manager.redis is disposable.redis


@pytest.mark.asyncio
async def test_mget_keeps_key_order_and_pattern_deletion_never_spills():
    manager, cache, state = routed()
    for key, val in (
        ("media:a", "A"), ("rate_limit:42:search", "B"),
        ("session:search:42", "C"), ("search:query", "D")
    ):
        await manager.set(key, val, expire=60)
    assert await manager.mget([
        "session:search:42", "media:a", "missing",
        "rate_limit:42:search", "search:query"
    ]) == ["C", "A", None, "B", "D"]

    assert await manager.delete_pattern("rate_limit:*") == 1
    assert "media:a" in cache.data and "session:search:42" in state.data
    assert await manager.delete_pattern("search:*") == 1
    assert "media:a" in cache.data and "session:search:42" in state.data
    assert await manager.delete_pattern("*") == 2
    assert not cache.data and not state.data


@pytest.mark.asyncio
async def test_separate_redis_database_number_is_not_isolation():
    with pytest.raises(ValueError, match="another Redis instance"):
        RoutedCacheManager(
            FakeBackend("redis"),
            SimpleNamespace(redis_url="redis://redis:6379/15"),
        )


@pytest.mark.asyncio
async def test_state_connection_failure_never_falls_back_to_disposable_cache():
    manager, cache, state = routed(state=FakeBackend("protected", initialized=False))
    with pytest.raises(ConnectionError, match="State Redis is down"):
        await manager.initialize()
    assert cache.closed
    assert "rate_limit:42:search" not in cache.data


@pytest.mark.asyncio
async def test_protected_generation_initializes_randomly_and_never_reuses_v1(monkeypatch):
    manager, cache, state = routed()
    values = iter((101, 202))
    monkeypatch.setattr("core.cache.invalidation.secrets.randbits", lambda _: next(values))

    invalidator = CacheInvalidator(manager)
    first = await invalidator.get_search_cache_version()
    assert first == 102
    assert await invalidator.get_search_cache_version() == first

    # A state instance restored without its counter must never resurrect v1.
    state.data.clear()
    after_reset = await invalidator.get_search_cache_version()
    assert after_reset == 203 and after_reset != first
    assert cache.data == {}
    assert await invalidator.increment_search_cache_version() == 204


@pytest.mark.asyncio
async def test_protected_counter_outage_prevents_search_without_cache_poisoning():
    manager, cache, state = routed()
    state.ensure_succeeds = False
    repo = MediaRepository(None, manager)
    repo.count = AsyncMock()

    with pytest.raises(SearchBackendUnavailableError):
        await repo.search_files("doctor x")

    repo.count.assert_not_awaited()
    assert cache.data == {}


@pytest.mark.asyncio
async def test_protected_rate_limiter_denies_when_state_redis_cannot_write():
    manager, _, state = routed()
    state.increment_succeeds = False
    allowed, seconds = await RateLimiter(manager).check_rate_limit(42, "search")
    assert not allowed
    assert seconds is not None and seconds > 0


@pytest.mark.asyncio
async def test_legacy_rate_limiter_fallback_unchanged_without_split():
    cache = FakeBackend("cache")
    cache.increment_succeeds = False
    allowed, _ = await RateLimiter(cache).check_rate_limit(42, "search")
    assert allowed


@pytest.mark.asyncio
async def test_session_creation_rejects_failed_state_write():
    manager, _, state = routed(state=FakeBackend("protected", set_success=False))
    sessions = UnifiedSessionManager(manager)
    with pytest.raises(RuntimeError, match="storage unavailable"):
        await sessions.create_session(42, SessionType.SEARCH, {"query": "doctor x"})


@pytest.mark.asyncio
async def test_search_reference_and_search_buttons_never_succeed_without_state():
    manager, _, state = routed(state=FakeBackend("protected", set_success=False))
    with pytest.raises(OperationalStateUnavailableError):
        await create_search_query_reference(manager, "doctor x", 42)

    service = SearchResultsService(manager, SimpleNamespace())
    file = SimpleNamespace(
        file_unique_id="unique-1", file_id="file-1",
        file_ref="ref-1", file_name="Doctor X", file_size=100,
        file_type=SimpleNamespace(value="video")
    )
    with pytest.raises(OperationalStateUnavailableError):
        await service.send_results(
            client=None, message=None, files=[file],
            query="doctor x", total=1, page_size=10, user_id=42,
            is_private=True,
        )


@pytest.mark.asyncio
async def test_pagination_not_updated_if_new_state_session_fails(monkeypatch):
    from handlers.callbacks_handlers.pagination import PaginationCallbackHandler
    import handlers.callbacks_handlers.pagination as callback_module

    manager, _, state = routed(state=FakeBackend("protected", set_success=False))
    media_file = SimpleNamespace(
        file_unique_id="unique", file_id="file", file_ref="ref",
        file_name="Doctor X", file_size=123,
        file_type=SimpleNamespace(value="video")
    )
    handler = PaginationCallbackHandler(SimpleNamespace(
        cache=manager,
        file_service=SimpleNamespace(search_files_with_access_check=AsyncMock(
            return_value=([media_file], 0, 1, True, None)
        )),
        config=SimpleNamespace(MAX_BTN_SIZE=10),
    ))
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        data="anything", answer=AsyncMock(),
    )
    monkeypatch.setattr(
        callback_module.PaginationHelper,
        "parse_callback_data",
        lambda _: {"query": "doctor x", "offset": 0, "total": 1, "user_id": 42},
    )
    monkeypatch.setattr(callback_module, "is_private_chat", lambda _: True)
    await handler.handle_search_pagination(None, callback)
    callback.answer.assert_awaited_once()
    assert "temporarily" in callback.answer.await_args.args[0].lower()


def test_protected_state_redis_config_is_opt_in():
    from config.settings import RedisConfig
    import os
    from pathlib import Path

    assert "maxmemory-policy noeviction" in Path("redis-state.conf").read_text()
    assert "maxmemory-policy allkeys-lru" in Path("redis.conf").read_text()
    compose = Path("docker-compose.yml").read_text()
    assert 'profiles: ["protected-state"]' in compose
    assert "REDIS_STATE_URI=" in compose
    assert "internal: true" in compose
    assert "REDIS_STATE_URI" not in (os.environ.get("REDIS_STATE_URI") or "")
