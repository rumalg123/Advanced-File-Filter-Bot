from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from handlers.decorators import check_ban
from handlers.commands_handlers.admin import AdminCommandHandler
from repositories.user import User,UserStatus
from test_inline_search import inline_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize('callback',[False,True])
async def test_authorization_failure_is_safe_and_does_not_enter_user_action(callback):
    protected=AsyncMock()
    @check_ban()
    async def operation(self,client,update): await protected()
    repo=SimpleNamespace(get_user=AsyncMock(side_effect=ConnectionError('private backend credentials')))
    handler=SimpleNamespace(bot=SimpleNamespace(user_repo=repo))
    update=SimpleNamespace(from_user=SimpleNamespace(id=42),reply_text=AsyncMock())
    if callback:update.answer=AsyncMock();update.data='qa'
    await operation(handler,None,update)
    protected.assert_not_awaited()
    reply=update.answer if callback else update.reply_text
    assert 'temporarily unavailable' in reply.await_args.args[0]
    assert 'private backend' not in reply.await_args.args[0]
    assert repo.get_user.await_args.kwargs['use_cache'] is False


@pytest.mark.asyncio
async def test_successful_missing_user_lookup_still_allows_first_start_registration():
    protected=AsyncMock()
    @check_ban()
    async def operation(self,client,update): await protected()
    await operation(SimpleNamespace(bot=SimpleNamespace(user_repo=SimpleNamespace(
        get_user=AsyncMock(return_value=None)))),None,SimpleNamespace(from_user=SimpleNamespace(id=42)))
    protected.assert_awaited_once()


@pytest.mark.asyncio
async def test_banned_admin_inline_query_retains_its_bypass():
    handler,query=inline_fixture();query.from_user.id=1
    handler.bot.user_repo.get_user.return_value=User(id=1,name='QA admin',status=UserStatus.BANNED)
    await handler.handle_inline_query(None,query)
    handler.bot.file_service.search_files_with_access_check.assert_awaited_once()
    handler.bot.user_repo.get_user.assert_not_awaited()
    assert len(query.answer.await_args.kwargs['results'])==1


@pytest.mark.asyncio
@pytest.mark.parametrize('method,command',[('ban_command','/ban'),('unban_command','/unban')])
async def test_moderation_read_failure_returns_retry_instead_of_claiming_user_absent(method,command):
    handler=object.__new__(AdminCommandHandler)
    handler.bot=SimpleNamespace(user_repo=SimpleNamespace(
        ban_user=AsyncMock(side_effect=ConnectionError('private credentials')),
        unban_user=AsyncMock(side_effect=ConnectionError('private credentials'))))
    message=SimpleNamespace(text=command+' 42',command=[command,'42'],reply_text=AsyncMock())
    await getattr(AdminCommandHandler,method).__wrapped__(handler,None,message)
    assert 'temporarily unavailable' in message.reply_text.await_args.args[0]
    assert 'private credentials' not in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_configured_admin_bypasses_the_ban_gate_and_unavailable_profile_store():
    protected=AsyncMock()
    @check_ban()
    async def operation(self,client,update): await protected()
    repo=SimpleNamespace(get_user=AsyncMock(side_effect=ConnectionError('QA unavailable')))
    await operation(SimpleNamespace(bot=SimpleNamespace(user_repo=repo,
        config=SimpleNamespace(ADMINS=[1]))),None,SimpleNamespace(from_user=SimpleNamespace(id=1)))
    protected.assert_awaited_once()
    repo.get_user.assert_not_awaited()
