"""BUG-116: request keywords remain literal, bounded text in admin messages."""
import html
import re

import pytest

import handlers.request as module
from handlers.request import RequestHandler
from request_support import request_fixture, callback_fixture, direct_api


@pytest.mark.asyncio
@pytest.mark.parametrize('keyword',['<b>Title & Co</b>','<not-a-tag> movie','x & '*1200])
async def test_forwarded_keyword_is_escaped_and_display_is_bounded(monkeypatch,keyword):
    monkeypatch.setattr(module.telegram_api,'call_api',direct_api)
    handler,message,client=request_fixture()
    assert await handler._forward_request_to_admins(client,message,keyword)
    output=client.send_message.await_args.args[1]
    assert html.escape(keyword[:500]) in output
    assert len(html.unescape(re.sub(r'<[^>]+>','',output)))<1500


@pytest.mark.asyncio
async def test_warning_log_keyword_cannot_add_html_markup(monkeypatch):
    monkeypatch.setattr(module.telegram_api,'call_api',direct_api)
    handler,message,client=request_fixture()
    message.text='#request <b>Injected & text</b>'
    handler.bot.user_repo.track_request.return_value=(False,'Daily request limit',False,True)
    await RequestHandler.handle_request_message.__wrapped__(handler,client,message)
    output=client.send_message.await_args.args[1]
    assert '&lt;b&gt;Injected &amp; text&lt;/b&gt;' in output


@pytest.mark.asyncio
async def test_handled_card_preserves_literal_rendered_keyword_during_edit(monkeypatch):
    monkeypatch.setattr(module.telegram_api,'call_api',direct_api)
    handler,query,client=callback_fixture()
    query.message.text='New request: <unknown> & literal content'
    await handler.handle_request_callback(client,query)
    output=query.message.edit_text.await_args.args[0]
    assert html.escape(query.message.text) in output
    assert 'Action Taken' in output
