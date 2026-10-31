"""PH-018: durable saved-search alert fan-out, safety, retries and recovery."""
import asyncio
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from config.settings import settings
from core.services.features import FeatureService
from repositories.features import FeatureRepository
from repositories.media import FileType, MediaFile
from repositories.saved_search_alert_jobs import SavedSearchAlertJobRepository
from scripts.profile_media_search import is_local


def make_media():
    return MediaFile(
        file_id="tg-file-1", file_unique_id="unique-test-media",
        file_ref="file-ref", file_name="The.Matrix.1999.1080p.mkv",
        file_size=100, file_type=FileType.VIDEO, mime_type="video/mp4",
        caption=None,
    )


@pytest.mark.asyncio
async def test_default_off_mode_never_opens_durable_queue(monkeypatch):
    monkeypatch.setattr(settings.processing, "durable_saved_search_alerts", False)
    pool = SimpleNamespace(get_collection=AsyncMock())
    repo = FeatureRepository(pool)
    service = FeatureService(repo, None, None,
                             SimpleNamespace(FEATURE_SAVED_SEARCH_ALERTS=False),
                             bot=SimpleNamespace())
    service.schedule_new_media(make_media())
    await service.persist_new_media(make_media())
    service.start_alert_workers()
    pool.get_collection.assert_not_awaited()
    assert service._alert_jobs is None


@pytest.mark.asyncio
async def test_bounded_workers_only_start_once_with_two_flags(monkeypatch):
    monkeypatch.setattr(settings.processing, "durable_saved_search_alerts", True)
    monkeypatch.setattr(settings.processing, "saved_search_alert_workers", 2)
    manager = SimpleNamespace(create_background_task=Mock())
    service = FeatureService(
        SimpleNamespace(db_pool=object()), None, None,
        SimpleNamespace(FEATURE_SAVED_SEARCH_ALERTS=True),
        bot=SimpleNamespace(handler_manager=manager),
    )
    service.start_alert_workers()
    service.start_alert_workers()
    assert manager.create_background_task.call_count == 2
    # Close never-scheduled coroutine objects created by the mock.
    for call in manager.create_background_task.call_args_list:
        call.args[0].close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_mongodb_claim_checkpoint_retry_dead_letter_and_recipient_lease(monkeypatch):
    uri = os.getenv("TEST_MONGO_URI")
    if not uri:
        pytest.skip("Local disposable MongoDB CI service required")
    assert is_local(uri), "Never test fixtures against a remote database"
    monkeypatch.setattr(settings.processing, "durable_saved_search_alerts", True)
    name = f"ph018_ci_{uuid4().hex}"
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)

    class Pool:
        async def get_collection(self, collection_name):
            return client[name][collection_name]

        async def execute_with_retry(self, fn, *args, **kwargs):
            return await fn(*args, **kwargs)

    pool = Pool()
    queue = SavedSearchAlertJobRepository(
        pool, lease_seconds=60, delivery_lease_seconds=60
    )
    try:
        await queue.ensure_indexes()
        index_info = await client[name].saved_search_alert_jobs.index_information()
        assert {"saved_alert_pending", "saved_alert_reclaim",
                "saved_alert_completed_retention"} <= set(index_info)
        assert index_info["saved_alert_completed_retention"]["expireAfterSeconds"] == 2592000

        media = make_media()
        assert await queue.enqueue(media)
        assert not await queue.enqueue(media)
        assert await client[name].saved_search_alert_jobs.count_documents({}) == 1
        first = await queue.claim()
        assert first["status"] == "processing"
        assert first["attempts"] == 1
        assert await queue.claim() is None
        assert await queue.checkpoint(first, "s000100")
        await client[name].saved_search_alert_jobs.update_one(
            {"_id": first["_id"]},
            {"$set": {"lease_until": datetime.now(UTC) - timedelta(seconds=1)}},
        )
        assert not await queue.checkpoint(first, "s000200")
        second = await queue.claim()
        assert second["lease_token"] != first["lease_token"]
        assert second["after_id"] == "s000100"
        assert not await queue.acknowledge(first)
        assert await queue.renew(second)
        assert await queue.acknowledge(second)
        assert (await queue.metrics())["processing"] == 0

        search_id, file_id = "s001", media.file_unique_id
        state, token = await queue.begin_delivery(search_id, file_id)
        assert (state, bool(token)) == ("claimed", True)
        assert (await queue.begin_delivery(search_id, file_id))[0] == "in_flight"
        assert await queue.release_delivery(search_id, file_id, token)
        state, token = await queue.begin_delivery(search_id, file_id)
        assert state == "claimed"
        assert await queue.finish_delivery(search_id, file_id, token)
        assert (await queue.begin_delivery(search_id, file_id))[0] == "delivered"

        # Existing PH-017 claim documents remain understood as already sent.
        legacy = "legacy-search"
        legacy_id = queue._delivery_id(legacy, file_id)
        await client[name].saved_search_notifications.insert_one({
            "_id": legacy_id, "search_id": legacy,
            "file_unique_id": file_id, "created_at": datetime.now(UTC),
        })
        assert (await queue.begin_delivery(legacy, file_id))[0] == "delivered"

        assert await queue.enqueue(MediaFile(
            **{**media.__dict__, "file_unique_id": "another-unique"}
        ))
        for attempt in range(queue.MAX_ATTEMPTS):
            claimed = await queue.claim()
            assert claimed is not None and claimed["attempts"] == attempt + 1
            state = await queue.fail(claimed, ValueError("deliberate failure with secret"))
            if attempt + 1 < queue.MAX_ATTEMPTS:
                assert state == "pending"
                await client[name].saved_search_alert_jobs.update_one(
                    {"_id": claimed["_id"]},
                    {"$set": {"next_attempt_at": datetime.now(UTC) - timedelta(seconds=1)}},
                )
            else:
                assert state == "dead"
        metrics = await queue.metrics()
        assert metrics["dead"] == 1
        assert await queue.retry_dead(claimed["_id"])
        assert (await queue.metrics())["pending"] == 1
        stored = await client[name].saved_search_alert_jobs.find_one({"_id": claimed["_id"]})
        assert stored.get("last_error_type") is None
        assert "secret" not in str(stored)
    finally:
        await client.drop_database(name)
        client.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_mongodb_recovery_reprocesses_checkpointed_page_without_duplicates(monkeypatch):
    uri = os.getenv("TEST_MONGO_URI")
    if not uri:
        pytest.skip("Requires ephemeral local CI MongoDB")
    assert is_local(uri), "Never use production DB for integration fixtures"
    monkeypatch.setattr(settings.processing, "durable_saved_search_alerts", True)
    db_name = f"ph018_fanout_{uuid4().hex}"
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)

    class Pool:
        async def get_collection(self, name):
            return client[db_name][name]

        async def execute_with_retry(self, fn, *a, **kw):
            return await fn(*a, **kw)

    queue = SavedSearchAlertJobRepository(Pool(), lease_seconds=60)
    repo = FeatureRepository(Pool())
    service = FeatureService(
        repo, None, None, SimpleNamespace(FEATURE_SAVED_SEARCH_ALERTS=True),
        bot=SimpleNamespace(send_message=AsyncMock(), user_repo=SimpleNamespace(can_receive_content=AsyncMock(return_value=True))),
    )
    service._alert_jobs = queue
    media = make_media()
    sent = []
    try:
        await queue.ensure_indexes()
        await client[db_name].saved_searches.insert_many([{
            "_id": f"s{i:05d}", "user_id": i + 100,
            "query": "matrix", "normalized_query": "matrix",
            "active": True,
        } for i in range(215)])
        assert await queue.enqueue(media)
        leased = await queue.claim()
        assert leased
        async def failing_send(_fn, user_id, *_a, **_kw):
            if user_id == 205:
                raise ConnectionError("simulated telegram API outage")
            sent.append(user_id)

        with patch("core.services.features.telegram_api.call_api",
                   new=AsyncMock(side_effect=failing_send)):
            with pytest.raises(ConnectionError):
                await service._notify_durable_job(leased, asyncio.Event())
        persisted = await client[db_name].saved_search_alert_jobs.find_one({
            "_id": leased["_id"]
        })
        assert persisted["after_id"] == "s00099"
        assert await queue.fail(leased, RuntimeError("outage")) == "pending"
        await client[db_name].saved_search_alert_jobs.update_one(
            {"_id": leased["_id"]},
            {"$set": {"next_attempt_at": datetime.now(UTC) - timedelta(seconds=1)}},
        )
        recovered = await queue.claim()
        assert recovered["after_id"] == "s00099"
        async def healthy_send(_fn, user_id, *_a, **_kw):
            sent.append(user_id)

        with patch("core.services.features.telegram_api.call_api",
                   new=AsyncMock(side_effect=healthy_send)):
            assert await service._notify_durable_job(recovered, asyncio.Event()) == 110
        assert await queue.acknowledge(recovered)
        assert sorted(sent) == list(range(100, 315))
        assert len(sent) == len(set(sent)) == 215
        assert (await queue.metrics())["pending"] == 0
    finally:
        await client.drop_database(db_name)
        client.close()
