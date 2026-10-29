from types import SimpleNamespace
from unittest.mock import AsyncMock

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
