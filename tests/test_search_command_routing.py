from types import SimpleNamespace

import pytest
from pyrogram import enums
from pyrogram.types import Chat, Message

from handlers.search import SEARCH_TEXT_FILTER, SearchHandler


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('text', 'should_search'),
    [
        ('/verify', False),
        ('/verify@my_filter_bot', False),
        ('  /future_command', False),
        ('verify', True),
        ('Glory S01E01', True),
    ],
)
async def test_search_filter_rejects_all_slash_commands(text, should_search):
    message = Message(
        id=1,
        chat=Chat(id=1, type=enums.ChatType.PRIVATE),
        text=text,
        outgoing=False,
    )

    assert await SEARCH_TEXT_FILTER(None, message) is should_search


@pytest.mark.asyncio
async def test_search_handler_guard_rejects_commands_before_using_services():
    handler = object.__new__(SearchHandler)
    message = SimpleNamespace(text='/new_command')

    result = await SearchHandler.handle_text_search.__wrapped__(
        handler, None, message
    )

    assert result is None
