from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock

import pytest
from pyrogram.types import CallbackQuery

from handlers.commands_handlers.database import DatabaseCommandHandler


@pytest.mark.asyncio
@pytest.mark.parametrize('action,method',[
    ('db_refresh_stats','_refresh_database_stats'),
    ('db_detailed_info','_show_detailed_info'),
    ('db_stats','_show_database_stats'),
    ('db_refresh_info','_refresh_database_info'),
])
async def test_database_callbacks_enforce_admin_permission_before_work(action,method):
    handler=object.__new__(DatabaseCommandHandler)
    handler.bot=SimpleNamespace(config=SimpleNamespace(ADMINS=[1]))
    for name in ['_refresh_database_stats','_show_detailed_info','_show_database_stats','_refresh_database_info']:
        setattr(handler,name,AsyncMock())
    query=Mock(spec=CallbackQuery)
    query.from_user=SimpleNamespace(id=2)
    query.data=action;query.answer=AsyncMock()
    await handler.handle_database_callback(None,query)
    getattr(handler,method).assert_not_awaited()
    query.answer.assert_awaited_once()
    assert 'denied' in query.answer.await_args.args[0].lower() or 'admin' in query.answer.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_admin_database_callback_keeps_its_action():
    handler=object.__new__(DatabaseCommandHandler)
    handler.bot=SimpleNamespace(config=SimpleNamespace(ADMINS=[1]))
    handler._show_database_stats=AsyncMock()
    query=Mock(spec=CallbackQuery);query.from_user=SimpleNamespace(id=1)
    query.data='db_stats';query.answer=AsyncMock()
    await handler.handle_database_callback(None,query)
    handler._show_database_stats.assert_awaited_once_with(query)


@pytest.mark.asyncio
@pytest.mark.parametrize('decorator',['admin_only','owner_only','private_only','auth_user_only'])
async def test_permission_denial_callback_is_plain_text(decorator):
    from core.utils.validators import ValidationDecorators
    from pyrogram import enums
    handler=SimpleNamespace(bot=SimpleNamespace(config=SimpleNamespace(ADMINS=[1],AUTH_USERS=[])))
    query=Mock(spec=CallbackQuery);query.from_user=SimpleNamespace(id=2)
    query.message=SimpleNamespace(chat=SimpleNamespace(type=enums.ChatType.SUPERGROUP))
    query.answer=AsyncMock()
    method=AsyncMock()
    await getattr(ValidationDecorators,decorator)(method)(handler,None,query)
    method.assert_not_awaited()
    query.answer.assert_awaited_once()
    assert '<b>' not in query.answer.await_args.args[0]
