"""Ordinary batch links validate ranges before Telegram/quota work."""
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from config.settings import settings
from core.services.filestore import FileStoreService
from handlers.deeplink import DeepLinkHandler


@pytest.mark.asyncio
@pytest.mark.parametrize('first,last', [(0, 2), (3, 2), (1, 5)])
async def test_batch_creation_rejects_invalid_or_oversized_ranges_before_api(monkeypatch, first, last):
    monkeypatch.setattr(settings.processing, 'max_batch_messages', 4)
    api = AsyncMock(return_value=SimpleNamespace(username='testbot'))
    monkeypatch.setattr('core.services.filestore.telegram_api.call_api', api)
    service = FileStoreService(None, None, SimpleNamespace())
    result = await service.create_batch_link(SimpleNamespace(get_me=AsyncMock()),
        f'https://t.me/c/1234567890/{first}', f'https://t.me/c/1234567890/{last}')
    assert result is None
    api.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', ['0_2_-100123_batch', '3_2_-100123_batch',
    '1_5_-100123_batch', '1_2_0_batch', '1_2_-100123_wrong', '1_2_-100123_batch_extra'])
async def test_encoded_batch_rejects_invalid_range_chat_or_mode_before_access(monkeypatch, payload):
    monkeypatch.setattr(settings.processing, 'max_batch_messages', 4)
    bot = SimpleNamespace(config=SimpleNamespace(ADMINS=[]),
        user_repo=SimpleNamespace(can_retrieve_file=AsyncMock(return_value=(False, 'fixture gate'))))
    message = SimpleNamespace(from_user=SimpleNamespace(id=42), reply_text=AsyncMock())
    encoded = base64.urlsafe_b64encode(payload.encode()).decode().rstrip('=')
    await DeepLinkHandler(bot)._send_dstore_files(None, message, encoded)
    bot.user_repo.can_retrieve_file.assert_not_awaited()
    message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('protected', [False, True])
@pytest.mark.parametrize('first,last', [(2, 2), (1, 4)])
async def test_valid_batch_links_preserve_single_item_and_configured_boundary(monkeypatch, protected, first, last):
    monkeypatch.setattr(settings.processing, 'max_batch_messages', 4)
    monkeypatch.setattr('core.services.filestore.telegram_api.call_api', AsyncMock(return_value=SimpleNamespace(username='testbot')))
    service = FileStoreService(None, None, SimpleNamespace())
    link = await service.create_batch_link(SimpleNamespace(get_me=AsyncMock()),
        f'https://t.me/c/1234567890/{first}', f'https://t.me/c/1234567890/{last}', protect=protected)
    decoded = base64.urlsafe_b64decode(link.split('DSTORE-')[1]+'===').decode()
    assert decoded == f'{first}_{last}_-1001234567890_{"pbatch" if protected else "batch"}'
