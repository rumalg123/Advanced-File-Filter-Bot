from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyrogram import enums

from core.services.bot_settings import BotSettingsService
from core.utils.subscription import SubscriptionManager
from subscription_support import call_api


def fixture(monkeypatch, *, status=enums.ChatMemberStatus.ADMINISTRATOR,
            invite=True, kind=enums.ChatType.CHANNEL):
    async def chat(target):
        return SimpleNamespace(id=-1001 if target == '@qa_alias' else target,
            type=kind, title='QA <channel>', username='qa_public')
    client = SimpleNamespace(get_chat=AsyncMock(side_effect=chat),
        get_chat_member=AsyncMock(return_value=SimpleNamespace(status=status,
            privileges=SimpleNamespace(can_invite_users=invite))))
    repo = SimpleNamespace(set_setting=AsyncMock(return_value=True))
    service = BotSettingsService(repo, None, telegram_client=client)
    monkeypatch.setattr('core.utils.subscription.telegram_api.call_api', call_api)
    return service, repo, client


@pytest.mark.asyncio
@pytest.mark.parametrize('key,kind', [('AUTH_CHANNEL', enums.ChatType.CHANNEL),
    ('AUTH_GROUPS', enums.ChatType.SUPERGROUP)])
async def test_every_candidate_is_checked_before_the_single_settings_write(monkeypatch, key, kind):
    service, repo, client = fixture(monkeypatch, kind=kind)

    async def checked(target, user_id):
        repo.set_setting.assert_not_awaited()
        assert user_id == 'me'
        return SimpleNamespace(status=enums.ChatMemberStatus.ADMINISTRATOR,
            privileges=SimpleNamespace(can_invite_users=True))

    client.get_chat_member.side_effect = checked
    assert await service.update_setting(key, '-1001, -1002')
    assert client.get_chat_member.await_count == 2
    assert repo.set_setting.await_args.kwargs['value'] == [-1001, -1002]


@pytest.mark.asyncio
@pytest.mark.parametrize('status,invite', [(enums.ChatMemberStatus.MEMBER, True),
    (enums.ChatMemberStatus.ADMINISTRATOR, False), (enums.ChatMemberStatus.LEFT, False)])
@pytest.mark.parametrize('key,kind', [('AUTH_CHANNEL', enums.ChatType.CHANNEL),
    ('AUTH_GROUPS', enums.ChatType.SUPERGROUP)])
async def test_invalid_bot_permissions_block_storage_with_actionable_feedback(monkeypatch, status, invite, key, kind):
    service, repo, _ = fixture(monkeypatch, status=status, invite=invite, kind=kind)
    with pytest.raises(ValueError, match='Invite Users'):
        await service.update_setting(key, '-1001')
    repo.set_setting.assert_not_awaited()


@pytest.mark.asyncio
async def test_unreachable_chat_never_stores_raw_backend_error(monkeypatch):
    service, repo, client = fixture(monkeypatch)
    client.get_chat.side_effect = RuntimeError('private backend diagnostic')
    with pytest.raises(ValueError) as caught:
        await service.update_setting('AUTH_CHANNEL', '-1001')
    assert 'Cannot access chat' in str(caught.value)
    assert 'private backend' not in str(caught.value)
    repo.set_setting.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_chat_kind_is_rejected_before_storage(monkeypatch):
    service, repo, _ = fixture(monkeypatch, kind=enums.ChatType.PRIVATE)
    with pytest.raises(ValueError, match='valid force-subscription channel'):
        await service.update_setting('AUTH_CHANNEL', '42')
    repo.set_setting.assert_not_awaited()


@pytest.mark.asyncio
async def test_aliases_are_resolved_to_one_immutable_chat_id(monkeypatch):
    service, repo, _ = fixture(monkeypatch)
    assert await service.update_setting('AUTH_CHANNEL', '@qa_alias, -1001')
    assert repo.set_setting.await_args.kwargs['value'] == [-1001]


@pytest.mark.asyncio
async def test_clearing_requirements_remains_possible_without_telegram_access():
    repo = SimpleNamespace(set_setting=AsyncMock(return_value=True))
    service = BotSettingsService(repo, None)
    assert await service.update_setting('AUTH_CHANNEL', '0')
    assert repo.set_setting.await_args.kwargs['value'] == []
    with pytest.raises(ValueError, match='Cannot verify'):
        await service.update_setting('AUTH_CHANNEL', '-1001')
    assert repo.set_setting.await_count == 1


@pytest.mark.asyncio
async def test_startup_accessibility_reports_missing_invite_permission(monkeypatch):
    _, _, client = fixture(monkeypatch, invite=False)
    result = await SubscriptionManager([-1001, -1002]).check_auth_channels_accessibility(client)
    assert result['accessible'] is False and len(result['errors']) == 2
    assert all('Invite Users' in item['error'] for item in result['errors'])


@pytest.mark.asyncio
async def test_invalid_second_target_does_not_partially_save_the_list(monkeypatch):
    service, repo, client = fixture(monkeypatch)
    client.get_chat_member.side_effect = [
        SimpleNamespace(status=enums.ChatMemberStatus.ADMINISTRATOR,
            privileges=SimpleNamespace(can_invite_users=True)),
        SimpleNamespace(status=enums.ChatMemberStatus.MEMBER),
    ]
    with pytest.raises(ValueError, match='-1002'):
        await service.update_setting('AUTH_CHANNEL', '-1001,-1002')
    repo.set_setting.assert_not_awaited()


@pytest.mark.asyncio
async def test_settings_ui_explains_permission_failure_without_requesting_restart(monkeypatch):
    from pyrogram import StopPropagation
    from test_settings_edit_lifecycle import fixture as edit_fixture

    service, repo, _ = fixture(monkeypatch, status=enums.ChatMemberStatus.MEMBER)
    handler, message, client = edit_fixture(monkeypatch, key='AUTH_CHANNEL')
    handler.settings_service = service
    message.text = '-1001'
    with pytest.raises(StopPropagation):
        await handler.handle_edit_input(client, message)
    repo.set_setting.assert_not_awaited()
    response = message.reply_text.await_args.args[0]
    assert 'administrator' in response and 'Invite Users' in response
    assert 'restart' not in response.lower()
    client.send_message.assert_not_awaited()
