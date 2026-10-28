"""PH-002: a database outage must never masquerade as a valid empty search.

No MongoDB/Redis instance is required. Error paths are injected at the same
driver operations exercised by MediaRepository on single-database production.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pymongo.errors import ServerSelectionTimeoutError, OperationFailure

from core.database.errors import SearchBackendUnavailableError, SEARCH_RETRY_MESSAGE
from core.services.file_access import FileAccessService
from repositories.media import MediaRepository


class MemoryCache:
    def __init__(self):
        self.values = {}
        self.writes = []
        self.deletes = []

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, expire=None):
        self.writes.append((key, value, expire))
        self.values[key] = value
        return True

    async def delete(self, key):
        self.deletes.append(key)
        self.values.pop(key, None)
        return True


class Cursor:
    def __init__(self, result=None, error=None):
        self.result = result if result is not None else []
        self.error = error

    def sort(self, *args):
        return self

    def skip(self, *args):
        return self

    def limit(self, *args):
        return self

    async def to_list(self, length=None):
        if self.error:
            raise self.error
        return self.result


class Collection:
    def __init__(self, *, count=None, count_error=None, read_error=None):
        self.count = count
        self.count_error = count_error
        self.read_error = read_error
        self.count_calls = 0
        self.find_calls = 0

    async def count_documents(self, query):
        self.count_calls += 1
        if self.count_error:
            raise self.count_error
        return self.count if self.count is not None else 0

    def find(self, query):
        self.find_calls += 1
        return Cursor(error=self.read_error)


class Pool:
    def __init__(self, collection):
        self.collection = collection

    async def get_collection(self, name):
        assert name == "media_files"
        return self.collection

    async def execute_with_retry(self, operation, *args, **kwargs):
        return await operation(*args, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["count", "page"])
async def test_driver_failures_propagate_without_poisoning_redis(operation):
    error = ServerSelectionTimeoutError("database unavailable")
    collection = Collection(
        count=3,
        count_error=error if operation == "count" else None,
        read_error=error if operation == "page" else None,
    )
    cache = MemoryCache()
    repo = MediaRepository(Pool(collection), cache)
    assert repo.is_multi_db is False

    for _ in range(2):
        with pytest.raises(SearchBackendUnavailableError) as exc:
            await repo.search_files("doctor x", offset=0, limit=10)
        assert isinstance(exc.value.__cause__, ServerSelectionTimeoutError)

    # A failed count or page retrieval must not be cached as a zero result.
    assert not cache.writes
    assert collection.count_calls == 2
    if operation == "count":
        assert collection.find_calls == 0
    else:
        assert collection.find_calls == 2


@pytest.mark.asyncio
async def test_successful_zero_count_is_still_eligible_for_negative_cache():
    cache = MemoryCache()
    collection = Collection(count=0)
    repo = MediaRepository(Pool(collection), cache)

    files, next_offset, total = await repo.search_files("absent series")
    assert (files, next_offset, total) == ([], 0, 0)
    assert len(cache.writes) == 1
    assert cache.writes[0][2] == 45
    assert collection.count_calls == 1

    await repo.search_files("absent series")
    assert collection.count_calls == 1


@pytest.mark.asyncio
async def test_bad_query_propagates_in_strict_mode_but_legacy_callers_remain_compatible():
    error = OperationFailure("bad query", code=2)
    collection = Collection(count_error=error, read_error=error)
    repo = MediaRepository(Pool(collection), MemoryCache())

    assert await repo.count({"invalid": 1}) == 0
    assert await repo.find_many({"invalid": 1}) == []
    with pytest.raises(OperationFailure):
        await repo.count({"invalid": 1}, raise_on_error=True)
    with pytest.raises(OperationFailure):
        await repo.find_many({"invalid": 1}, raise_on_error=True)


@pytest.mark.asyncio
async def test_search_service_returns_retryable_error_not_successful_zero_results():
    media_repo = SimpleNamespace(
        search_files=AsyncMock(
            side_effect=SearchBackendUnavailableError("Mongo URI must stay secret")
        )
    )
    service = FileAccessService(
        user_repo=SimpleNamespace(can_retrieve_file=AsyncMock(return_value=(True, "allowed"))),
        media_repo=media_repo,
        cache_manager=MemoryCache(),
        rate_limiter=SimpleNamespace(
            check_rate_limit=AsyncMock(return_value=(True, None))
        ),
        config=SimpleNamespace(USE_CAPTION_FILTER=True, FEATURE_ADVANCED_SEARCH=False),
    )
    result = await service.search_files_with_access_check(
        user_id=42, query="doctor x", chat_id=42
    )

    assert result == ([], 0, 0, False, SEARCH_RETRY_MESSAGE)
    assert "Mongo" not in result[-1] and "URI" not in result[-1]


@pytest.mark.asyncio
async def test_service_still_reports_genuine_empty_search_as_success():
    service = FileAccessService(
        user_repo=SimpleNamespace(can_retrieve_file=AsyncMock(return_value=(True, "allowed"))),
        media_repo=SimpleNamespace(search_files=AsyncMock(return_value=([], 0, 0))),
        cache_manager=MemoryCache(),
        rate_limiter=SimpleNamespace(check_rate_limit=AsyncMock(return_value=(True, None))),
        config=SimpleNamespace(USE_CAPTION_FILTER=True, FEATURE_ADVANCED_SEARCH=False),
    )
    assert await service.search_files_with_access_check(
        user_id=42, query="absent series", chat_id=42
    ) == ([], 0, 0, True, None)


@pytest.mark.asyncio
async def test_group_failure_does_not_trigger_filters_or_zero_result_analytics():
    from handlers.search import SearchHandler

    message = SimpleNamespace(
        chat=SimpleNamespace(id=-1001),
        reply_text=AsyncMock(),
    )
    handler = object.__new__(SearchHandler)
    handler.bot = SimpleNamespace(
        file_service=SimpleNamespace(search_files_with_access_check=AsyncMock(
            return_value=([], 0, 0, False, SEARCH_RETRY_MESSAGE)
        )),
        config=SimpleNamespace(MAX_BTN_SIZE=10, DISABLE_FILTER=False),
    )
    handler.search_results_service = SimpleNamespace(send_results=AsyncMock())
    handler._check_and_send_filter = AsyncMock()
    handler._track_successful_query = AsyncMock()
    handler._sync_zero_result_analytics = AsyncMock()

    await handler._handle_group_search(None, message, "doctor x", 42)

    message.reply_text.assert_awaited_once()
    assert "temporarily unavailable" in message.reply_text.await_args.args[0].lower()
    handler._check_and_send_filter.assert_not_awaited()
    handler._track_successful_query.assert_not_awaited()
    handler._sync_zero_result_analytics.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_failure_does_not_emit_no_results_or_analytics():
    from handlers.search import SearchHandler

    message = SimpleNamespace(reply_text=AsyncMock())
    handler = object.__new__(SearchHandler)
    handler.bot = SimpleNamespace(
        file_service=SimpleNamespace(search_files_with_access_check=AsyncMock(
            return_value=([], 0, 0, False, SEARCH_RETRY_MESSAGE)
        )),
        config=SimpleNamespace(MAX_BTN_SIZE=10),
    )
    handler._sync_zero_result_analytics = AsyncMock()
    handler._track_successful_query = AsyncMock()

    await handler._handle_private_search(None, message, "doctor x", 42)

    message.reply_text.assert_awaited_once()
    assert "temporarily unavailable" in message.reply_text.await_args.args[0].lower()
    handler._sync_zero_result_analytics.assert_not_awaited()
    handler._track_successful_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_pagination_backend_failure_shows_retry_alert(monkeypatch):
    from handlers.callbacks_handlers.pagination import PaginationCallbackHandler

    handler = PaginationCallbackHandler(SimpleNamespace(
        file_service=SimpleNamespace(search_files_with_access_check=AsyncMock(
            return_value=([], 0, 0, False, SEARCH_RETRY_MESSAGE)
        )),
        cache=MemoryCache(),
        config=SimpleNamespace(MAX_BTN_SIZE=10),
    ))
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        data="search#page#doctor x#0#10#42",
        answer=AsyncMock(),
    )

    # Use a valid parsed callback without depending on an actual Telegram client.
    import handlers.callbacks_handlers.pagination as pagination_handler
    monkeypatch.setattr(
        pagination_handler.PaginationHelper,
        "parse_callback_data",
        lambda _: {"query": "doctor x", "offset": 0, "total": 10, "user_id": 42},
    )
    monkeypatch.setattr(pagination_handler, "is_private_chat", lambda _: True)

    await handler.handle_search_pagination(None, callback)

    callback.answer.assert_awaited_once_with(SEARCH_RETRY_MESSAGE, show_alert=True)
