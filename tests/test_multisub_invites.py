from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyrogram import enums
from pyrogram.errors import UserNotParticipant

from core.utils.subscription import SubscriptionManager
from handlers.commands_handlers.user import UserCommandHandler
from subscription_support import call_api, fixture as callback_fixture


def client_fixture(monkeypatch, *, joined=(), invite=True):
    async def chat(target):
        return SimpleNamespace(id=target, title='QA chat', username='qa_public',
            type=enums.ChatType.SUPERGROUP if target == -1003 else enums.ChatType.CHANNEL)

    async def member(target, uid):
        if uid == 'me':
            return SimpleNamespace(status=enums.ChatMemberStatus.ADMINISTRATOR,
                privileges=SimpleNamespace(can_invite_users=invite))
        if target not in joined:
            raise UserNotParticipant()
        return SimpleNamespace(status=enums.ChatMemberStatus.MEMBER)

    client = SimpleNamespace(get_chat=AsyncMock(side_effect=chat),
        get_chat_member=AsyncMock(side_effect=member),
        create_chat_invite_link=AsyncMock(side_effect=lambda cid, **kwargs:
            SimpleNamespace(invite_link=f'https://t.me/+qa{abs(cid)}')))
    monkeypatch.setattr('core.utils.subscription.telegram_api.call_api', call_api)
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize('joined,allowed', [([-1001, -1002, -1003], True),
    ([-1001, -1003], False), ([-1001, -1002], False), ([], False)])
async def test_all_channels_and_groups_are_required(monkeypatch, joined, allowed):
    client = client_fixture(monkeypatch, joined=joined)
    manager = SubscriptionManager('-1001,-1002', [-1003])
    assert await manager.is_subscribed(client, 42) is allowed
    assert await manager.is_subscribed(client, 42, check_channel=False) is (-1003 in joined)


@pytest.mark.asyncio
@pytest.mark.parametrize('minutes,limit', [(15, 1), (2, 3)])
async def test_missing_targets_get_expiring_limited_links_even_when_public(monkeypatch, minutes, limit):
    client = client_fixture(monkeypatch, joined=[-1001])
    manager = SubscriptionManager([-1001, -1002], [-1003],
        invite_expire_minutes=minutes, invite_member_limit=limit)
    before = datetime.now(UTC).timestamp()
    buttons = await manager.build_subscription_buttons(client, 42)
    assert len([b.url for row in buttons for b in row if b.url]) == 2
    assert client.create_chat_invite_link.await_count == 2
    for call in client.create_chat_invite_link.await_args_list:
        assert call.args[0] in [-1002, -1003]
        assert call.kwargs['member_limit'] == limit
        assert call.kwargs['creates_join_request'] is False
        assert before + minutes * 60 <= call.kwargs['expire_date'].timestamp() <= datetime.now(UTC).timestamp() + minutes * 60
    assert all(b.url != 'https://t.me/qa_public' for row in buttons for b in row)


@pytest.mark.asyncio
async def test_no_invite_is_generated_without_bot_invite_rights(monkeypatch):
    client = client_fixture(monkeypatch, invite=False)
    rows = await SubscriptionManager(-1001).build_subscription_buttons(client, 42)
    assert all(not button.url for row in rows for button in row)
    client.create_chat_invite_link.assert_not_awaited()


@pytest.mark.asyncio
async def test_initial_start_of_missing_member_shows_join_prompt():
    owner, query, _ = callback_fixture(subscribed=False)
    owner.bot.user_repo.is_user_exist = AsyncMock(return_value=True)
    message = query.message
    message.from_user = query.from_user
    message.command = ['start']
    handler = UserCommandHandler(owner.bot)
    handler._send_subscription_message_for_deeplink = AsyncMock()
    await handler.start_command(None, message)
    assert handler._send_subscription_message_for_deeplink.await_args.args[-1] == 'start'


@pytest.mark.asyncio
async def test_failed_retry_refreshes_links_without_consuming_saved_action():
    handler, query, cache = callback_fixture('checksub#dl#deeplink_42_aabbccdd', subscribed=False)
    cache.values['deeplink_42_aabbccdd'] = {'user_id': 42, 'deeplink': 'start'}
    handler.bot.subscription_manager.build_subscription_buttons = AsyncMock(return_value=[])
    query.message.edit_reply_markup = AsyncMock()
    await handler.handle_checksub_callback(None, query)
    handler.bot.subscription_manager.build_subscription_buttons.assert_awaited_once_with(
        None, 42, custom_callback_data=query.data)
    query.message.edit_reply_markup.assert_awaited_once()
    assert 'deeplink_42_aabbccdd' in cache.values
