"""Bulk deletion confirmations are bound to chat/actor and consumed once."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from pyrogram import enums

import handlers.callbacks_handlers.filter as callbacks
from handlers.callbacks_handlers.filter import FilterCallBackHandler


def fixture(data, *, actor=12, owner=True, chat=-1001):
    handler=object.__new__(FilterCallBackHandler)
    pending={'group_id':-1001,'user_id':12,'chat_id':-1001}
    cache=NS(get=AsyncMock(return_value=pending),delete_if_value=AsyncMock(return_value=True))
    handler.bot=NS(config=NS(ADMINS=[]),cache=cache,user_repo=NS(get_user=AsyncMock(return_value=None)),
                   filter_service=NS(delete_all_filters=AsyncMock(return_value=True)))
    query=NS(data=data,from_user=NS(id=actor),answer=AsyncMock(),
             message=NS(chat=NS(id=chat,type=enums.ChatType.SUPERGROUP),delete=AsyncMock(),edit_text=AsyncMock(),reply_to_message=None))
    return handler,query


@pytest.mark.asyncio
async def test_non_requester_cannot_cancel_owner_confirmation(monkeypatch):
    handler,query=fixture('delallcancel#'+'a'*24,actor=13)
    monkeypatch.setattr(callbacks,'is_group_owner',AsyncMock(return_value=False))
    await handler.handle_delall_cancel_callback(None,query)
    query.message.delete.assert_not_awaited()
    handler.bot.cache.delete_if_value.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancelled_or_used_confirmation_cannot_delete_new_filters(monkeypatch):
    handler,query=fixture('delallconfirm#'+'a'*24)
    handler.bot.cache.get.return_value=None
    monkeypatch.setattr(callbacks,'is_group_owner',AsyncMock(return_value=True))
    await handler.handle_delall_confirm_callback(None,query)
    handler.bot.filter_service.delete_all_filters.assert_not_awaited()
    query.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_confirmation_rejects_cross_chat_replay(monkeypatch):
    handler,query=fixture('delallconfirm#'+'a'*24,chat=-1002)
    monkeypatch.setattr(callbacks,'is_group_owner',AsyncMock(return_value=True))
    await handler.handle_delall_confirm_callback(None,query)
    handler.bot.filter_service.delete_all_filters.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_confirmations_have_one_winner(monkeypatch):
    handler,query=fixture('delallconfirm#'+'a'*24)
    handler.bot.cache.delete_if_value.side_effect=[True,False]
    monkeypatch.setattr(callbacks,'is_group_owner',AsyncMock(return_value=True))
    monkeypatch.setattr(callbacks.telegram_api,'call_api',AsyncMock(return_value=NS(title='QA')))
    await asyncio.gather(handler.handle_delall_confirm_callback(None,query),handler.handle_delall_confirm_callback(None,query))
    handler.bot.filter_service.delete_all_filters.assert_awaited_once_with('-1001')


@pytest.mark.asyncio
async def test_legacy_unbound_cancel_cannot_delete_messages():
    handler,query=fixture('delallcancel',actor=13)
    await handler.handle_delall_cancel_callback(None,query)
    query.message.delete.assert_not_awaited()
