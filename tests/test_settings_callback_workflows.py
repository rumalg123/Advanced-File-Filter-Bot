from types import SimpleNamespace
from unittest.mock import AsyncMock
from pyrogram.errors import MessageNotModified

import pytest
from handlers.commands_handlers.bot_settings import BotSettingsHandler


@pytest.mark.asyncio
@pytest.mark.parametrize('data',['bset_view_CACHE_TIME_0','bset_edit_CACHE_TIME','bset_back','bset_close','bset_page_1'])
async def test_settings_navigation_acknowledges_callback_before_slow_work(data):
    handler=object.__new__(BotSettingsHandler)
    handler.bot=SimpleNamespace(config=SimpleNamespace(ADMINS=[1]))
    handler.session_manager=SimpleNamespace(cancel_edit_session=AsyncMock())
    query=SimpleNamespace(from_user=SimpleNamespace(id=1),data=data,
        answer=AsyncMock(),message=SimpleNamespace(delete=AsyncMock()))
    async def display(*args):
        query.answer.assert_awaited_once()
    handler.show_setting_details=display;handler.start_edit_session=display;handler.show_settings_menu=display
    query.message.delete.side_effect=display
    await handler.settings_callback(None,query)
    query.answer.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('reset', [False, True])
async def test_repeating_an_already_saved_setting_still_confirms_success(reset):
    handler = object.__new__(BotSettingsHandler)
    handler.bot = SimpleNamespace()
    handler.settings_service = SimpleNamespace(
        update_setting=AsyncMock(return_value=True),
        reset_to_default=AsyncMock(return_value=True),
        get_all_settings=AsyncMock(return_value={'FEATURE_FAVORITES': {
            'value': True, 'default': False, 'type': 'bool', 'description': 'QA favorites',
        }}))
    handler.invalidate_related_caches = AsyncMock()
    query = SimpleNamespace(answer=AsyncMock(), message=SimpleNamespace(
        edit_text=AsyncMock(side_effect=MessageNotModified())))
    if reset:
        await handler.reset_to_default(query, 'FEATURE_FAVORITES')
        handler.settings_service.reset_to_default.assert_awaited_once()
    else:
        await handler.update_boolean_setting(query, 'FEATURE_FAVORITES', True)
        handler.settings_service.update_setting.assert_awaited_once()
    query.answer.assert_awaited_once()
    assert 'Success' in query.answer.await_args.args[0]
    assert 'MESSAGE_NOT_MODIFIED' not in query.answer.await_args.args[0]
