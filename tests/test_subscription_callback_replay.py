from unittest.mock import AsyncMock

import pytest
from pyrogram.types import CallbackQuery

from core.utils.validators import is_private_chat
from subscription_support import fixture


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['help', 'about'])
async def test_verified_user_menu_retry_replays_a_real_callback(action):
    handler, query, _ = fixture('checksub#42#cb#'+action)
    await handler.handle_checksub_callback(None, query)
    query.message.edit_text.assert_awaited_once()
    query.message.delete.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('action,method', [('file#qa-file', 'handle_file_callback'),
    ('sendall#qa-search', 'handle_sendall_callback')])
async def test_delivery_retry_keeps_callback_type_actor_and_private_chat(monkeypatch, action, method):
    handler, query, _ = fixture('checksub#42#'+action)
    replay = AsyncMock()
    monkeypatch.setattr('handlers.callbacks_handlers.file.FileCallbackHandler.'+method, replay)
    await handler.handle_checksub_callback(None, query)
    replayed = replay.await_args.args[-1]
    assert isinstance(replayed, CallbackQuery)
    assert replayed.from_user.id == 42 and replayed.data == action
    assert is_private_chat(replayed)


@pytest.mark.asyncio
@pytest.mark.parametrize('uid,authorized', [(1, False), (42, True)])
async def test_admin_owner_and_authorized_user_subscription_exemptions_remain(uid, authorized):
    handler, query, _ = fixture(f'checksub#{uid}#general', uid=uid, subscribed=False)
    if authorized:
        handler.bot.config.AUTH_USERS = [uid]
    await handler.handle_checksub_callback(None, query)
    handler.bot.subscription_manager.is_subscribed.assert_not_awaited()
    assert 'verified' in query.answer.await_args.args[0].lower()
