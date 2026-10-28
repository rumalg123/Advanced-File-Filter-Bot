"""PH-007 bounded deletion, stale previews, partial progress, admin confirmation."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.services.bulk_delete_policy import (
    MAX_BULK_DELETE_FILES, BULK_DELETE_BATCH_SIZE,
    BulkDeleteRejected, BulkDeleteInterrupted,
)
from core.services.bulk_media_deletion import MediaBulkDeletion
from handlers.delete import DeleteHandler


class Cursor:
    def __init__(self, collection, predicate, projection):
        self.collection = collection
        self.projection = projection
        self.requested_limit = None

    def limit(self, value):
        assert 1 <= value <= BULK_DELETE_BATCH_SIZE
        self.requested_limit = value
        self.collection.limits.append(value)
        return self

    async def to_list(self, length):
        assert length == self.requested_limit
        self.collection.max_loaded = max(self.collection.max_loaded, length)
        return [
            {k: v for k, v in doc.items() if k in self.projection}
            for doc in list(self.collection.docs.values())[:length]
        ]


class Collection:
    def __init__(self, count=250):
        self.docs = {
            f"id-{i:04d}": {
                "_id": f"id-{i:04d}",
                "file_unique_id": f"unique-{i}",
                "file_ref": f"ref-{i}",
                "file_name": f"doctor x episode {i}",
            } for i in range(count)
        }
        self.max_loaded = 0
        self.limits = []
        self.deleted_batches = []
        self.fail_batch = None

    async def count_documents(self, predicate):
        return len(self.docs)

    def find(self, predicate, projection):
        return Cursor(self, predicate, projection)

    async def delete_many(self, filter):
        ids = filter["_id"]["$in"]
        assert len(ids) <= BULK_DELETE_BATCH_SIZE
        self.deleted_batches.append(len(ids))
        if len(self.deleted_batches) == self.fail_batch:
            raise TimeoutError("Injected database outage")
        deleted = 0
        for file_id in ids:
            if self.docs.pop(file_id, None):
                deleted += 1
        return SimpleNamespace(deleted_count=deleted)


def make_deletion(count=250):
    collection = Collection(count)
    db = SimpleNamespace(execute_with_retry=AsyncMock(side_effect=lambda op, *args, **kwargs: op(*args, **kwargs)))
    cache = SimpleNamespace(
        invalidate_file_cache=AsyncMock(return_value=True),
        invalidate_all_search_results=AsyncMock(return_value=True),
    )
    media = SimpleNamespace(
        is_multi_db=False,
        _build_search_filter=lambda text, *_: {"file_name": {"$regex": text}},
        collection=AsyncMock(return_value=collection),
        db_pool=db,
        cache_invalidator=cache,
    )
    return MediaBulkDeletion(media), collection, cache


@pytest.mark.asyncio
async def test_preview_reads_only_five_names_without_deleting():
    service, col, cache = make_deletion(250)
    result = await service.preview("doctor x")
    assert result.count == 250
    assert len(result.sample) == 5
    assert col.max_loaded == 5
    assert len(col.docs) == 250
    assert not col.deleted_batches
    cache.invalidate_all_search_results.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_deletion_is_bounded_accurate_and_invalidates_each_batch():
    service, col, cache = make_deletion(250)
    assert await service.execute("doctor x", expected_count=250) == 250
    assert len(col.docs) == 0
    assert col.max_loaded == 100
    assert col.deleted_batches == [100, 100, 50]
    assert cache.invalidate_file_cache.await_count == 250
    assert cache.invalidate_all_search_results.await_count == 3


@pytest.mark.asyncio
async def test_stale_preview_rejected_before_any_delete():
    service, col, cache = make_deletion(5)
    with pytest.raises(BulkDeleteRejected, match="changed"):
        await service.execute("doctor x", expected_count=4)
    assert len(col.docs) == 5
    assert not col.deleted_batches


@pytest.mark.asyncio
async def test_no_delete_without_confirmation_and_no_unbounded_keywords():
    service, col, cache = make_deletion(8)
    with pytest.raises(BulkDeleteRejected):
        await service.execute("doctor x", expected_count=None)
    with pytest.raises(BulkDeleteRejected):
        await service.execute("doctor x", expected_count=MAX_BULK_DELETE_FILES + 1)
    with pytest.raises(BulkDeleteRejected):
        await service.preview("x")
    assert len(col.docs) == 8


@pytest.mark.asyncio
async def test_repository_failure_reports_acknowledged_progress():
    service, col, cache = make_deletion(205)
    col.fail_batch = 2
    with pytest.raises(BulkDeleteInterrupted) as exc:
        await service.execute("doctor x", expected_count=205)
    assert exc.value.deleted_count == 100
    assert len(col.docs) == 105
    assert cache.invalidate_all_search_results.await_count == 1
    # Restart requires a fresh preview with a new expected count.
    preview = await service.preview("doctor x")
    assert preview.count == 105
    col.fail_batch = None
    assert await service.execute("doctor x", expected_count=105) == 105


@pytest.mark.asyncio
async def test_shutdown_before_second_batch_preserves_remaining_records():
    service, col, cache = make_deletion(250)
    should_stop = lambda: len(col.deleted_batches) >= 1
    with pytest.raises(BulkDeleteInterrupted) as exc:
        await service.execute("doctor x", expected_count=250, stop_requested=should_stop)
    assert exc.value.deleted_count == 100
    assert len(col.docs) == 150
    assert cache.invalidate_all_search_results.await_count == 1


@pytest.mark.asyncio
async def test_search_invalidation_failure_never_reports_completion():
    service, col, cache = make_deletion(2)
    cache.invalidate_all_search_results.return_value = False
    with pytest.raises(BulkDeleteInterrupted) as exc:
        await service.execute("doctor x", expected_count=2)
    assert exc.value.deleted_count == 2
    assert cache.invalidate_all_search_results.await_count == 1


@pytest.mark.asyncio
async def test_deleteall_callback_rejects_nonadmin_and_replay(monkeypatch):
    import handlers.delete as module
    # No real Telegram client; registration side effects intentionally skipped.
    handler = object.__new__(DeleteHandler)
    user_id = 42
    nonce = "001122334455"
    data = {"keyword": "doctor x", "count": 2, "token": nonce}
    cache = SimpleNamespace(
        get=AsyncMock(return_value=data),
        delete_if_value=AsyncMock(side_effect=[True, False]),
    )
    media = SimpleNamespace(
        delete_files_by_keyword=AsyncMock(return_value=2),
    )
    handler.bot = SimpleNamespace(
        cache=cache,
        media_repo=media,
        config=SimpleNamespace(ADMINS=[42], LOG_CHANNEL=None),
    )
    handler._shutdown = asyncio.Event()

    def make_callback(who):
        return SimpleNamespace(
            data=f"deleteall_confirm#{user_id}#{nonce}",
            from_user=SimpleNamespace(id=who),
            answer=AsyncMock(),
            message=SimpleNamespace(edit_text=AsyncMock()),
        )
    forbidden = make_callback(43)
    await handler.handle_deleteall_callback(None, forbidden)
    forbidden.answer.assert_awaited_once()
    media.delete_files_by_keyword.assert_not_awaited()

    first = make_callback(42)
    await handler.handle_deleteall_callback(None, first)
    media.delete_files_by_keyword.assert_awaited_once()
    assert media.delete_files_by_keyword.await_args.kwargs["expected_count"] == 2
    second = make_callback(42)
    await handler.handle_deleteall_callback(None, second)
    assert media.delete_files_by_keyword.await_count == 1


@pytest.mark.asyncio
async def test_preview_rejects_more_than_1000_without_storing_a_token():
    handler = object.__new__(DeleteHandler)
    cache = SimpleNamespace(set=AsyncMock())
    preview = SimpleNamespace(keyword="doctor x", count=1001, sample=("one",))
    handler.bot = SimpleNamespace(
        cache=cache,
        config=SimpleNamespace(ADMINS=[42]),
        media_repo=SimpleNamespace(preview_delete_files_by_keyword=AsyncMock(return_value=preview)),
    )
    msg = SimpleNamespace(
        command=["deleteall", "doctor", "x"],
        from_user=SimpleNamespace(id=42),
        reply_text=AsyncMock(),
    )
    await handler.handle_deleteall_command(None, msg)
    cache.set.assert_not_awaited()
    assert "1001" in msg.reply_text.await_args.args[0]
