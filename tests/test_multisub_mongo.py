from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from bson.int64 import Int64
from pyrogram import enums

from ban_support import Cache
from favorites_recent_support import storage
from repositories.bot_settings import BotSettingsRepository
from core.services.bot_settings import BotSettingsService
from subscription_support import call_api

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.parametrize('key,kind', [('AUTH_CHANNEL', enums.ChatType.CHANNEL),
    ('AUTH_GROUPS', enums.ChatType.SUPERGROUP)])
async def test_large_telegram_ids_survive_settings_storage_and_reload(storage, monkeypatch, key, kind):
    _, pool, db = storage
    ids = [-1001234567890, -1009876543210]

    async def chat(target):
        return SimpleNamespace(id=target, type=kind)

    client = SimpleNamespace(get_chat=AsyncMock(side_effect=chat),
        get_chat_member=AsyncMock(return_value=SimpleNamespace(
            status=enums.ChatMemberStatus.ADMINISTRATOR,
            privileges=SimpleNamespace(can_invite_users=True))))
    monkeypatch.setattr('core.utils.subscription.telegram_api.call_api', call_api)
    cache = Cache()
    service = BotSettingsService(BotSettingsRepository(pool, cache), cache, telegram_client=client)
    assert await service.update_setting(key, ','.join(map(str, ids)))
    raw = await db.bot_settings.find_one({'_id': key})
    assert all(isinstance(value, Int64) for value in raw['value'])
    cache.values.clear()
    reloaded = await service.get_all_settings()
    assert reloaded[key]['value'] == ids
    assert all(type(value) is int for value in reloaded[key]['value'])
    assert (await service.get_all_settings())[key]['value'] == ids
