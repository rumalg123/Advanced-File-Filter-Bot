"""BUG-115: only a completed empty lookup may enter the missing-content flow."""
from unittest.mock import AsyncMock

import pytest

from core.database.errors import SEARCH_RETRY_MESSAGE
from handlers.request import RequestHandler
from request_support import request_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['backend', 'access', 'exception', 'render', 'shutdown'])
async def test_incomplete_or_denied_search_never_creates_or_forwards_request(failure):
    handler, message, client = request_fixture()
    reason = SEARCH_RETRY_MESSAGE
    if failure in ('backend','access'):
        reason = SEARCH_RETRY_MESSAGE if failure=='backend' else 'Daily limit reached'
        handler.bot.file_service.search_files_with_access_check.return_value = ([],0,0,False,reason)
    elif failure=='exception':
        handler.bot.file_service.search_files_with_access_check.side_effect = RuntimeError('private backend details')
    elif failure=='render':
        handler.bot.file_service.search_files_with_access_check.return_value = ([object()],0,1,True,None)
        handler.search_results_service.send_results.return_value = False
    else:
        handler._shutdown.set()
    handler._forward_request_to_admins = AsyncMock(return_value=True)
    await RequestHandler.handle_request_message.__wrapped__(handler, client, message)
    handler.bot.feature_repo.create_content_request.assert_not_awaited()
    handler._forward_request_to_admins.assert_not_awaited()
    if failure!='shutdown':
        assert reason in message.reply_text.await_args.args[0]
        assert 'private backend details' not in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('found',[True,False])
async def test_successful_search_keeps_found_and_missing_routes_distinct(found):
    handler,message,client=request_fixture()
    handler.bot.file_service.search_files_with_access_check.return_value=([object()] if found else [],0,int(found),True,None)
    handler._forward_request_to_admins=AsyncMock(return_value=True)
    await RequestHandler.handle_request_message.__wrapped__(handler,client,message)
    assert handler._forward_request_to_admins.await_count==int(not found)
    assert handler.bot.feature_repo.create_content_request.await_count==int(not found)
