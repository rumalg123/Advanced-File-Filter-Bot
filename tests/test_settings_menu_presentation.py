"""Settings remain discoverable across sorted pages and existing callbacks."""
import math
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from core.services.bot_settings import BotSettingsService
from handlers.commands_handlers.bot_settings import BotSettingsHandler


def handler_with(settings):
    handler = object.__new__(BotSettingsHandler)
    handler.bot = NS(config=NS(ADMINS=[1]))
    handler.settings_service = NS(get_all_settings=AsyncMock(return_value=settings))
    handler.session_manager = None
    return handler


def setting_buttons(message):
    markup = message.edit_text.await_args.kwargs['reply_markup']
    return [button for row in markup.inline_keyboard for button in row
            if button.callback_data.startswith('bset_view_')]


@pytest.mark.asyncio
async def test_all_settings_sort_by_visible_label_across_pages_without_losing_callbacks():
    settings = {key: {} for key in reversed(BotSettingsService.SETTINGS_METADATA)}
    handler = handler_with(settings)
    message = NS(edit_text=AsyncMock())
    labels, keys = [], []
    for page in range(math.ceil(len(settings) / 8)):
        await handler.show_settings_menu(message, page)
        buttons = setting_buttons(message)
        assert 1 <= len(buttons) <= 8
        for button in buttons:
            key, callback_page = button.callback_data.removeprefix('bset_view_').rsplit('_', 1)
            assert int(callback_page) == page
            assert len(button.callback_data.encode()) <= 64
            assert button.text == handler._get_display_name(key)
            keys.append(key)
            labels.append(button.text)
    assert labels == sorted(labels, key=str.casefold)
    assert len(set(labels)) == len(labels)
    assert len(keys) == len(set(keys)) == len(settings)
    assert set(keys) == set(settings)


@pytest.mark.asyncio
async def test_existing_database_setting_shows_current_purpose_and_configuration_key():
    repo = NS(get_all_settings=AsyncMock(return_value={
        'INDEX_REQ_CHANNEL': NS(value=-1001, description='STALE DESCRIPTION'),
    }))
    service = BotSettingsService(repo, NS())
    service.owner_registry_policy = AsyncMock(return_value={
        'editable': False, 'default': False, 'bound': False, 'note': 'QA single source',
    })
    handler = handler_with({})
    handler.settings_service = service
    message = NS(edit_text=AsyncMock())
    await handler.show_setting_details(message, 'INDEX_REQ_CHANNEL')
    text = message.edit_text.await_args.args[0]
    assert 'Setting: Index Requests Channel' in text
    assert '<code>INDEX_REQ_CHANNEL</code>' in text
    assert 'approval inbox' in text
    assert 'automatically indexed' in text
    assert 'STALE DESCRIPTION' not in text
    assert '<code>-1001</code>' in text


@pytest.mark.asyncio
async def test_select_and_back_returns_to_the_setting_on_its_sorted_page():
    settings = {key: {'value': metadata['default'], **metadata}
                for key, metadata in BotSettingsService.SETTINGS_METADATA.items()}
    handler = handler_with(settings)
    key = 'INDEX_REQ_CHANNEL'
    message = NS(edit_text=AsyncMock())
    found = None
    for page in range(math.ceil(len(settings) / 8)):
        await handler.show_settings_menu(message, page)
        found = next((b for b in setting_buttons(message)
                      if b.callback_data == f'bset_view_{key}_{page}'), None)
        if found:
            break
    assert found is not None
    query = NS(from_user=NS(id=1), data=found.callback_data,
               answer=AsyncMock(), message=message)
    await handler.settings_callback(None, query)
    assert 'Setting: Index Requests Channel' in message.edit_text.await_args.args[0]
    query.data = 'bset_back'
    await handler.settings_callback(None, query)
    assert found.callback_data in [b.callback_data for b in setting_buttons(message)]
    query.answer.assert_awaited()
