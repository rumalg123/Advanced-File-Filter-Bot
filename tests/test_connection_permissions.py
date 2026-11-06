"""Fresh Telegram roles and menu context guard group connections and filters."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from pyrogram import enums
from pyrogram.errors import UserNotParticipant

import core.services.connection as connections
import handlers.connection as routes
from core.services.connection import ConnectionService
from handlers.connection import ConnectionHandler
from handlers.search import SearchHandler


@pytest.mark.parametrize('status,is_member,expected', [
    (enums.ChatMemberStatus.OWNER, None, True),
    (enums.ChatMemberStatus.ADMINISTRATOR, None, True),
    (enums.ChatMemberStatus.MEMBER, None, True),
    (enums.ChatMemberStatus.RESTRICTED, True, True),
    (enums.ChatMemberStatus.RESTRICTED, False, False),
    (enums.ChatMemberStatus.RESTRICTED, None, False),
    (enums.ChatMemberStatus.LEFT, None, False),
    (enums.ChatMemberStatus.BANNED, None, False),
    ('unknown', None, None),
])
@pytest.mark.asyncio
async def test_membership_is_explicit(monkeypatch, status, is_member, expected):
    monkeypatch.setattr(connections.telegram_api, 'call_api', AsyncMock(return_value=NS(status=status, is_member=is_member)))
    assert await connections.verify_user_in_group(NS(get_chat_member=object()), 12, -1001) is expected


@pytest.mark.parametrize('error,removed', [(ConnectionError('QA offline'), 0), (UserNotParticipant(), 1)])
@pytest.mark.asyncio
async def test_cleanup_preserves_unverifiable_connections(monkeypatch, error, removed):
    repo = NS(get_all_connections=AsyncMock(return_value=['-1001']), delete_connection=AsyncMock(return_value=True))
    monkeypatch.setattr(connections.telegram_api, 'call_api', AsyncMock(side_effect=error))
    service = ConnectionService(repo, [])
    assert await service.cleanup_invalid_connections(NS(get_chat_member=object()), 12) == removed
    assert repo.delete_connection.await_count == removed


def handler_fixture(data, *, private=True, user=12):
    handler = object.__new__(ConnectionHandler)
    repo = NS(find_by_id=AsyncMock(return_value=NS(group_details=[{'group_id': '-1001'}])))
    service = NS(connection_repo=repo, can_manage_group=AsyncMock(return_value=False),
                 set_active_connection=AsyncMock(return_value=(True, 'ok')),
                 disconnect_from_group=AsyncMock(return_value=(True, 'ok')))
    handler.connection_service = service
    handler.bot = NS(config=NS(ADMINS=[], DISABLE_FILTER=False), user_repo=NS(get_user=AsyncMock(return_value=None)),
                     filter_service=NS(delete_all_filters=AsyncMock(return_value=True)))
    query = NS(data=data, from_user=NS(id=user), answer=AsyncMock(),
               message=NS(chat=NS(id=user if private else -1001, type=enums.ChatType.PRIVATE if private else enums.ChatType.SUPERGROUP), edit_text=AsyncMock()))
    handler._show_connections = AsyncMock()
    return handler, query


@pytest.mark.asyncio
@pytest.mark.parametrize('route', ['delete_group_filters_callback', 'connection_action_callback'])
async def test_bulk_filter_removal_requires_owner_or_bot_admin(monkeypatch, route):
    data = 'delete_group_filters:-1001' if route.startswith('delete_') else 'disconnect_group_with_filters:-1001'
    handler, query = handler_fixture(data, private=not route.startswith('delete_'))
    monkeypatch.setattr(routes, 'is_group_admin', AsyncMock(return_value=True))
    monkeypatch.setattr(routes, 'is_group_owner', AsyncMock(return_value=False), raising=False)
    await getattr(handler, route)(None, query)
    handler.bot.filter_service.delete_all_filters.assert_not_awaited()
    handler.connection_service.disconnect_from_group.assert_not_awaited()
    assert query.answer.await_count == 1


@pytest.mark.asyncio
async def test_demoted_user_cannot_activate_old_connection():
    handler, query = handler_fixture('connect_group:-1001')
    await handler.connection_action_callback(None, query)
    handler.connection_service.set_active_connection.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('data', ['disconnect_group:-1001', 'deactivate_group:-1001', 'delete_connection:-1001'])
async def test_private_connection_controls_reject_shared_group_context(data):
    handler, query = handler_fixture(data, private=False)
    await handler.connection_action_callback(None, query)
    handler.connection_service.disconnect_from_group.assert_not_awaited()
    query.message.edit_text.assert_not_awaited()
    assert query.answer.await_count == 1


@pytest.mark.asyncio
async def test_private_filter_search_rechecks_group_rights():
    handler = object.__new__(SearchHandler)
    service = NS(get_all_filters=AsyncMock(return_value=['qa']),
                 get_filter=AsyncMock(return_value=('secret', '[]', None, 'None')), send_filter_response=AsyncMock())
    handler.bot = NS(config=NS(DISABLE_FILTER=False), filter_service=service,
                     connection_service=NS(can_manage_group=AsyncMock(return_value=False)))
    assert not await handler._check_and_send_filter(None, NS(), 'qa', '-1001', 12, True)
    service.get_all_filters.assert_not_awaited()
    service.send_filter_response.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('bot_admin,owner,allowed', [(True, False, True), (False, True, True), (False, False, False)])
async def test_bulk_delete_retains_owner_and_configured_admin_bypass(monkeypatch, bot_admin, owner, allowed):
    handler, query = handler_fixture('disconnect_group_with_filters:-1001')
    handler.bot.config.ADMINS = [12] if bot_admin else []
    monkeypatch.setattr(routes, 'is_group_owner', AsyncMock(return_value=owner))
    await handler.connection_action_callback(None, query)
    assert handler.bot.filter_service.delete_all_filters.await_count == int(allowed)
    assert handler.connection_service.disconnect_from_group.await_count == int(allowed)
    assert query.answer.await_count == 1


@pytest.mark.asyncio
async def test_admin_cleanup_preserves_bypass_connections():
    repo = NS(get_all_connections=AsyncMock(), delete_connection=AsyncMock())
    assert await ConnectionService(repo, [12]).cleanup_invalid_connections(None, 12) == 0
    repo.get_all_connections.assert_not_awaited()


@pytest.mark.asyncio
async def test_back_button_refreshes_private_connections():
    handler, query = handler_fixture('back_to_connections')
    await handler.connection_callback(None, query)
    handler._show_connections.assert_awaited_once_with(None, query.message, 12, edit=True)


@pytest.mark.asyncio
async def test_filter_deletion_failure_does_not_report_success(monkeypatch):
    handler, query = handler_fixture('disconnect_group_with_filters:-1001')
    monkeypatch.setattr(routes, 'is_group_owner', AsyncMock(return_value=True))
    handler.bot.filter_service.delete_all_filters.return_value = False
    await handler.connection_action_callback(None, query)
    assert 'could not be deleted' in query.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_delete_connection_preview_acknowledges_callback_once():
    handler, query = handler_fixture('delete_connection:-1001')
    await handler.connection_action_callback(None, query)
    query.answer.assert_awaited_once()
    query.message.edit_text.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('items', [[], [{'id': '-1001', 'title': 'QA', 'is_active': True}]])
async def test_refreshing_unchanged_connections_is_idempotent(items):
    from pyrogram.errors import MessageNotModified
    handler, query = handler_fixture('cleanup_connections')
    handler.connection_service.get_all_connections = AsyncMock(return_value=items)
    query.message.edit_text.side_effect = MessageNotModified()
    await handler._show_connections(None, query.message, 12, edit=True)
