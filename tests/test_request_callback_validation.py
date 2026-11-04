"""BUG-117: malformed or unauthorized request actions never notify users."""
import pytest

import handlers.request as module
from request_support import callback_fixture,direct_api


@pytest.mark.asyncio
@pytest.mark.parametrize('data',[
    'req_action#done#abc#10', 'req_action#done#7#abc',
    'req_action#done#0#10', 'req_action#done#-7#10',
    'req_action#done#7#0', 'req_action#done#7#-10',
    'req_action#done#9223372036854775808#10',
    'req_action#done#7#2147483648',
    'req_action#done#7#10#extra', 'wrong#done#7#10',
    'req_action#done#7', 'req_action#unknown#7#10',
])
async def test_invalid_callback_answers_without_database_or_telegram_work(monkeypatch,data):
    monkeypatch.setattr(module.telegram_api,'call_api',direct_api)
    handler,query,client=callback_fixture(data)
    await handler.handle_request_callback(client,query)
    query.answer.assert_awaited_once()
    assert 'invalid' in query.answer.await_args.args[0].lower()
    handler.bot.feature_repo.get_content_request.assert_not_awaited()
    client.send_message.assert_not_awaited()
    query.message.edit_text.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('actor',[7,8,None])
async def test_only_configured_admin_can_take_request_actions(monkeypatch,actor):
    monkeypatch.setattr(module.telegram_api,'call_api',direct_api)
    handler,query,client=callback_fixture(admin_id=actor)
    if actor is None:query.from_user=None
    await handler.handle_request_callback(client,query)
    assert 'only bot admins' in query.answer.await_args.args[0].lower()
    handler.bot.feature_repo.get_content_request.assert_not_awaited()
    client.send_message.assert_not_awaited()
