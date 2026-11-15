"""File-only sources restore old URLs without subscribing them to indexing."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from core.services.filestore import FileStoreService
from core.services.bot_settings import BotSettingsService


@pytest.mark.parametrize('value', [
    [-10011, -10022], ['-10011', '-10022'], (-10011, -10022),
    '-10011 -10022', '-10011,-10022', '-10011, -10022', -10022,
])
@pytest.mark.asyncio
async def test_legacy_file_sources_accept_persisted_and_environment_forms(value):
    service = FileStoreService(None, None, NS(ADMINS=[1], CHANNELS=[], FILE_STORE_CHANNEL=value))
    assert await service.can_read_legacy_batch(None, 42, -10022)
    assert not await service.can_read_legacy_batch(None, 42, -10099)


@pytest.mark.asyncio
async def test_settings_roundtrip_keeps_multiple_file_sources_authorized():
    repo = NS(set_setting=AsyncMock(return_value=True), get_all_settings=AsyncMock(return_value={}))
    settings = BotSettingsService(repo, NS())
    assert await settings.update_setting('FILE_STORE_CHANNEL', '-10011 -10022')
    value = repo.set_setting.await_args.kwargs['value']
    assert value == [-10011, -10022]
    service = FileStoreService(None, None, NS(ADMINS=[1], CHANNELS=[], FILE_STORE_CHANNEL=value))
    assert await service.can_read_legacy_batch(None, 42, -10011)
    assert await service.can_read_legacy_batch(None, 42, -10022)


@pytest.mark.asyncio
async def test_public_creator_uses_membership_without_a_source_list(monkeypatch):
    from pyrogram import enums
    async def api(fn, *args, chat_id=None, **kwargs):
        return await fn(*args, **kwargs)
    monkeypatch.setattr('core.services.filestore.telegram_api.call_api', api)
    client = NS(get_chat_member=AsyncMock(return_value=NS(status=enums.ChatMemberStatus.MEMBER)),
                get_messages=AsyncMock(return_value=NS(empty=False)),
                get_me=AsyncMock(return_value=NS(username='qa_bot')))
    repo = NS(create_batch_link=AsyncMock(return_value=True))
    service = FileStoreService(None, None,
        NS(ADMINS=[1], PUBLIC_FILE_STORE=True, CHANNELS=[], FILE_STORE_CHANNEL=[]), repo)
    link = await service.create_batch_link(client, 'https://t.me/c/1234567890/1',
                                           'https://t.me/c/1234567890/2', created_by=42)
    assert link and '?start=DSTORE-BL-' in link
    assert repo.create_batch_link.await_args.args[0].source_chat_id == -1001234567890
