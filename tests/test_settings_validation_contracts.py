from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from core.services.bot_settings import BotSettingsService


def service():
    repo=SimpleNamespace(set_setting=AsyncMock(return_value=True),get_all_settings=AsyncMock(return_value={}))
    return BotSettingsService(repo,SimpleNamespace()),repo


@pytest.mark.asyncio
@pytest.mark.parametrize('key,value',[
    ('PORT','bad'),('PORT',0),('PORT',65536),('CACHE_TIME','bad'),('CACHE_TIME',0),
    ('MESSAGE_DELETE_SECONDS','bad'),('MESSAGE_DELETE_SECONDS',-1),('WORKERS',0),
    ('MAX_BTN_SIZE',0),('NON_PREMIUM_DAILY_LIMIT',-1),('DATABASE_SIZE_LIMIT_GB',0),
    ('DATABASE_SIZE_LIMIT_GB','nan'),('DATABASE_SIZE_LIMIT_GB','inf'),
    ('PREMIUM_DURATION_DAYS',True),('MESSAGE_DELETE_SECONDS',3.5),
    ('DISABLE_PREMIUM','definitely'),('FEATURE_FAVORITES','tru'),
])
async def test_invalid_settings_never_reach_persistence(key,value):
    settings,repo=service()
    with pytest.raises(ValueError):await settings.update_setting(key,value)
    repo.set_setting.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('key,raw,expected',[
    ('PORT','8001',8001),('MESSAGE_DELETE_SECONDS','0',0),('CACHE_TIME','600',600),
    ('FEATURE_FAVORITES','yes',True),('FEATURE_FAVORITES','off',False),
    ('DATABASE_SIZE_LIMIT_GB','0.5',.5),('CHANNELS','-1001, -1002',[-1001,-1002]),
    ('START_MESSAGE',None,''),
])
async def test_valid_settings_preserve_expected_type(key,raw,expected):
    settings,repo=service()
    assert await settings.update_setting(key,raw)
    assert repo.set_setting.await_args.kwargs['value']==expected
    assert type(repo.set_setting.await_args.kwargs['value']) is type(expected)


@pytest.mark.asyncio
async def test_invalid_legacy_values_fall_back_without_rewriting_database():
    settings,repo=service()
    repo.get_all_settings.return_value={
        'CACHE_TIME':SimpleNamespace(value=0),'PORT':SimpleNamespace(value='not-a-port'),
        'WORKERS':SimpleNamespace(value=-1),'FEATURE_FAVORITES':SimpleNamespace(value='tru'),
    }
    result=await settings.get_all_settings()
    for key in repo.get_all_settings.return_value:
        assert result[key]['value']==settings.SETTINGS_METADATA[key]['default']
    repo.set_setting.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_counts_only_acknowledged_writes():
    settings,repo=service();repo.set_setting.return_value=False
    assert await settings.import_settings({'CACHE_TIME':{'value':600}})==(0,1)
