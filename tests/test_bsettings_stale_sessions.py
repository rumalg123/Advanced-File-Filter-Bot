import asyncio

import pytest

from bsettings_support import fixture
from core.session.manager import UnifiedSessionManager
from test_cache_audit import MemoryCache


@pytest.mark.asyncio
@pytest.mark.parametrize('message_id,chat_id,cancel', [(20, 1, False), (10, 2, False), (10, 1, True)])
async def test_closing_menu_only_cancels_the_edit_owned_by_that_message(message_id, chat_id, cancel):
    handler, message, query = fixture()
    manager = UnifiedSessionManager(MemoryCache())
    handler.session_manager = manager
    token = await manager.create_edit_session(1, {
        'key': 'CACHE_TIME', 'chat_id': chat_id, 'message_id': message_id,
    })
    query.data = 'bset_close'
    await handler.settings_callback(None, query)
    current = await manager.get_edit_session(1)
    if cancel:
        assert current is None
    else:
        assert current is not None and current.session_id == token


@pytest.mark.asyncio
@pytest.mark.parametrize('error', [RuntimeError('QA Telegram prompt failed'), asyncio.CancelledError()])
async def test_failed_edit_prompt_does_not_leave_a_hidden_input_session(error):
    handler, message, _ = fixture()
    manager = UnifiedSessionManager(MemoryCache())
    handler.session_manager = manager
    message.edit_text.side_effect = error
    with pytest.raises(type(error)):
        await handler.start_edit_session(message, 'CACHE_TIME', 1)
    assert await manager.get_edit_session(1) is None


@pytest.mark.asyncio
async def test_delayed_close_does_not_cancel_a_newer_edit_on_the_same_menu():
    handler, message, query = fixture()
    manager = UnifiedSessionManager(MemoryCache())
    handler.session_manager = manager
    data = {'key': 'CACHE_TIME', 'chat_id': 1, 'message_id': 10}
    await manager.create_edit_session(1, data)
    created = []

    async def delete():
        created.append(await manager.create_edit_session(1, data))

    message.delete.side_effect = delete
    query.data = 'bset_close'
    await handler.settings_callback(None, query)
    assert (await manager.get_edit_session(1)).session_id == created[0]
