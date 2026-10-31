from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyrogram import enums
from pyrogram.errors import UserNotParticipant

from core.utils.subscription import SubscriptionManager
from subscription_support import call_api


@pytest.mark.asyncio
@pytest.mark.parametrize('target', ['channel', 'group'])
@pytest.mark.parametrize('status,is_member,allowed', [
    (enums.ChatMemberStatus.OWNER, None, True),
    (enums.ChatMemberStatus.ADMINISTRATOR, None, True),
    (enums.ChatMemberStatus.MEMBER, None, True),
    (enums.ChatMemberStatus.RESTRICTED, True, True),
    (enums.ChatMemberStatus.RESTRICTED, False, False),
    (enums.ChatMemberStatus.RESTRICTED, None, False),
    (enums.ChatMemberStatus.LEFT, None, False),
    (enums.ChatMemberStatus.BANNED, None, False),
    ('unknown-state', None, False),
])
async def test_subscription_requires_actual_membership(monkeypatch, target, status, is_member, allowed):
    manager = SubscriptionManager(-1001 if target == 'channel' else None,
        [-1002] if target == 'group' else [])
    client = SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(
        status=status, is_member=is_member)))
    monkeypatch.setattr('core.utils.subscription.telegram_api.call_api', call_api)
    assert await manager.is_subscribed(client, 42) is allowed


@pytest.mark.asyncio
@pytest.mark.parametrize('target', ['channel', 'group'])
@pytest.mark.parametrize('error', [UserNotParticipant(), RuntimeError('CHANNEL_PRIVATE'),
    RuntimeError('chat not found'), RuntimeError('QA network unavailable')])
async def test_unverifiable_required_chat_never_grants_access(monkeypatch, target, error):
    manager = SubscriptionManager(-1001 if target == 'channel' else None,
        [-1002] if target == 'group' else [])
    client = SimpleNamespace(get_chat_member=AsyncMock(side_effect=error))
    monkeypatch.setattr('core.utils.subscription.telegram_api.call_api', call_api)
    assert await manager.is_subscribed(client, 42) is False


@pytest.mark.asyncio
async def test_every_required_chat_is_checked_and_disabled_targets_are_skipped(monkeypatch):
    manager = SubscriptionManager(-1001, [-1002, -1003])
    client = SimpleNamespace(get_chat_member=AsyncMock(side_effect=[
        SimpleNamespace(status=enums.ChatMemberStatus.MEMBER),
        SimpleNamespace(status=enums.ChatMemberStatus.LEFT),
    ]))
    monkeypatch.setattr('core.utils.subscription.telegram_api.call_api', call_api)
    assert not await manager.is_subscribed(client, 42)
    assert client.get_chat_member.await_count == 2
    client.get_chat_member.reset_mock()
    assert await manager.is_subscribed(client, 42, check_channel=False, check_groups=False)
    client.get_chat_member.assert_not_awaited()
