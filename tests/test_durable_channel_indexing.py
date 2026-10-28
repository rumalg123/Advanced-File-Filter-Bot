"""PH-005 channel queue regression and durable MongoDB job tests.

Uses self-contained collection doubles; never touches production MongoDB.
"""
import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from handlers.channel import ChannelHandler
from repositories.channel_index_jobs import ChannelIndexJobRepository


class Result:
    def __init__(self, upserted_id=None, modified_count=0):
        self.upserted_id = upserted_id
        self.modified_count = modified_count


class JobCollection:
    """Small deterministic subset of Mongo operations for job lifecycle tests."""

    def __init__(self):
        self.jobs = {}
        self.indexes = []
        self.collection_calls = 0

    async def create_index(self, *args, **kwargs):
        self.indexes.append((args, kwargs))

    async def update_one(self, criteria, changes, upsert=False):
        job_id = criteria["_id"]
        old = self.jobs.get(job_id)
        if old is None:
            if not upsert:
                return Result()
            data = {"_id": job_id, **changes["$setOnInsert"]}
            self.jobs[job_id] = data
            return Result(upserted_id=job_id)
        if "status" in criteria and old.get("status") != criteria["status"]:
            return Result()
        if "lease_token" in criteria and old.get("lease_token") != criteria["lease_token"]:
            return Result()

        for key, value in changes.get("$set", {}).items():
            old[key] = value
        for key in changes.get("$unset", {}):
            old.pop(key, None)
        return Result(modified_count=1)

    async def find_one_and_update(self, predicate, update, sort=None, return_document=None):
        now = datetime.now(UTC)
        candidates = [
            job for job in self.jobs.values()
            if (
                job["status"] == "pending"
                and job["next_attempt_at"] <= now
            ) or (
                job["status"] == "processing"
                and job["lease_until"] <= now
            )
        ]
        if not candidates:
            return None
        job = sorted(candidates, key=lambda x: x["created_at"])[0]
        job.update(update["$set"])
        for field, inc in update["$inc"].items():
            job[field] += inc
        return dict(job)

    async def count_documents(self, where):
        return sum(job["status"] == where["status"] for job in self.jobs.values())


def make_jobs():
    collection = JobCollection()
    pool = SimpleNamespace(get_collection=AsyncMock(return_value=collection))
    repository = ChannelIndexJobRepository(pool)
    return repository, collection, pool


@pytest.mark.asyncio
async def test_enqueuing_same_telegram_message_is_idempotent():
    repository, collection, pool = make_jobs()
    media = {"_id": "file-id", "file_unique_id": "unique", "file_name": "Doctor X"}
    assert await repository.enqueue(-100123, 456, media) is True
    assert await repository.enqueue(-100123, 456, {**media, "file_name": "changed"}) is False
    assert len(collection.jobs) == 1
    assert collection.jobs["-100123:456"]["media"] == media
    assert pool.get_collection.await_count == 1


@pytest.mark.asyncio
async def test_claim_ack_and_duplicate_processing_is_not_requeued():
    repository, collection, _ = make_jobs()
    await repository.ensure_indexes()
    assert len(collection.indexes) == 3
    await repository.enqueue(-1001, 55, {"file_id": "file-1"})
    first = await repository.claim()
    assert first["status"] == "processing"
    assert first["attempts"] == 1
    assert await repository.claim() is None
    assert await repository.acknowledge(first)
    assert (await repository.counts()) == {
        "pending": 0, "processing": 0, "dead": 0
    }
    assert collection.jobs["-1001:55"]["status"] == "done"
    assert not await repository.acknowledge(first)


@pytest.mark.asyncio
async def test_expired_lease_reclaimed_after_crash_and_stale_ack_rejected():
    repository, collection, _ = make_jobs()
    await repository.enqueue(-1001, 42, {"file_id": "file"})
    first = await repository.claim()
    collection.jobs[first["_id"]]["lease_until"] = datetime.now(UTC) - timedelta(seconds=1)

    second = await repository.claim()
    assert second["attempts"] == 2
    assert second["lease_token"] != first["lease_token"]
    assert not await repository.acknowledge(first)
    assert await repository.acknowledge(second)


@pytest.mark.asyncio
async def test_retry_backoff_then_dead_letter_then_manual_replay():
    repository, collection, _ = make_jobs()
    await repository.enqueue(-1001, 7, {"file_id": "file"})
    for attempt in range(repository.MAX_ATTEMPTS):
        job = await repository.claim()
        assert job is not None
        status = await repository.fail(job, "temporary outage")
        if attempt < repository.MAX_ATTEMPTS - 1:
            assert status == "pending"
            # Avoid waiting during deterministic lifecycle tests.
            collection.jobs[job["_id"]]["next_attempt_at"] = (
                datetime.now(UTC) - timedelta(seconds=1)
            )
        else:
            assert status == "dead"

    assert (await repository.counts())["dead"] == 1
    assert await repository.claim() is None
    assert await repository.retry_dead("-1001:7")
    assert collection.jobs["-1001:7"]["attempts"] == 0
    assert (await repository.counts())["pending"] == 1


@pytest.mark.asyncio
async def test_full_in_memory_buffers_backpressure_without_dropping(monkeypatch):
    import handlers.channel as channel

    handler = object.__new__(ChannelHandler)
    handler.bot = SimpleNamespace(config=SimpleNamespace())
    handler.message_queue = asyncio.Queue(maxsize=1)
    old_primary = {"message": "old primary"}
    handler.message_queue.put_nowait(old_primary)
    old_overflow = {"message": "old overflow"}
    handler.overflow_queue = [old_overflow]
    handler.max_overflow_size = 1
    handler.last_warning_time = 0
    handler.queue_full_warnings = 0

    monkeypatch.setattr(channel, "get_special_channels", lambda _: [])
    message = SimpleNamespace(chat=SimpleNamespace(id=-1001), from_user=None)
    handle_task = asyncio.create_task(handler.handle_channel_media(None, message))
    await asyncio.sleep(0)
    assert not handle_task.done()
    assert handler.overflow_queue == [old_overflow]
    assert handler.message_queue.qsize() == 1

    # A worker frees capacity; the handler resumes without evicting anything.
    assert handler.message_queue.get_nowait() is old_primary
    await asyncio.wait_for(handle_task, timeout=1)
    assert handler.message_queue.get_nowait()["message"] is message
    assert handler.overflow_queue == [old_overflow]


@pytest.mark.asyncio
async def test_durable_handler_snapshots_media_before_returning(monkeypatch):
    import handlers.channel as channel

    message = SimpleNamespace(chat=SimpleNamespace(id=-1001), id=10, from_user=None)
    media = SimpleNamespace(file_unique_id="unique", file_id="file-id")
    media_file = SimpleNamespace(file_name="Doctor X")
    handler = object.__new__(ChannelHandler)
    handler.bot = SimpleNamespace(
        config=SimpleNamespace(),
        media_repo=SimpleNamespace(_entity_to_dict=lambda f: {"file_name": f.file_name}),
    )
    handler.durable_jobs = SimpleNamespace(enqueue=AsyncMock(return_value=True))
    handler.message_queue = asyncio.Queue(maxsize=1)
    monkeypatch.setattr(channel, "get_special_channels", lambda _: [])
    monkeypatch.setattr(
        "core.utils.media_extractor.extract_media_from_message",
        lambda *_args, **_kwargs: (media, "video", None),
    )
    monkeypatch.setattr(
        channel.MediaFileFactory, "from_pyrogram_media",
        lambda **_kwargs: media_file,
    )

    await handler.handle_channel_media(None, message)
    handler.durable_jobs.enqueue.assert_awaited_once_with(
        -1001, 10, {"file_name": "Doctor X"}
    )
    assert handler.message_queue.empty()


@pytest.mark.asyncio
async def test_worker_acknowledges_before_scheduling_side_effects():
    """After a crash before ack, duplicate file save is safe to retry."""
    handler = object.__new__(ChannelHandler)
    handler._shutdown = asyncio.Event()
    media = SimpleNamespace(file_name="Doctor X")
    job = {
        "_id": "-1001:10", "chat_id": -1001, "lease_token": "token",
        "media": {"file_name": "Doctor X"},
    }
    jobs = SimpleNamespace(
        ensure_indexes=AsyncMock(),
        claim=AsyncMock(side_effect=[job]),
        acknowledge=AsyncMock(return_value=True),
        fail=AsyncMock(),
    )
    handler.durable_jobs = jobs
    notifications = SimpleNamespace(schedule_new_media=AsyncMock())
    handler.bot = SimpleNamespace(
        media_repo=SimpleNamespace(
            _dict_to_entity=lambda data: media,
            save_media=AsyncMock(return_value=(True, 1, None)),
        ),
        feature_service=notifications,
    )
    handler.channel_repo = SimpleNamespace(update_indexed_count=AsyncMock(return_value=True))
    handler.processing_config = SimpleNamespace(inter_message_delay=0)

    async def ack_and_stop(_job):
        handler._shutdown.set()
        return True

    jobs.acknowledge.side_effect = ack_and_stop
    await handler._process_durable_queue()

    jobs.acknowledge.assert_awaited_once()
    jobs.fail.assert_not_awaited()
    handler.channel_repo.update_indexed_count.assert_awaited_once_with(-1001)
    notifications.schedule_new_media.assert_called_once_with(media)


@pytest.mark.asyncio
async def test_worker_retains_failed_media_for_retry():
    handler = object.__new__(ChannelHandler)
    handler._shutdown = asyncio.Event()
    job = {"_id": "-1001:12", "chat_id": -1001, "media": {"file_name": "Doctor X"}}
    jobs = SimpleNamespace(
        ensure_indexes=AsyncMock(),
        claim=AsyncMock(return_value=job),
        acknowledge=AsyncMock(),
        fail=AsyncMock(),
    )
    handler.durable_jobs = jobs
    handler.bot = SimpleNamespace(
        media_repo=SimpleNamespace(
            _dict_to_entity=lambda data: SimpleNamespace(file_name="Doctor X"),
            save_media=AsyncMock(return_value=(False, 2, None)),
        ),
    )

    async def fail_then_stop(_job, _reason):
        handler._shutdown.set()
        return "pending"

    jobs.fail.side_effect = fail_then_stop
    await handler._process_durable_queue()
    jobs.acknowledge.assert_not_awaited()
    jobs.fail.assert_awaited_once()


@pytest.mark.asyncio
async def test_mongo_unavailable_during_enqueue_is_not_silently_accepted(monkeypatch):
    import handlers.channel as channel
    handler = object.__new__(ChannelHandler)
    handler.bot = SimpleNamespace(
        config=SimpleNamespace(),
        media_repo=SimpleNamespace(_entity_to_dict=lambda _: {"file_name": "Doctor X"}),
    )
    handler.durable_jobs = SimpleNamespace(
        enqueue=AsyncMock(side_effect=ConnectionError("DB down"))
    )
    monkeypatch.setattr(channel, "get_special_channels", lambda _: [])
    monkeypatch.setattr(
        "core.utils.media_extractor.extract_media_from_message",
        lambda *_args, **_kwargs: (SimpleNamespace(), "video", None),
    )
    monkeypatch.setattr(
        channel.MediaFileFactory, "from_pyrogram_media",
        lambda **_kwargs: SimpleNamespace(file_name="Doctor X"),
    )
    with pytest.raises(ConnectionError, match="DB down"):
        await handler.handle_channel_media(
            None, SimpleNamespace(chat=SimpleNamespace(id=-1001), id=1, from_user=None)
        )
