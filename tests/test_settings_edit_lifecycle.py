"""Persistence outcome and Telegram cleanup are separate edit-session contracts."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pyrogram import StopPropagation

from handlers.commands_handlers.bot_settings import BotSettingsHandler


def fixture(monkeypatch, *, key='CACHE_TIME'):
    handler=object.__new__(BotSettingsHandler)
    handler.bot=SimpleNamespace(cache=SimpleNamespace(set=AsyncMock(return_value=True)))
    handler.settings_service=SimpleNamespace(update_setting=AsyncMock(return_value=True))
    handler.session_manager=SimpleNamespace(
        get_edit_session=AsyncMock(return_value=SimpleNamespace(data={'key':key,'message_id':10})),
        cancel_edit_session=AsyncMock())
    handler.invalidate_related_caches=AsyncMock()
    handler._schedule_auto_delete=Mock()
    message=SimpleNamespace(from_user=SimpleNamespace(id=1),chat=SimpleNamespace(id=1),
        text='600',delete=AsyncMock(),reply_text=AsyncMock())
    client=SimpleNamespace(delete_messages=AsyncMock(),send_message=AsyncMock(return_value=SimpleNamespace(id=99)))
    async def call(fn,*args,**kwargs):
        kwargs.pop('chat_id',None)
        return await fn(*args,**kwargs)
    monkeypatch.setattr('handlers.commands_handlers.bot_settings.telegram_api.call_api',call)
    return handler,message,client


@pytest.mark.asyncio
async def test_saved_setting_is_confirmed_even_when_input_cleanup_fails(monkeypatch):
    handler,message,client=fixture(monkeypatch)
    message.delete.side_effect=RuntimeError('Telegram message already deleted')
    with pytest.raises(StopPropagation):await handler.handle_edit_input(client,message)
    handler.settings_service.update_setting.assert_awaited_once_with('CACHE_TIME','600')
    assert 'updated successfully' in client.send_message.await_args.args[1]
    message.reply_text.assert_not_awaited()
    handler.session_manager.cancel_edit_session.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_successful_edit_clears_session_and_schedules_confirmation_cleanup(monkeypatch):
    handler,message,client=fixture(monkeypatch)
    with pytest.raises(StopPropagation):await handler.handle_edit_input(client,message)
    message.delete.assert_awaited_once()
    handler.session_manager.cancel_edit_session.assert_awaited_once_with(1)
    assert 'updated successfully' in client.send_message.await_args.args[1]
    handler._schedule_auto_delete.assert_called_once_with(client.send_message.return_value,10)


@pytest.mark.asyncio
async def test_invalid_edit_reports_failure_and_clears_session(monkeypatch):
    handler,message,client=fixture(monkeypatch)
    handler.settings_service.update_setting.side_effect=ValueError('Expected an integer')
    with pytest.raises(StopPropagation):await handler.handle_edit_input(client,message)
    assert 'Expected an integer' in message.reply_text.await_args.args[0]
    handler.session_manager.cancel_edit_session.assert_awaited_once_with(1)
    client.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_protected_setting_cannot_be_written_by_forged_edit_session(monkeypatch):
    handler,message,client=fixture(monkeypatch,key='BOT_TOKEN')
    with pytest.raises(StopPropagation):await handler.handle_edit_input(client,message)
    handler.settings_service.update_setting.assert_not_awaited()
    handler.session_manager.cancel_edit_session.assert_awaited_once_with(1)
    assert 'protected' in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('failed_cleanup',[False,True])
async def test_cancel_clears_session_even_when_telegram_cleanup_fails(monkeypatch,failed_cleanup):
    handler,message,client=fixture(monkeypatch);message.text='/cancel'
    if failed_cleanup:
        message.delete.side_effect=RuntimeError('already deleted')
        client.delete_messages.side_effect=RuntimeError('already deleted')
    with pytest.raises(StopPropagation):await handler.handle_edit_input(client,message)
    handler.settings_service.update_setting.assert_not_awaited()
    handler.session_manager.cancel_edit_session.assert_awaited_once_with(1)


@pytest.mark.asyncio
@pytest.mark.parametrize('manager_present',[False,True])
async def test_ordinary_text_without_edit_session_is_not_consumed(monkeypatch,manager_present):
    handler,message,client=fixture(monkeypatch)
    if manager_present:handler.session_manager.get_edit_session.return_value=None
    else:handler.session_manager=None
    assert await handler.handle_edit_input(client,message) is None
    handler.bot.cache.set.assert_not_awaited()
    handler.settings_service.update_setting.assert_not_awaited()


@pytest.mark.asyncio
async def test_completing_old_edit_does_not_cancel_newer_owner_session(monkeypatch):
    from core.session.manager import UnifiedSessionManager
    from test_cache_audit import MemoryCache
    handler,message,client=fixture(monkeypatch)
    manager=UnifiedSessionManager(MemoryCache());handler.session_manager=manager
    old=await manager.create_edit_session(1,{'key':'CACHE_TIME','message_id':10})
    created=[]
    async def persist(*args):
        created.append(await manager.create_edit_session(1,{'key':'MAX_BTN_SIZE','message_id':20}))
        return True
    handler.settings_service.update_setting.side_effect=persist
    with pytest.raises(StopPropagation):await handler.handle_edit_input(client,message)
    latest=await manager.get_edit_session(1)
    assert latest is not None and latest.session_id==created[0] and latest.session_id!=old


@pytest.mark.asyncio
async def test_cancel_of_old_edit_does_not_cancel_newer_owner_session(monkeypatch):
    from core.session.manager import UnifiedSessionManager
    from test_cache_audit import MemoryCache
    handler,message,client=fixture(monkeypatch)
    manager=UnifiedSessionManager(MemoryCache());handler.session_manager=manager
    await manager.create_edit_session(1,{'key':'CACHE_TIME','message_id':10})
    created=[]
    async def delete_old_message(*args):
        created.append(await manager.create_edit_session(1,{'key':'MAX_BTN_SIZE','message_id':20}))
    client.delete_messages.side_effect=delete_old_message
    with pytest.raises(StopPropagation):await handler.handle_cancel(client,message)
    latest=await manager.get_edit_session(1)
    assert latest is not None and latest.session_id==created[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('phase',['input_lock','input_delete','confirmation'])
async def test_cancelled_edit_closes_its_session_at_every_processing_phase(monkeypatch,phase):
    handler,message,client=fixture(monkeypatch)
    target={'input_lock':handler.bot.cache.set,'input_delete':message.delete,
            'confirmation':client.send_message}[phase]
    target.side_effect=asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):await handler.handle_edit_input(client,message)
    handler.session_manager.cancel_edit_session.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_task_cancellation_waits_for_owned_edit_cleanup(monkeypatch):
    handler,message,client=fixture(monkeypatch)
    confirming=asyncio.Event();cleaning=asyncio.Event();finish=asyncio.Event();completed=asyncio.Event()
    async def send(*args):
        confirming.set();await asyncio.sleep(60)
    async def cancel(*args,**kwargs):
        cleaning.set();await finish.wait();completed.set()
    client.send_message.side_effect=send
    handler.session_manager.cancel_edit_session.side_effect=cancel
    task=asyncio.create_task(handler.handle_edit_input(client,message))
    try:
        await asyncio.wait_for(confirming.wait(),.5)
        task.cancel()
        await asyncio.wait_for(cleaning.wait(),.5)
        assert not task.done()
    finally:
        finish.set()
        with pytest.raises(asyncio.CancelledError):await task
    assert completed.is_set()
