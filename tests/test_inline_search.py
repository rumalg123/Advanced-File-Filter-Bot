"""Bounded QA round: inline query access, response deadlines and pagination."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyrogram.errors import QueryIdInvalid

from core.database.errors import SEARCH_RETRY_MESSAGE
from handlers.search import SearchHandler
from repositories.media import FileType, MediaFile
from repositories.user import UserStatus


def media(index=1):
    return MediaFile(file_unique_id=f'qa-unique-{index}', file_id=f'qa-file-{index}',
        file_ref=f'qa-ref-{index}', file_name=f'QA Group {index}.txt', file_size=10,
        file_type=FileType.DOCUMENT, mime_type='text/plain', caption=None)


def inline_fixture():
    handler = object.__new__(SearchHandler)
    handler.bot = SimpleNamespace(
        config=SimpleNamespace(ADMINS=[1], AUTH_USERS=[], DISABLE_PREMIUM=True,
            AUTH_CHANNEL=None, AUTH_GROUPS=[], CUSTOM_FILE_CAPTION=None,
            BATCH_FILE_CAPTION=None, KEEP_ORIGINAL_CAPTION=False),
        app_rate_limiter=SimpleNamespace(check_rate_limit=AsyncMock(return_value=(True, 0))),
        user_repo=SimpleNamespace(get_user=AsyncMock(return_value=SimpleNamespace(status=UserStatus.ACTIVE))),
        subscription_manager=SimpleNamespace(is_subscribed=AsyncMock(return_value=True)),
        file_service=SimpleNamespace(search_files_with_access_check=AsyncMock(
            return_value=([media()], 10, 11, True, None))))
    query = SimpleNamespace(from_user=SimpleNamespace(id=2), query='QA Group', offset='', answer=AsyncMock())
    return handler, query


@pytest.mark.asyncio
@pytest.mark.parametrize('gate', ['unknown-user', 'rate-limit', 'banned', 'premium', 'subscription', 'empty', 'short'])
async def test_inline_gates_answer_without_searching(monkeypatch, gate):
    handler, query = inline_fixture()
    if gate == 'unknown-user':
        query.from_user = None
    elif gate == 'rate-limit':
        handler.bot.app_rate_limiter.check_rate_limit.return_value = (False, 3)
    elif gate == 'banned':
        handler.bot.user_repo.get_user.return_value = SimpleNamespace(
            status=UserStatus.BANNED, ban_reason='QA reason', updated_at=None)
        monkeypatch.setattr('handlers.search.MessageHelper.get_ban_message', lambda config: '{reason} {date}')
    elif gate == 'premium':
        handler.bot.config.DISABLE_PREMIUM = False
    elif gate == 'subscription':
        handler.bot.config.AUTH_CHANNEL = -1001
        handler.bot.subscription_manager.is_subscribed.return_value = False
    else:
        query.query = '' if gate == 'empty' else 'a'
    await handler.handle_inline_query(None, query)
    query.answer.assert_awaited_once()
    assert query.answer.await_args.kwargs['results'] == []
    handler.bot.file_service.search_files_with_access_check.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('identity', ['admin', 'authorized', 'subscribed'])
async def test_inline_subscription_exemptions_and_member_access(identity):
    handler, query = inline_fixture()
    handler.bot.config.AUTH_CHANNEL = -1001
    if identity == 'admin':
        query.from_user.id = 1
        handler.bot.config.DISABLE_PREMIUM = False
    elif identity == 'authorized':
        handler.bot.config.AUTH_USERS = [2]
    await handler.handle_inline_query(None, query)
    assert len(query.answer.await_args.kwargs['results']) == 1
    if identity in ['admin', 'authorized']:
        handler.bot.subscription_manager.is_subscribed.assert_not_awaited()
    else:
        handler.bot.subscription_manager.is_subscribed.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('offset,next_offset', [('', 10), ('10', 0)])
async def test_inline_results_are_personal_and_keep_next_page_offsets(offset, next_offset):
    handler, query = inline_fixture()
    query.offset = offset
    handler.bot.file_service.search_files_with_access_check.return_value = ([media()], next_offset, 11, True, None)
    await handler.handle_inline_query(None, query)
    answer = query.answer.await_args.kwargs
    assert answer['is_personal'] is True
    assert answer['next_offset'] == (str(next_offset) if next_offset else '')
    assert len(answer['results']) == 1
    assert len(answer['results'][0].id.encode()) <= 64
    call = handler.bot.file_service.search_files_with_access_check.await_args.kwargs
    assert call['offset'] == int(offset or 0) and call['limit'] == 10


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['empty', 'unavailable', 'exception', 'bad-offset'])
async def test_inline_empty_and_error_results_do_not_publish_media(kind):
    handler, query = inline_fixture()
    operation = handler.bot.file_service.search_files_with_access_check
    if kind == 'exception':
        operation.side_effect = ConnectionError('fixture private backend error')
    elif kind == 'bad-offset':
        query.offset = 'not-a-number'
    else:
        operation.return_value = ([], 0, 0, kind == 'empty', None if kind == 'empty' else SEARCH_RETRY_MESSAGE)
    await handler.handle_inline_query(None, query)
    answer = query.answer.await_args.kwargs
    assert answer['results'] == []
    assert 'private backend' not in answer['switch_pm_text']
    if kind == 'unavailable':
        assert answer['switch_pm_text'] == SEARCH_RETRY_MESSAGE


@pytest.mark.asyncio
async def test_inline_gate_database_error_still_answers_safely():
    handler, query = inline_fixture()
    handler.bot.user_repo.get_user.side_effect = ConnectionError('fixture private backend error')
    await handler.handle_inline_query(None, query)
    query.answer.assert_awaited_once()
    assert query.answer.await_args.kwargs['results'] == []
    assert 'private backend' not in query.answer.await_args.kwargs['switch_pm_text']


@pytest.mark.asyncio
async def test_expired_inline_error_reply_does_not_escape_dispatcher():
    handler, query = inline_fixture()
    handler.bot.file_service.search_files_with_access_check.side_effect = ConnectionError('fixture error')
    query.answer.side_effect = QueryIdInvalid()
    await handler.handle_inline_query(None, query)


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['user-state', 'search'])
async def test_inline_request_has_a_deadline_and_cancels_slow_work(monkeypatch, stage):
    handler, query = inline_fixture()
    monkeypatch.setattr(SearchHandler, 'INLINE_QUERY_TIMEOUT', .02, raising=False)
    cancelled = asyncio.Event()

    async def blocked(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    operation = (handler.bot.user_repo.get_user if stage == 'user-state'
                 else handler.bot.file_service.search_files_with_access_check)
    operation.side_effect = blocked
    await asyncio.wait_for(handler.handle_inline_query(None, query), timeout=.5)
    assert cancelled.is_set()
    query.answer.assert_awaited_once()
    answer = query.answer.await_args.kwargs
    assert answer['results'] == [] and answer['cache_time'] == 0
    assert answer['switch_pm_text'] == SEARCH_RETRY_MESSAGE



@pytest.mark.asyncio
@pytest.mark.parametrize('privileged',[False,True])
async def test_inline_cache_does_not_keep_normal_user_access_after_status_changes(privileged):
    handler,query=inline_fixture()
    if privileged:query.from_user.id=1
    await handler.handle_inline_query(None,query)
    assert query.answer.await_args.kwargs['cache_time']==(30 if privileged else 0)
