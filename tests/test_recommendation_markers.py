"""Independent favorite and recommendation controls keep each other's state."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyrogram.types import InlineKeyboardMarkup

from core.utils.button_builder import ButtonBuilder
from handlers.features import FeatureHandler


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['fav', 'unfav', 'more', 'less', 'rec_reset'])
async def test_delivery_marker_changes_only_its_own_control_group(action):
    markup = InlineKeyboardMarkup([[
        ButtonBuilder.action_button('✅ Favorited', callback_data='feature#fav#file'),
    ], [
        ButtonBuilder.action_button('👍 More like this', callback_data='feature#more#file'),
        ButtonBuilder.action_button('✅ Not interested', callback_data='feature#less#file'),
    ]])
    message = SimpleNamespace(reply_markup=markup, edit_reply_markup=AsyncMock())
    handler = object.__new__(FeatureHandler)
    assert await handler._update_delivery_markers(message, action)
    result = message.edit_reply_markup.await_args.args[0] if message.edit_reply_markup.await_count else markup
    if action in {'fav', 'unfav'}:
        assert result.inline_keyboard[1][1].text == '✅ Not interested'
    else:
        assert result.inline_keyboard[0][0].text == '✅ Favorited'
