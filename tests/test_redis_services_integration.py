"""PH-008: real Redis integration tests using two LOCAL ephemeral CI instances.

TEST_REDIS_CACHE_URI and TEST_REDIS_STATE_URI are intentionally distinct.
Tests never connect to the bot's REDIS_URI/REDIS_STATE_URI or production.
"""
import os
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from core.cache.invalidation import CacheInvalidator
from core.cache.redis_cache import CacheManager
from core.cache.routed_cache import RoutedCacheManager


def _localhost_test_uri(name, *, expected_port):
    uri = os.environ.get(name)
    if not uri:
        pytest.skip(f"{name} not supplied (local Redis CI service is absent)")
    parsed = urlsplit(uri)
    if (
        parsed.scheme != "redis" or
        (parsed.hostname or "").lower() not in ("localhost", "127.0.0.1", "::1") or
        parsed.port != expected_port or
        parsed.username or parsed.password or
        parsed.path not in ("", "/", "/0")
    ):
        pytest.fail(f"{name} must be an unauthenticated local Redis test service")
    return uri


@pytest.mark.integration
@pytest.mark.asyncio
async def test_isolated_redis_cache_and_protected_state_real_roundtrip():
    disposable_uri = _localhost_test_uri("TEST_REDIS_CACHE_URI", expected_port=6379)
    protected_uri = _localhost_test_uri("TEST_REDIS_STATE_URI", expected_port=6380)
    cache = CacheManager(disposable_uri)
    state = CacheManager(protected_uri)
    routed = RoutedCacheManager(cache, state)
    await routed.initialize()
    suffix = uuid4().hex
    cache_key = f"media:ci:{suffix}"
    session_key = f"session:ci:{suffix}"
    limiter_key = f"rate_limit:ci:{suffix}"
    try:
        cache_config = await cache.redis.config_get("maxmemory-policy")
        state_config = await state.redis.config_get("maxmemory-policy")
        def policy(config):
            value = next(iter(config.values()))
            return value.decode() if isinstance(value, bytes) else value

        assert policy(cache_config) == "allkeys-lru"
        assert policy(state_config) == "noeviction"

        assert await routed.set(cache_key, {"source": "disposable"}, expire=30)
        assert await routed.set(session_key, {"source": "protected"}, expire=30)
        assert await routed.get(cache_key) == {"source": "disposable"}
        assert await routed.get(session_key) == {"source": "protected"}
        assert await cache.redis.exists(cache_key) == 1
        assert await state.redis.exists(cache_key) == 0
        assert await state.redis.exists(session_key) == 1
        assert await cache.redis.exists(session_key) == 0
        assert 0 < await routed.ttl(session_key) <= 30

        assert await routed.increment_with_expiry(limiter_key, 1, 30) == 1
        assert await routed.increment_with_expiry(limiter_key, 1, 30) == 2
        assert await cache.redis.exists(limiter_key) == 0
        assert await state.redis.exists(limiter_key) == 1

        mixed = await routed.mget([session_key, cache_key, "media:ci:unknown"])
        assert mixed == [
            {"source": "protected"}, {"source": "disposable"}, None
        ]
    finally:
        for key in (cache_key, session_key, limiter_key):
            await routed.delete(key)
        await routed.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_protected_search_cache_generation_is_not_reused_after_reset():
    disposable_uri = _localhost_test_uri("TEST_REDIS_CACHE_URI", expected_port=6379)
    protected_uri = _localhost_test_uri("TEST_REDIS_STATE_URI", expected_port=6380)
    routed = RoutedCacheManager(CacheManager(disposable_uri), CacheManager(protected_uri))
    await routed.initialize()
    key = CacheInvalidator.SEARCH_CACHE_VERSION_KEY
    try:
        # Only run against the isolated CI Redis server. This is not a FLUSHDB.
        await routed.delete(key)
        invalidator = CacheInvalidator(routed)
        initial = await invalidator.get_search_cache_version()
        assert initial > 1
        assert await invalidator.get_search_cache_version() == initial
        assert await invalidator.increment_search_cache_version() == initial + 1

        # Simulate loss of the VERSION key, not entire databases.
        await routed.delete(key)
        reset_version = await invalidator.get_search_cache_version()
        assert reset_version > 1
        assert reset_version != initial
    finally:
        await routed.delete(key)
        await routed.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_redis_safe_serialization_and_legacy_pickle_miss():
    """Prove the live Redis API reads safe values but never unpickles legacy ones."""
    import json
    import pickle

    uri = _localhost_test_uri("TEST_REDIS_CACHE_URI", expected_port=6379)
    manager = CacheManager(uri)
    await manager.initialize()
    suffix = uuid4().hex
    keys = (
        f"media:ph009:safe:{suffix}",
        f"session:ph009:pickle:{suffix}",
        f"media:ph009:legacy-json:{suffix}",
    )
    try:
        assert await manager.set(keys[0], {"name": "Doctor X"}, expire=30)
        await manager.redis.setex(keys[1], 30, b"p" + pickle.dumps(
            {"should_be_ignored": True}, protocol=4
        ))
        await manager.redis.setex(keys[2], 30, json.dumps(
            {"raw_json": True}
        ).encode("utf-8"))

        assert await manager.mget(list(keys)) == [
            {"name": "Doctor X"}, None, {"raw_json": True}
        ]
        assert await manager.redis.exists(keys[1]) == 1
        assert await manager.redis.ttl(keys[1]) > 0
    finally:
        for key in keys:
            await manager.redis.delete(key)
        await manager.close()
