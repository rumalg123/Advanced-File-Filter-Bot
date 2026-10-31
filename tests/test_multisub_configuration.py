from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from bson.int64 import Int64

from bot import BotConfig
from config.settings import ChannelConfig, settings
from core.services.bot_settings import BotSettingsService
from core.utils.subscription_config import parse_subscription_targets


@pytest.mark.parametrize('raw,expected', [
    (None, []), ('', []), ('0', []), (0, []), (-1001, [-1001]),
    ('-1001', [-1001]), ('-1001, -1002', [-1001, -1002]),
    ([-1001, '-1002'], [-1001, -1002]),
    (Int64(-1001234567890), [-1001234567890]),
    ([Int64(-1001234567890), Int64(-1009876543210)], [-1001234567890, -1009876543210]),
    ('0, -1001, -1001, @QA_Chan, qa_chan', [-1001, '@qa_chan']),
])
def test_force_sub_target_formats_remain_compatible(raw, expected):
    assert parse_subscription_targets(raw) == expected
    config = object.__new__(BotConfig)
    config._settings = deepcopy(settings)
    config.AUTH_CHANNEL = None
    config.AUTH_GROUPS = []
    config.sync_settings_from_db({'AUTH_CHANNEL': {'value': raw}})
    assert config.AUTH_CHANNELS == expected
    assert config.AUTH_CHANNEL == (expected[0] if expected else None)


@pytest.mark.parametrize('raw', [True, False, 1.5, {}, [None], ['bad/url'], 'https://t.me/qa', '-'])
def test_invalid_force_sub_target_is_not_silently_discarded(raw):
    with pytest.raises(ValueError):
        parse_subscription_targets(raw)


def test_environment_lists_and_default_invite_controls():
    config = ChannelConfig(_env_file=None, auth_channel='-1001,-1002', auth_groups='-1003,-1004')
    assert config.get_auth_channel_list() == [-1001, -1002]
    assert config.get_auth_groups_list() == [-1003, -1004]
    assert config.force_sub_invite_expire_minutes == 15
    assert config.force_sub_invite_member_limit == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('raw', [-1001, '-1001', [-1001, -1002]])
async def test_old_mongo_channel_documents_are_read_without_a_migration(raw):
    repo = SimpleNamespace(get_all_settings=AsyncMock(return_value={
        'AUTH_CHANNEL': SimpleNamespace(value=raw)}), set_setting=AsyncMock())
    service = BotSettingsService(repo, None)
    result = await service.get_all_settings()
    assert result['AUTH_CHANNEL']['value'] == parse_subscription_targets(raw)
    assert result['AUTH_CHANNEL']['type'] == 'list'
    repo.set_setting.assert_not_awaited()


@pytest.mark.asyncio
async def test_corrupt_persisted_memberships_fail_closed_before_startup():
    repo = SimpleNamespace(get_all_settings=AsyncMock(return_value={
        'AUTH_CHANNEL': SimpleNamespace(value=['bad/url'])}))
    with pytest.raises(ValueError, match='Invalid stored force-subscription'):
        await BotSettingsService(repo, None).get_all_settings()


@pytest.mark.asyncio
@pytest.mark.parametrize('key,value', [
    ('FORCE_SUB_INVITE_EXPIRE_MINUTES', 0), ('FORCE_SUB_INVITE_EXPIRE_MINUTES', 525601),
    ('FORCE_SUB_INVITE_MEMBER_LIMIT', 0), ('FORCE_SUB_INVITE_MEMBER_LIMIT', 100000),
    ('FORCE_SUB_INVITE_MEMBER_LIMIT', True),
])
async def test_invalid_invite_controls_never_reach_mongo(key, value):
    repo = SimpleNamespace(set_setting=AsyncMock())
    with pytest.raises(ValueError):
        await BotSettingsService(repo, None).update_setting(key, value)
    repo.set_setting.assert_not_awaited()
