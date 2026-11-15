"""All indexing controls operate on the same persisted, restart-safe registry."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from core.services.bot_settings import BotSettingsService
from core.services.filestore import FileStoreService
from repositories.bot_settings import BotSettingsRepository
from repositories.channel import ChannelRepository
from test_repository_crud_contracts import Cache, mongo_pool  # noqa: F401


@pytest.mark.asyncio
async def test_environment_commands_settings_and_restarts_share_one_registry(mongo_pool, monkeypatch):
    monkeypatch.setenv('CHANNELS', '-10011,-10022')
    cache = Cache()
    channels = ChannelRepository(mongo_pool, cache)
    saved = BotSettingsRepository(mongo_pool, cache)
    service = BotSettingsService(saved, cache, channel_repo=channels)
    await service.initialize_settings()
    assert await service.get_setting('CHANNELS') == [-10022, -10011]
    assert await channels.add_channel(-10033, channel_title='Preserved title', added_by=1)
    assert set((await service.get_all_settings())['CHANNELS']['value']) == {-10011, -10022, -10033}
    # Materialize the cached active projection before editing it.
    assert len(await channels.get_active_channels()) == 3
    assert await channels.update(-10022, {'indexed_count': 8})
    assert await service.update_setting('CHANNELS', '-10022, -10044')
    assert await service.get_setting('CHANNELS') == [-10044, -10022]
    assert {c.channel_id for c in await channels.get_active_channels()} == {-10022, -10044}
    assert (await channels.find_by_id(-10022)).indexed_count == 8
    assert not (await channels.find_by_id(-10033)).enabled
    assert (await channels.find_by_id(-10033)).channel_title == 'Preserved title'
    # An old stored bootstrap value must not revive explicit removals.
    restarted_channels = ChannelRepository(mongo_pool, cache)
    restarted = BotSettingsService(saved, cache, channel_repo=restarted_channels)
    await restarted.initialize_settings()
    assert await restarted.get_setting('CHANNELS') == [-10044, -10022]
    assert await restarted_channels.remove_channel(-10022)
    await restarted.initialize_settings()
    assert await restarted.get_setting('CHANNELS') == [-10044]
    assert await restarted_channels.add_channel(-10022)
    assert await restarted.get_setting('CHANNELS') == [-10044, -10022]
    assert await restarted.reset_to_default('CHANNELS')
    await restarted.initialize_settings()
    assert await restarted.get_setting('CHANNELS') == []


@pytest.mark.asyncio
async def test_legacy_uses_current_index_registry_and_independent_file_sources(mongo_pool):
    channels = ChannelRepository(mongo_pool, Cache())
    await channels.seed_channels([-10011])
    config = NS(ADMINS=[1], CHANNELS=[-10011], FILE_STORE_CHANNEL=[-10022])
    service = FileStoreService(None, None, config, channel_repo=channels)
    assert await service.can_read_legacy_batch(None, 42, -10011)
    assert await service.can_read_legacy_batch(None, 42, -10022)
    assert not await channels.find_by_id(-10022)
    await channels.remove_channel(-10011)
    assert not await service.can_read_legacy_batch(None, 42, -10011)
    assert await service.can_read_legacy_batch(None, 42, -10022)
    assert await service.can_read_legacy_batch(None, 1, -10099)
    assert not await service.can_read_legacy_batch(None, 42, -10099)


@pytest.mark.asyncio
async def test_concurrent_channel_additions_remain_visible_in_settings(mongo_pool):
    cache = Cache()
    channels = ChannelRepository(mongo_pool, cache)
    service = BotSettingsService(BotSettingsRepository(mongo_pool, cache), cache, channel_repo=channels)
    assert all(await asyncio.gather(*(channels.add_channel(-10000-i) for i in range(12))))
    assert set(await service.get_setting('CHANNELS')) == {-10000-i for i in range(12)}
    assert await service.update_setting('CHANNELS', [])
    assert await service.get_setting('CHANNELS') == []


@pytest.mark.parametrize('value', ['@not_an_id', '-10011 nope', [True], True, False, {}, '1.2'])
@pytest.mark.asyncio
async def test_invalid_indexing_targets_do_not_modify_registry(mongo_pool, value):
    cache = Cache()
    channels = ChannelRepository(mongo_pool, cache)
    await channels.add_channel(-10011)
    service = BotSettingsService(BotSettingsRepository(mongo_pool, cache), cache, channel_repo=channels)
    with pytest.raises(ValueError):
        await service.update_setting('CHANNELS', value)
    assert await service.get_setting('CHANNELS') == [-10011]


@pytest.mark.asyncio
async def test_registry_read_failure_is_not_presented_as_an_empty_setting():
    channels = ChannelRepository(NS(get_collection=AsyncMock(side_effect=ConnectionError('QA unavailable'))), Cache())
    service = BotSettingsService(NS(), Cache(), channel_repo=channels)
    with pytest.raises(ConnectionError):
        await service.get_setting('CHANNELS')


@pytest.mark.asyncio
async def test_startup_registers_current_sources_without_readding_disabled_ones():
    from handlers.channel import ChannelHandler
    handler = object.__new__(ChannelHandler)
    handler.channel_repo = NS(add_channel=AsyncMock())
    handler.update_handlers = AsyncMock()
    await handler._setup_initial_channels()
    handler.channel_repo.add_channel.assert_not_awaited()
    handler.update_handlers.assert_awaited_once()
