from unittest.mock import AsyncMock

import pytest

from handlers.commands_handlers.user import UserCommandHandler
from subscription_support import fixture


@pytest.mark.asyncio
@pytest.mark.parametrize('subscribed', [False, True])
async def test_inline_subscribe_entry_resumes_welcome_instead_of_decoding_a_file(monkeypatch, subscribed):
    original, query, _ = fixture(subscribed=subscribed)
    bot = original.bot
    bot.user_repo.is_user_exist = AsyncMock(return_value=True)
    bot.config.SUPPORT_GROUP_URL = ''
    bot.config.SUPPORT_GROUP_NAME = ''
    bot.config.PAYMENT_LINK = 'https://example.invalid/qa'
    message = query.message
    message.from_user = query.from_user
    message.command = ['start', 'subscribe']
    message.text = '/start subscribe'
    handler = UserCommandHandler(bot)
    handler._send_subscription_message_for_deeplink = AsyncMock()
    handler._reply_text_with_auto_delete = AsyncMock()
    file_replay = AsyncMock()
    monkeypatch.setattr('handlers.deeplink.DeepLinkHandler.handle_deep_link_internal', file_replay)
    await handler.start_command(None, message)
    file_replay.assert_not_awaited()
    if subscribed:
        handler._reply_text_with_auto_delete.assert_awaited_once()
    else:
        assert handler._send_subscription_message_for_deeplink.await_args.args[-1] == 'start'
