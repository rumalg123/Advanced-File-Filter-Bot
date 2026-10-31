from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyrogram import enums
from pyrogram.errors import UserNotParticipant

from core.utils.subscription import SubscriptionManager
from subscription_support import call_api


@pytest.mark.asyncio
@pytest.mark.parametrize('target', ['channel', 'group'])
async def test_unavailable_join_link_does_not_create_an_invalid_url_button(monkeypatch, target):
    manager = SubscriptionManager(-1001 if target == 'channel' else None,
        [-1002] if target == 'group' else [])
    client = SimpleNamespace(get_chat=AsyncMock(side_effect=RuntimeError('CHANNEL_PRIVATE')),
        create_chat_invite_link=AsyncMock(side_effect=RuntimeError('QA cannot invite')))
    monkeypatch.setattr('core.utils.subscription.telegram_api.call_api', call_api)
    buttons = await manager.build_subscription_buttons(client, 42)
    assert all(not b.url or b.url.startswith('https://') for row in buttons for b in row)
    assert buttons[-1][0].callback_data == 'checksub#42#general'


@pytest.mark.asyncio
async def test_successful_join_buttons_keep_channel_and_group_destinations(monkeypatch):
    manager = SubscriptionManager(-1001, [-1002])
    async def chat(target):
        return SimpleNamespace(id=target, username='qa_required_chat', title='QA required chat',
            type=enums.ChatType.CHANNEL if target == -1001 else enums.ChatType.SUPERGROUP)

    async def member(target, user_id):
        if user_id != 'me':
            raise UserNotParticipant()
        return SimpleNamespace(status=enums.ChatMemberStatus.ADMINISTRATOR,
            privileges=SimpleNamespace(can_invite_users=True))

    client = SimpleNamespace(get_chat=AsyncMock(side_effect=chat),
        get_chat_member=AsyncMock(side_effect=member),
        create_chat_invite_link=AsyncMock(side_effect=lambda target, **kwargs:
            SimpleNamespace(invite_link=f'https://t.me/+qa{abs(target)}')))
    monkeypatch.setattr('core.utils.subscription.telegram_api.call_api', call_api)
    buttons = await manager.build_subscription_buttons(client, 42)
    assert [row[0].url for row in buttons[:-1]] == ['https://t.me/+qa1001', 'https://t.me/+qa1002']
