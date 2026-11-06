"""Alert callbacks preserve their source group and recheck private access."""
import hashlib
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from pyrogram import enums
from pyrogram.types import InlineKeyboardButton

import core.services.filter as filters
from core.services.filter import FilterService
from handlers.callbacks_handlers.filter import FilterCallBackHandler


@pytest.mark.asyncio
@pytest.mark.parametrize('keyword', ['qa', 'long keyword ' * 20, '你好世界' * 30])
async def test_delivered_alert_data_has_source_and_fits_telegram(monkeypatch, keyword):
    svc = FilterService(NS(), NS(), NS(), NS())
    payload = svc.serialize_buttons([[InlineKeyboardButton('Alert', callback_data='alertmessage:0:'+keyword)]])
    api = AsyncMock();monkeypatch.setattr(filters.telegram_api, 'call_api', api)
    msg = NS(id=7, reply_to_message=None, chat=NS(id=12, type=enums.ChatType.PRIVATE))
    assert await svc.send_filter_response(NS(send_message=object()),msg,'body',payload,"['hello']",'None',group_id='-1001')
    callback = api.await_args.kwargs['reply_markup'].inline_keyboard[0][0].callback_data
    assert callback.startswith('filteralert:-1001:0:')
    assert len(callback.encode())<=64


def callback_fixture(data, private=False):
    handler = object.__new__(FilterCallBackHandler)
    svc = NS(get_all_filters=AsyncMock(return_value=['qa']), get_filter=AsyncMock(return_value=('body','[]',"['first', 'last']",'None')))
    handler.bot = NS(config=NS(ADMINS=[]),user_repo=NS(get_user=AsyncMock(return_value=None)),filter_service=svc,
                     connection_service=NS(can_manage_group=AsyncMock(return_value=True)))
    query = NS(data=data, from_user=NS(id=12), answer=AsyncMock(),message=NS(chat=NS(id=12 if private else -1001,type=enums.ChatType.PRIVATE if private else enums.ChatType.SUPERGROUP)))
    return handler,query


@pytest.mark.asyncio
@pytest.mark.parametrize('private',[False,True])
async def test_source_scoped_alert_works_in_groups_and_connected_private_chat(private):
    digest=hashlib.sha256(b'qa').hexdigest()[:16]
    handler,query=callback_fixture('filteralert:-1001:0:'+digest, private)
    await handler.handle_filter_alert_callback(None,query)
    assert query.answer.await_args.args[0]=='first'
    handler.bot.filter_service.get_filter.assert_awaited_once_with('-1001','qa')


@pytest.mark.asyncio
async def test_demoted_private_user_cannot_read_old_alert():
    digest=hashlib.sha256(b'qa').hexdigest()[:16]
    handler,query=callback_fixture('filteralert:-1001:0:'+digest,True)
    handler.bot.connection_service.can_manage_group.return_value=False
    await handler.handle_filter_alert_callback(None,query)
    handler.bot.filter_service.get_filter.assert_not_awaited()


@pytest.mark.asyncio
async def test_negative_legacy_alert_index_is_rejected():
    handler,query=callback_fixture('alertmessage:-1:qa')
    await handler.handle_filter_alert_callback(None,query)
    assert query.answer.await_args.args[0]!='last'
    handler.bot.filter_service.get_filter.assert_not_awaited()


@pytest.mark.asyncio
async def test_scoped_alert_cannot_be_replayed_from_another_group():
    digest=hashlib.sha256(b'qa').hexdigest()[:16]
    handler,query=callback_fixture('filteralert:-1002:0:'+digest)
    await handler.handle_filter_alert_callback(None,query)
    handler.bot.filter_service.get_filter.assert_not_awaited()
