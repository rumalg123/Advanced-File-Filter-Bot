"""Resume the real welcome handler after subscription verification, including photos."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyrogram.types import User

from core.utils.helpers import MessageProxy
from handlers.commands_handlers.base import BaseCommandHandler
from subscription_support import fixture


@pytest.mark.asyncio
@pytest.mark.parametrize('with_photo', [False, True])
@pytest.mark.parametrize('delete_seconds', [0, 37])
async def test_subscription_retry_resumes_welcome_and_tracks_its_reply(
    monkeypatch, with_photo, delete_seconds
):
    handler, query, _ = fixture('checksub#42#start')
    handler.bot.config.PICS = ['qa-photo-file-id'] if with_photo else []
    handler.bot.config.MESSAGE_DELETE_SECONDS = delete_seconds
    handler.bot.config.SUPPORT_GROUP_URL = ''
    handler.bot.config.SUPPORT_GROUP_NAME = ''
    handler.bot.config.PAYMENT_LINK = 'https://example.com'
    handler.bot.config.START_MESSAGE = 'Welcome {first_name}'
    handler.bot.user_repo.is_user_exist = AsyncMock(return_value=True)
    sent = SimpleNamespace(delete=AsyncMock())
    query.message.reply_text = AsyncMock(return_value=sent)
    query.message.reply_photo = AsyncMock(return_value=sent)
    deletion = AsyncMock()
    monkeypatch.setattr(BaseCommandHandler, '_auto_delete_message', deletion)
    tasks = []

    def schedule(coroutine):
        task = asyncio.create_task(coroutine)
        tasks.append(task)
        return task

    handler.bot.handler_manager = SimpleNamespace(create_auto_delete_task=schedule)

    try:
        await handler.handle_checksub_callback(None, query)
    finally:
        if tasks:
            await asyncio.gather(*tasks)

    if with_photo:
        query.message.reply_photo.assert_awaited_once()
        kwargs = query.message.reply_photo.await_args.kwargs
        assert kwargs['photo'] == 'qa-photo-file-id'
        assert kwargs['caption'] == 'Welcome QA'
        assert kwargs['reply_markup'].inline_keyboard
        query.message.reply_text.assert_not_awaited()
    else:
        query.message.reply_text.assert_awaited_once()
        assert query.message.reply_text.await_args.args[0] == 'Welcome QA'
        query.message.reply_photo.assert_not_awaited()

    if delete_seconds:
        deletion.assert_awaited_once_with(sent, delete_seconds)
    else:
        deletion.assert_not_awaited()
    query.answer.assert_awaited_once()
    query.message.delete.assert_awaited_once()
    sent.delete.assert_not_awaited()
    # Both the callback and resumed command retain their membership checks.
    assert handler.bot.subscription_manager.is_subscribed.await_count == 2


@pytest.mark.asyncio
async def test_callback_photo_proxy_keeps_clicker_and_forwards_reply_arguments():
    _, query, _ = fixture()
    query.message.from_user = User(id=99, is_bot=True, first_name='Bot')
    sent = object()
    query.message.reply_photo = AsyncMock(return_value=sent)
    proxy = MessageProxy.from_callback_query(query, text='/start', command=['/start'])

    result = await proxy.reply_photo(
        'qa-photo-file-id', caption='Welcome', protect_content=True
    )

    assert result is sent
    assert proxy.from_user is query.from_user
    assert proxy.chat is query.message.chat
    assert proxy.text == '/start' and proxy.command == ['/start']
    query.message.reply_photo.assert_awaited_once_with(
        'qa-photo-file-id', caption='Welcome', protect_content=True
    )


@pytest.mark.asyncio
async def test_callback_photo_proxy_preserves_the_actual_send_exception():
    _, query, _ = fixture()
    error = RuntimeError('QA photo send failure')
    query.message.reply_photo = AsyncMock(side_effect=error)
    proxy = MessageProxy.from_callback_query(query)

    with pytest.raises(RuntimeError) as caught:
        await proxy.reply_photo(photo='qa-photo-file-id')
    assert caught.value is error


@pytest.mark.asyncio
async def test_contextless_photo_proxy_matches_existing_noop_reply_contract():
    _, query, _ = fixture()
    query.message = None
    proxy = MessageProxy.from_callback_query(query)

    assert await proxy.reply_photo(photo='qa-photo-file-id') is None
