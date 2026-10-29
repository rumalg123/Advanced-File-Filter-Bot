"""PH-017 coverage for all subscribers past the old newest-500 cutoff."""
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from core.services.features import FeatureService
from repositories.features import FeatureRepository
from repositories.media import FileType, MediaFile
from scripts.profile_media_search import is_local


def media_fixture():
    return MediaFile(
        file_id="telegram-file", file_unique_id="test-unique-file",
        file_ref=None, file_name="The.Matrix.1999.1080p.mkv",
        file_size=100, file_type=FileType.VIDEO, mime_type="video/mp4",
        caption=None,
    )


@pytest.mark.asyncio
async def test_every_active_subscriber_matched_after_500_with_bounded_pages():
    records = [{
        "_id": f"s{i:06d}", "user_id": i + 100,
        "query": "matrix" if i % 251 == 0 else "nonmatching",
        "normalized_query": "matrix" if i % 251 == 0 else "nonmatching",
    } for i in range(1253)]
    requested = []
    claimed = set()
    deliveries = []

    async def get_page(*, after_id=None, limit=100):
        requested.append((after_id, limit))
        assert limit == 100
        candidates = [doc for doc in records
                      if after_id is None or doc["_id"] > after_id]
        return candidates[:limit]

    async def claim(search_id, file_id):
        key = (search_id, file_id)
        if key in claimed:
            return False
        claimed.add(key)
        return True

    async def send(_func, user_id, *_args, **_kwargs):
        deliveries.append(user_id)

    repo = SimpleNamespace(
        get_active_saved_search_page=AsyncMock(side_effect=get_page),
        claim_saved_search_notification=AsyncMock(side_effect=claim),
        release_saved_search_notification=AsyncMock(),
    )
    service = FeatureService(
        repo, None, None,
        SimpleNamespace(FEATURE_SAVED_SEARCH_ALERTS=True),
        bot=SimpleNamespace(send_message=AsyncMock()),
    )

    with patch("core.services.features.telegram_api.call_api", new=AsyncMock(side_effect=send)):
        assert await service.notify_saved_search_matches(media_fixture()) == 5
        assert await service.notify_saved_search_matches(media_fixture()) == 0

    assert set(deliveries) == {100 + i for i in range(1253) if i % 251 == 0}
    assert len(deliveries) == len(set(deliveries)) == 5
    assert len(requested) == 26  # 13 bounded pages per invocation
    assert all(limit == 100 for _after, limit in requested)
    assert "s001199" in {after for after, _limit in requested}
    repo.release_saved_search_notification.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_page_read_never_looks_like_end_of_subscriptions():
    repo = SimpleNamespace(
        get_active_saved_search_page=AsyncMock(side_effect=ConnectionError("Mongo unavailable")),
        claim_saved_search_notification=AsyncMock(),
    )
    service = FeatureService(
        repo, None, None, SimpleNamespace(FEATURE_SAVED_SEARCH_ALERTS=True),
        bot=SimpleNamespace(send_message=AsyncMock()),
    )
    with pytest.raises(ConnectionError, match="Mongo unavailable"):
        await service.notify_saved_search_matches(media_fixture())
    repo.claim_saved_search_notification.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_or_out_of_order_pages_fail_closed_instead_of_looping():
    repo = SimpleNamespace(
        get_active_saved_search_page=AsyncMock(return_value=[
            {"_id": "s001", "normalized_query": "other"},
            {"_id": "s000", "normalized_query": "other"},
        ]),
        claim_saved_search_notification=AsyncMock(),
    )
    service = FeatureService(
        repo, None, None, SimpleNamespace(FEATURE_SAVED_SEARCH_ALERTS=True),
        bot=SimpleNamespace(send_message=AsyncMock()),
    )
    with pytest.raises(RuntimeError, match="cursor contract"):
        await service.notify_saved_search_matches(media_fixture())
    repo.claim_saved_search_notification.assert_not_awaited()


@pytest.mark.parametrize("limit", [0, 101, -1, True, 1.5])
@pytest.mark.asyncio
async def test_repository_rejects_invalid_page_sizes_without_database_calls(limit):
    pool = SimpleNamespace(get_collection=AsyncMock())
    repo = FeatureRepository(pool)
    with pytest.raises(ValueError, match="page limit"):
        await repo.get_active_saved_search_page(limit=limit)
    pool.get_collection.assert_not_awaited()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_mongo_keyset_pages_cover_all_active_over_500_with_mutable_timestamps():
    uri = os.getenv("TEST_MONGO_URI")
    if not uri:
        pytest.skip("Requires disposable CI MongoDB")
    assert is_local(uri), "Never test writes against a remote MongoDB"
    db_name = f"ph017_ci_{uuid4().hex}"
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)

    class Pool:
        async def get_collection(self, name):
            assert name == "saved_searches"
            return client[db_name][name]

        async def execute_with_retry(self, fn, *args, **kwargs):
            return await fn(*args, **kwargs)

    try:
        collection = client[db_name].saved_searches
        now = datetime.now(UTC)
        records = [{
            "_id": f"search-{i:05d}",
            "user_id": i + 1,
            "query": "matrix" if i % 503 == 0 else "other",
            "normalized_query": "matrix" if i % 503 == 0 else "other",
            "active": i < 1205,
            "updated_at": now - timedelta(days=(i % 10)),
        } for i in range(1400)]
        await collection.insert_many(records)

        repository = FeatureRepository(Pool())
        current = None
        ids = []
        sizes = []
        while True:
            page = await repository.get_active_saved_search_page(
                after_id=current, limit=73,
            )
            if not page:
                break
            sizes.append(len(page))
            ids.extend(doc["_id"] for doc in page)
            current = page[-1]["_id"]
            if len(sizes) == 1:
                await collection.update_one(
                    {"_id": ids[0]}, {"$set": {"updated_at": now + timedelta(days=200)}}
                )

        assert len(ids) == len(set(ids)) == 1205
        assert ids == sorted(ids)
        assert all(1 <= size <= 73 for size in sizes)
        assert "search-00000" in ids
        assert "search-00500" in ids
        assert "search-01204" in ids
        assert "search-01205" not in ids
        assert await collection.count_documents({"active": True}) == 1205
    finally:
        await client.drop_database(db_name)
        client.close()
