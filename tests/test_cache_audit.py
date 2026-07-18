import copy
import fnmatch
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import MediaSearchBot
from core.cache.config import CacheKeyGenerator, CachePatterns
from core.cache.invalidation import CacheInvalidator
from core.cache.monitor import CacheMonitor
from core.cache.redis_cache import CacheManager
from core.cache.serialization import (
    OptimizedSerializer,
    SerializationMethod,
    serialize,
)
from core.database.base import BaseRepository
from core.session.manager import SessionType, UnifiedSessionManager
from core.utils.rate_limiter import RateLimiter
from repositories.bot_settings import BotSettingsRepository
from repositories.channel import Channel, ChannelRepository
from repositories.connection import ConnectionRepository
from repositories.filter import FilterRepository
from repositories.media import FileType, MediaFile, MediaRepository
from repositories.optimizations.batch_operations import BatchOptimizations


class MemoryCache:
    def __init__(self):
        self.values = {}
        self.deleted = []
        self.patterns = []
        self.expirations = {}
        self.set_calls = []

    async def get(self, key):
        return copy.deepcopy(self.values.get(key))

    async def set(self, key, value, expire=None):
        self.values[key] = copy.deepcopy(value)
        self.set_calls.append((key, copy.deepcopy(value), expire))
        return True

    async def delete(self, key):
        self.deleted.append(key)
        self.values.pop(key, None)
        return True

    async def delete_pattern(self, pattern):
        self.patterns.append(pattern)
        for key in list(self.values):
            if fnmatch.fnmatch(key, pattern):
                self.values.pop(key)
        return 0

    async def increment(self, key, amount=1):
        current = int(self.values.get(key, 0)) + amount
        self.values[key] = current
        return current

    async def expire(self, key, seconds):
        self.expirations[key] = seconds
        return True

    async def delete_if_value(self, key, expected_value):
        if self.values.get(key) != expected_value:
            return False
        await self.delete(key)
        return True


class FakeCollection:
    def __init__(self, document=None, modified_count=1):
        self.document = document
        self.modified_count = modified_count

    async def find_one(self, _query):
        return copy.deepcopy(self.document)

    async def bulk_write(self, _operations, ordered=False):
        return SimpleNamespace(modified_count=self.modified_count, ordered=ordered)


class FakeDbPool:
    def __init__(self, collection):
        self._collection = collection

    async def get_collection(self, _name):
        return self._collection

    async def execute_with_retry(self, operation, *args, **kwargs):
        return await operation(*args, **kwargs)


def make_media() -> MediaFile:
    return MediaFile(
        file_unique_id="unique-1",
        file_id="telegram-file-1",
        file_ref="short-ref-1",
        file_name="Example 1080p.mkv",
        file_size=1024,
        file_type=FileType.VIDEO,
        mime_type="video/x-matroska",
        caption="Example",
    )


def test_compressed_serialization_hints_use_readable_method_prefixes():
    serializer = OptimizedSerializer()
    payload = {"items": ["compressible-value" * 100] * 20}

    compressed_json = serializer.serialize(payload, SerializationMethod.COMPRESSED_JSON)
    compressed_msgpack = serializer.serialize(payload, SerializationMethod.COMPRESSED_MSGPACK)

    assert compressed_json.startswith(b"cj")
    assert compressed_msgpack.startswith(b"cm")
    assert serializer.deserialize(compressed_json) == payload
    assert serializer.deserialize(compressed_msgpack) == payload


def test_unsupported_values_are_not_stringified_into_a_different_cache_schema():
    with pytest.raises(TypeError):
        serialize({"unsupported": {1, 2, 3}})


@pytest.mark.asyncio
async def test_cache_manager_rejects_non_positive_ttls_without_persistent_write():
    redis = SimpleNamespace(set=AsyncMock(), setex=AsyncMock())
    cache = CacheManager("redis://unused")
    cache.redis = redis

    assert not await cache.set("bad-zero", {"value": 1}, expire=0)
    assert not await cache.set("bad-negative", {"value": 1}, expire=-5)
    redis.set.assert_not_awaited()
    redis.setex.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_redis_initialization_is_rolled_back(monkeypatch):
    failed_client = SimpleNamespace(
        ping=AsyncMock(side_effect=ConnectionError("offline")),
        aclose=AsyncMock(),
    )
    monkeypatch.setattr(
        "core.cache.redis_cache.aioredis.from_url",
        lambda *_args, **_kwargs: failed_client,
    )
    cache = CacheManager("redis://offline")

    with pytest.raises(ConnectionError):
        await cache.initialize()

    assert cache.redis is None
    failed_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_rate_limiter_uses_atomic_increment_with_expiry():
    class RateCache:
        def __init__(self):
            self.atomic_calls = []

        async def ttl(self, _key):
            return -2

        async def increment_with_expiry(self, key, amount, seconds):
            self.atomic_calls.append((key, amount, seconds))
            return 1

        async def set(self, _key, _value, expire=None):
            return expire is not None

    cache = RateCache()
    limiter = RateLimiter(cache)

    allowed, retry_after = await limiter.check_rate_limit(42, "search")

    assert allowed
    assert retry_after is None
    assert cache.atomic_calls == [(CacheKeyGenerator.rate_limit(42, "search"), 1, 60)]


@pytest.mark.asyncio
async def test_cancelling_old_session_does_not_delete_newer_pointer():
    cache = MemoryCache()
    manager = UnifiedSessionManager(cache)
    pointer = CacheKeyGenerator.session(SessionType.SEARCH.value, 7)
    old_key = CacheKeyGenerator.session(SessionType.SEARCH.value, 7, "old")
    cache.values[pointer] = "new"
    cache.values[old_key] = {"session_id": "old"}

    assert await manager.cancel_session(7, SessionType.SEARCH, "old")
    assert cache.values[pointer] == "new"
    assert old_key not in cache.values


@pytest.mark.asyncio
async def test_default_session_ids_do_not_collide_within_the_same_second():
    cache = MemoryCache()
    manager = UnifiedSessionManager(cache)

    first = await manager.create_session(7, SessionType.EDIT, {"step": 1})
    second = await manager.create_session(7, SessionType.EDIT, {"step": 2})

    assert first != second


@pytest.mark.asyncio
async def test_each_search_invalidation_advances_version_and_corruption_self_heals():
    cache = MemoryCache()
    invalidator = CacheInvalidator(cache)

    assert await invalidator.invalidate_all_search_results()
    first = cache.values[CacheKeyGenerator.search_cache_version()]
    assert await invalidator.invalidate_all_search_results()
    second = cache.values[CacheKeyGenerator.search_cache_version()]
    assert (first, second) == (2, 3)

    cache.values[CacheKeyGenerator.search_cache_version()] = "broken"
    assert await invalidator.get_search_cache_version() == 1
    assert CacheKeyGenerator.search_cache_version() not in cache.values


@pytest.mark.asyncio
async def test_legacy_partial_connection_cache_rebuilds_full_entity():
    cache = MemoryCache()
    cache_key = CacheKeyGenerator.user_connections("12")
    cache.values[cache_key] = {"active_group": "-100"}
    collection = FakeCollection({
        "_id": "12",
        "group_details": [{"group_id": "-100"}],
        "active_group": "-100",
        "created_at": "2026-07-18T00:00:00+00:00",
        "updated_at": "2026-07-18T00:00:00+00:00",
    })
    repository = ConnectionRepository(FakeDbPool(collection), cache)

    assert await repository.get_active_connection("12") == "-100"
    assert cache_key in cache.deleted
    assert cache.values[cache_key]["_id"] == "12"


@pytest.mark.asyncio
async def test_group_filter_invalidation_clears_list_and_entry_prefix():
    cache = MemoryCache()
    invalidator = CacheInvalidator(cache)

    assert await invalidator.invalidate_filter_cache("-100")
    assert CacheKeyGenerator.filter_list("-100") in cache.deleted
    assert CachePatterns.filter_entries_pattern("-100") in cache.patterns


@pytest.mark.asyncio
async def test_single_database_media_create_invalidates_search_and_file_stats():
    cache = MemoryCache()
    repository = MediaRepository(None, cache)
    repository.find_file = AsyncMock(return_value=None)
    repository.create = AsyncMock(return_value=True)

    success, status, existing = await repository.save_media(make_media())

    assert (success, status, existing) == (True, 1, None)
    assert cache.values[CacheKeyGenerator.search_cache_version()] == 2
    assert CacheKeyGenerator.file_stats() in cache.deleted
    assert CacheKeyGenerator.media("unique-1") in cache.values


@pytest.mark.asyncio
async def test_media_update_invalidates_version_in_multi_database_mode():
    class MultiDatabase:
        async def update_one_across_databases(self, *_args, **_kwargs):
            return True

    cache = MemoryCache()
    repository = MediaRepository(None, cache, multi_db_manager=MultiDatabase())
    repository.find_file = AsyncMock(return_value=make_media())

    assert await repository.update("telegram-file-1", {"caption": "Updated"})
    assert cache.values[CacheKeyGenerator.search_cache_version()] == 2


@pytest.mark.asyncio
async def test_batch_premium_expiry_invalidates_user_access_and_stats():
    cache = MemoryCache()
    database = FakeDbPool(FakeCollection())
    optimization = BatchOptimizations(database, cache)

    assert await optimization._batch_expire_premium_users([10, 11])
    for user_id in (10, 11):
        assert CacheKeyGenerator.user(user_id) in cache.deleted
        assert CacheKeyGenerator.premium_status(user_id) in cache.deleted
    assert CacheKeyGenerator.user_stats() in cache.deleted


@pytest.mark.asyncio
async def test_bot_setting_upsert_does_not_put_immutable_id_in_set_document():
    cache = MemoryCache()
    repository = BotSettingsRepository(None, cache)
    repository.update = AsyncMock(return_value=True)

    assert await repository.set_setting("CACHE_TIME", 90, "int", 300, "Search TTL")
    update_data = repository.update.await_args.args[1]
    assert "_id" not in update_data


def test_configured_search_cache_ttl_is_validated_and_applied():
    cache = MemoryCache()
    assert MediaRepository(None, cache, search_cache_ttl=45).ttl.SEARCH_RESULTS == 45
    assert MediaRepository(None, cache, search_cache_ttl=0).ttl.SEARCH_RESULTS == 300


@pytest.mark.asyncio
async def test_cached_empty_channel_and_filter_lists_are_hits_not_database_reads():
    cache = MemoryCache()
    cache.values[CacheKeyGenerator.active_channels()] = []
    cache.values[CacheKeyGenerator.filter_list("-100")] = []

    channels = ChannelRepository(None, cache)
    filters = FilterRepository(None, cache)

    assert await channels.get_active_channels() == []
    assert await filters.get_filters("-100") == []


class MonitorRedis:
    def __init__(self, documents):
        self.documents = documents
        self.connection_pool = SimpleNamespace(connection_kwargs={"db": 2})

    async def scan_iter(self, match=None, count=None):
        del count
        for key in self.documents:
            if match is None or fnmatch.fnmatch(key, match):
                yield key.encode()

    async def memory_usage(self, key):
        return len(self.documents[self._text(key)])

    async def get(self, key):
        return self.documents.get(self._text(key), b"")

    async def ttl(self, _key):
        return 60

    async def info(self, section=None):
        if section == "memory":
            return {"used_memory_human": "1K"}
        return {
            "db2": {"keys": len(self.documents), "expires": len(self.documents)},
            "keyspace_hits": 5,
            "keyspace_misses": 1,
        }

    @staticmethod
    def _text(key):
        return key.decode() if isinstance(key, bytes) else str(key)


@pytest.mark.asyncio
async def test_monitor_awaits_memory_reports_selected_db_and_classifies_aliases():
    media = {
        "_id": "telegram-file-1",
        "file_unique_id": "unique-1",
        "file_ref": "short-ref-1",
    }
    raw_documents = {
        "media:unique-1": b"value-a",
        "media:telegram-file-1": b"value-b",
        "media:stale-alias": b"value-c",
    }
    redis = MonitorRedis(raw_documents)

    class MonitorCache:
        def __init__(self):
            self.redis = redis

        async def get(self, key):
            return copy.deepcopy(media) if key in raw_documents else None

    monitor = CacheMonitor(MonitorCache())
    analysis = await monitor.analyze_cache_usage(sample_size=10)
    stats = await monitor.get_cache_stats()
    aliases = await monitor.find_duplicate_data()

    assert analysis["key_size_distribution"]
    assert stats["keys"]["database"] == 2
    assert stats["keys"]["total_keys"] == 3
    assert aliases[0]["stale_cache_keys"] == ["media:stale-alias"]
    assert set(aliases[0]["valid_cache_keys"]) == {
        "media:unique-1",
        "media:telegram-file-1",
    }


@pytest.mark.asyncio
async def test_delete_pattern_streams_bounded_batches():
    class PatternRedis:
        def __init__(self):
            self.keys = {f"temp:{index}".encode() for index in range(250)}
            self.batch_sizes = []

        async def scan_iter(self, match=None, count=None):
            del count
            for key in list(self.keys):
                if fnmatch.fnmatch(key.decode(), match):
                    yield key

        async def delete(self, *keys):
            self.batch_sizes.append(len(keys))
            for key in keys:
                self.keys.discard(key)
            return len(keys)

    redis = PatternRedis()
    cache = CacheManager("redis://unused")
    cache.redis = redis

    assert await cache.delete_pattern("temp:*") == 250
    assert not redis.keys
    assert max(redis.batch_sizes) <= 100


@pytest.mark.asyncio
async def test_invalidator_propagates_delete_failure_and_user_scope_is_complete():
    class FailingCache(MemoryCache):
        async def delete(self, key):
            self.deleted.append(key)
            return False

    invalidator = CacheInvalidator(FailingCache())
    assert not await invalidator.invalidate_user_data(88)

    targets = CachePatterns.user_related(88)
    assert CacheKeyGenerator.premium_status(88) in targets
    assert CacheKeyGenerator.user_recommendations_cache(88) in targets
    assert CacheKeyGenerator.user_search_history(88) in targets


@pytest.mark.asyncio
async def test_maintenance_does_not_purge_live_ttl_managed_search_sessions():
    invalidator = SimpleNamespace(
        invalidate_search_sessions=AsyncMock(side_effect=AssertionError("must not purge"))
    )
    bot = SimpleNamespace(cache_invalidator=invalidator)

    await MediaSearchBot._cleanup_old_cache(bot)
    invalidator.invalidate_search_sessions.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_count_update_invalidates_active_projection(monkeypatch):
    cache = MemoryCache()
    channel = Channel(channel_id=-100, indexed_count=2)
    repository = ChannelRepository(None, cache)
    repository.find_by_id = AsyncMock(return_value=channel)
    monkeypatch.setattr(BaseRepository, "update", AsyncMock(return_value=True))
    repository.cache_invalidator.invalidate_channels_cache = AsyncMock(return_value=True)

    assert await repository.update_indexed_count(-100)
    repository.cache_invalidator.invalidate_channels_cache.assert_awaited_once()
