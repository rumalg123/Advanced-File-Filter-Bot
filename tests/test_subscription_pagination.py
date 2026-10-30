from unittest.mock import AsyncMock

import pytest
from pyrogram import enums

from ban_support import Cache
from core.utils.subscription import SubscriptionManager
from handlers.callbacks_handlers.pagination import PaginationCallbackHandler
from handlers.decorators import SubscriptionRequired
from subscription_support import fixture


@pytest.mark.asyncio
async def test_old_page_button_rechecks_membership_before_reading_search_cache(monkeypatch):
    owner, query, cache = fixture('search#page#@qa#1#50#42', subscribed=False)
    cache.get = AsyncMock(return_value=None)
    prompt = AsyncMock()
    monkeypatch.setattr(SubscriptionRequired, '_send_subscription_message', prompt)
    await PaginationCallbackHandler(owner.bot).handle_search_pagination(None, query)
    owner.bot.subscription_manager.is_subscribed.assert_awaited_once()
    cache.get.assert_not_awaited()
    prompt.assert_awaited_once()


@pytest.mark.asyncio
async def test_group_preview_pagination_preserves_the_existing_subscription_exemption(monkeypatch):
    owner, query, cache = fixture('search#page#@qa#1#50#42', subscribed=False)
    query.message.chat.type = enums.ChatType.SUPERGROUP
    cache.get = AsyncMock(return_value=None)
    prompt = AsyncMock()
    monkeypatch.setattr(SubscriptionRequired, '_send_subscription_message', prompt)
    await PaginationCallbackHandler(owner.bot).handle_search_pagination(None, query)
    cache.get.assert_awaited_once()
    owner.bot.subscription_manager.is_subscribed.assert_not_awaited()
    prompt.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['page', 'first', 'last', 'next', 'prev'])
async def test_verified_subscription_retry_can_resume_pagination(monkeypatch, action):
    handler, query, _ = fixture(f'checksub#42#cb#search#{action}#@qa#1#50#42')
    replay = AsyncMock()
    monkeypatch.setattr(PaginationCallbackHandler, 'handle_search_pagination', replay)
    await handler.handle_checksub_callback(None, query)
    replay.assert_awaited_once()
    assert replay.await_args.args[-1].data == f'search#{action}#@qa#1#50#42'
    query.message.delete.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('action', [
    'cb#search#page#@'+'x'*40+'#1#50#42', 'file#'+'x'*60, 'sendall#'+'x'*60,
])
async def test_long_retry_payload_uses_an_owned_short_session(action):
    manager = SubscriptionManager()
    manager.cache = Cache()
    rows = await manager.build_subscription_buttons(None, 42,
        custom_callback_data='checksub#42#'+action)
    data = rows[-1][0].callback_data
    assert len(data.encode()) <= 64
    assert data.startswith('checksub#dl#')
    stored = manager.cache.values[data.split('#', 2)[2]]
    assert stored == {'user_id': 42, 'deeplink': action}


@pytest.mark.asyncio
async def test_unavailable_retry_storage_keeps_a_valid_general_check():
    manager = SubscriptionManager()
    manager.cache = Cache()
    manager.cache.set = AsyncMock(return_value=False)
    rows = await manager.build_subscription_buttons(None, 42,
        custom_callback_data='checksub#42#cb#'+'x'*60)
    assert rows[-1][0].callback_data == 'checksub#42#general'

