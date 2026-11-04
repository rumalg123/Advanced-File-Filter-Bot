"""Group search results, ownership, literal queries and cleanup."""
import html
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.database.errors import SEARCH_RETRY_MESSAGE
from core.services.search_results import SearchResultsService
from core.utils.caption import CaptionFormatter
from core.utils.pagination import PaginationBuilder
from handlers.search import SearchHandler
from repositories.media import FileType, MediaFile


def media(index=1):
    return MediaFile(file_unique_id=f'qa-unique-{index}', file_id=f'qa-file-{index}',
        file_ref=f'qa-ref-{index}', file_name=f'QA Group {index}.txt', file_size=10,
        file_type=FileType.DOCUMENT, mime_type='text/plain', caption=None)


@pytest.mark.parametrize('is_private', [False, True])
def test_result_caption_keeps_user_query_literal(is_private):
    query = 'QA <b>literal</b> & <unknown>'
    pagination = PaginationBuilder(total_items=15, page_size=10, current_offset=0,
                                   query='q:fixture', user_id=2)
    caption = CaptionFormatter.format_search_results_caption(
        query, 15, pagination, is_private=is_private)
    assert html.escape(query) in caption
    assert 'Search Results for:</b> QA <b>' not in caption


def group_fixture():
    handler = object.__new__(SearchHandler)
    handler.bot = SimpleNamespace(config=SimpleNamespace(MAX_BTN_SIZE=3, DISABLE_FILTER=True),
        file_service=SimpleNamespace(search_files_with_access_check=AsyncMock(
            return_value=([media()], 0, 1, True, None))))
    handler.search_results_service = SimpleNamespace(send_results=AsyncMock(return_value=True))
    handler._schedule_auto_delete = Mock()
    handler._track_successful_query = AsyncMock()
    handler._sync_zero_result_analytics = AsyncMock()
    handler._check_and_send_filter = AsyncMock(return_value=False)
    message = SimpleNamespace(chat=SimpleNamespace(id=-1001), reply_text=AsyncMock())
    return handler, message


@pytest.mark.asyncio
async def test_group_results_are_scoped_to_group_and_original_user():
    handler, message = group_fixture()
    await handler._handle_group_search(None, message, 'QA Group', 2)
    search = handler.bot.file_service.search_files_with_access_check.await_args.kwargs
    assert search['chat_id'] == -1001 and search['user_id'] == 2
    sent = handler.search_results_service.send_results.await_args.kwargs
    assert sent['is_private'] is False and sent['user_id'] == 2
    handler._track_successful_query.assert_awaited_once_with(2, 'QA Group')


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['empty', 'denied', 'unavailable'])
async def test_group_empty_and_unavailable_paths_do_not_publish_results(kind):
    handler, message = group_fixture()
    handler.bot.file_service.search_files_with_access_check.return_value = (
        [], 0, 0, kind == 'empty', SEARCH_RETRY_MESSAGE if kind == 'unavailable' else 'access denied')
    await handler._handle_group_search(None, message, 'QA Group', 2)
    handler.search_results_service.send_results.assert_not_awaited()
    handler._track_successful_query.assert_not_awaited()
    if kind == 'unavailable':
        message.reply_text.assert_awaited_once()
        handler._sync_zero_result_analytics.assert_not_awaited()
    else:
        message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_group_custom_filter_fallback_is_tracked_when_enabled():
    handler, message = group_fixture()
    handler.bot.config.DISABLE_FILTER = False
    handler.bot.file_service.search_files_with_access_check.return_value = ([], 0, 0, True, None)
    handler._check_and_send_filter.return_value = True
    await handler._handle_group_search(None, message, 'QA Group', 2)
    handler._check_and_send_filter.assert_awaited_once()
    handler._track_successful_query.assert_awaited_once_with(2, 'QA Group')


@pytest.mark.asyncio
async def test_group_result_session_buttons_and_auto_delete_preserve_ownership():
    class Cache:
        def __init__(self): self.values = {}
        async def set(self, key, value, **kwargs): self.values[key] = value; return True
        async def get(self, key): return self.values.get(key)
    cache = Cache()
    service = SearchResultsService(cache, SimpleNamespace(PICS=[], MESSAGE_DELETE_SECONDS=10,
                                                          FEATURE_DUPLICATE_GROUPING=True))
    reply = SimpleNamespace(id=99)
    message = SimpleNamespace(reply_text=AsyncMock(return_value=reply))
    delete = Mock()
    assert await service.send_results(None, message, [media(1), media(2)], 'QA <b>literal</b>',
        total=5, page_size=2, user_id=2, is_private=False, auto_delete_callback=delete)
    assert all(item['user_id'] == 2 for item in cache.values.values())
    markup = message.reply_text.await_args.kwargs['reply_markup']
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert all(len(value.encode()) <= 64 for value in callbacks)
    assert all('#2' in value for value in callbacks if value.startswith(('file#', 'sendall#')))
    delete.assert_called_once_with(reply, 10)
    await service.tasks.close()
