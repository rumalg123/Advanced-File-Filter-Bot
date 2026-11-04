import pytest
from pyrogram.errors import MessageNotModified

from bsettings_support import fixture


@pytest.mark.asyncio
async def test_command_replies_without_trying_to_edit_the_owners_message():
    handler, message, _ = fixture()
    await handler.bsetting_command(None, message)
    message.edit_text.assert_not_awaited()
    message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_callback_updates_existing_bot_menu():
    handler, message, query = fixture()
    query.data = 'bset_page_0'
    await handler.settings_callback(None, query)
    message.edit_text.assert_awaited_once()
    message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_unchanged_menu_does_not_create_duplicate_or_log_failure(caplog):
    handler, message, query = fixture()
    query.data = 'bset_page_0'
    message.edit_text.side_effect = MessageNotModified()
    await handler.settings_callback(None, query)
    message.reply_text.assert_not_awaited()
    assert 'Failed to edit settings menu' not in caplog.text


@pytest.mark.asyncio
async def test_uneditable_bot_menu_retains_reply_fallback():
    handler, message, query = fixture()
    query.data = 'bset_back'
    message.edit_text.side_effect = RuntimeError('QA deleted bot message')
    await handler.settings_callback(None, query)
    message.reply_text.assert_awaited_once()
