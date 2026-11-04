import html
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from handlers.decorators import check_ban
from handlers.commands_handlers.admin import AdminCommandHandler
from repositories.user import User,UserStatus
from favorites_recent_support import storage
from ban_support import user_repository


@pytest.mark.asyncio
@pytest.mark.parametrize('callback',[False,True])
async def test_ban_reason_is_literal_on_html_and_plain_text_surfaces(callback):
    reason='QA <tag> & reason'
    repo=SimpleNamespace(get_user=AsyncMock(return_value=User(id=42,name='QA',status=UserStatus.BANNED,ban_reason=reason)))
    handler=SimpleNamespace(bot=SimpleNamespace(user_repo=repo,config=SimpleNamespace(ADMINS=[1])))
    update=SimpleNamespace(from_user=SimpleNamespace(id=42),reply_text=AsyncMock())
    if callback:update.data='qa';update.answer=AsyncMock()
    @check_ban()
    async def protected(*args):raise AssertionError('Banned action must not run')
    await protected(handler,None,update)
    actual=(update.answer if callback else update.reply_text).await_args.args[0]
    assert (reason if callback else html.escape(reason)) in actual


@pytest.mark.asyncio
async def test_long_unicode_ban_reason_fits_a_callback_answer():
    repo=SimpleNamespace(get_user=AsyncMock(return_value=User(id=42,name='QA',status=UserStatus.BANNED,ban_reason='🚫'*1000)))
    handler=SimpleNamespace(bot=SimpleNamespace(user_repo=repo))
    update=SimpleNamespace(from_user=SimpleNamespace(id=42),data='qa',answer=AsyncMock())
    @check_ban()
    async def protected(*args):raise AssertionError('Banned action must not run')
    await protected(handler,None,update)
    answer=update.answer.await_args.args[0]
    assert len(answer.encode())<=200 and 'banned' in answer.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_repeat_ban_response_escapes_stored_name_and_reason(storage,monkeypatch):
    repo,_,db=await user_repository(storage,monkeypatch,status=UserStatus.BANNED)
    await db.users.update_one({'_id':42},{'$set':{'name':'<name> &','ban_reason':'<reason> &'}})
    ok,message,_=await repo.ban_user(42,'QA')
    assert not ok and html.escape('<name> &') in message and html.escape('<reason> &') in message


@pytest.mark.asyncio
@pytest.mark.parametrize('verb',['ban','unban'])
async def test_moderation_notifications_and_log_keep_name_and_reason_literal(monkeypatch,verb):
    handler=object.__new__(AdminCommandHandler)
    user=User(id=42,name='<name> &')
    handler.bot=SimpleNamespace(config=SimpleNamespace(LOG_CHANNEL=-100123),
        cache_invalidator=SimpleNamespace(invalidate_user_cache=AsyncMock()),
        user_repo=SimpleNamespace(ban_user=AsyncMock(return_value=(True,'OK',user)),unban_user=AsyncMock(return_value=(True,'OK',user))))
    handler._notify_user=AsyncMock(return_value=True)
    api=AsyncMock();monkeypatch.setattr('handlers.commands_handlers.admin.telegram_api.call_api',api)
    reason='QA <tag> &'
    message=SimpleNamespace(text=f'/ban 42 "{reason}"',command=['/unban','42'],
        from_user=SimpleNamespace(id=1,mention='QA admin'),reply_text=AsyncMock())
    await getattr(AdminCommandHandler,verb+'_command').__wrapped__(handler,SimpleNamespace(send_message=AsyncMock()),message)
    log=api.await_args.args[2]
    assert html.escape(user.name) in log
    if verb=='ban':
        assert html.escape(reason) in log and html.escape(reason) in handler._notify_user.await_args.args[2]
