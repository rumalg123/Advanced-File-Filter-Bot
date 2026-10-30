import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from sendall_support import fixture, run


@pytest.mark.asyncio
@pytest.mark.parametrize('stage,confirmed,uncertain', [
    ('missing-media', 0, False), ('first-lookup', 0, False),
    ('second-lookup', 1, False), ('second-send', 1, True), ('after-send', 1, False)])
async def test_sendall_settlement_distinguishes_unsent_and_unknown_delivery(monkeypatch, stage, confirmed, uncertain):
    handler, client, query, _, reservation = fixture(monkeypatch)
    media = handler.bot.media_repo.find_file.return_value
    if stage == 'missing-media':
        handler.bot.media_repo.find_file.return_value = None
    elif stage == 'first-lookup':
        handler.bot.media_repo.find_file.side_effect = asyncio.CancelledError()
    elif stage == 'second-lookup':
        handler.bot.media_repo.find_file.side_effect = [media, asyncio.CancelledError()]
    elif stage == 'second-send':
        client.send_cached_media.side_effect = [SimpleNamespace(), asyncio.CancelledError()]
    else:
        monkeypatch.setattr('handlers.callbacks_handlers.file.asyncio.sleep', AsyncMock(side_effect=asyncio.CancelledError()))
    if stage == 'missing-media':
        await run(handler, client, query)
    else:
        with pytest.raises(asyncio.CancelledError):
            await run(handler, client, query)
    handler.bot.user_repo.settle_quota_delivery.assert_awaited_once_with(
        42, reservation, confirmed, uncertain=uncertain)


@pytest.mark.asyncio
async def test_sendall_recent_history_failure_does_not_reclassify_sent_files(monkeypatch):
    handler, client, query, status, reservation = fixture(monkeypatch)
    handler.bot.feature_service = SimpleNamespace(record_recent_file=AsyncMock(side_effect=ConnectionError('QA history unavailable')))
    await run(handler, client, query)
    final = status.edit_text.await_args.args[0]
    assert 'Sent: 2' in final and 'Failed:' not in final
    handler.bot.user_repo.settle_quota_delivery.assert_awaited_once_with(42, reservation, 2, uncertain=False)
