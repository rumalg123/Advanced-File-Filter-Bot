"""PH-022: setup errors and cancellation must settle bulk deep-link quota."""
import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.utils.quota_calendar import QuotaReservation
from handlers.deeplink import DeepLinkHandler
from repositories.user import User


def fixture():
    reservation = QuotaReservation(2, date(2026, 10, 29), 'bulk-token')
    repo = SimpleNamespace(
        can_retrieve_file=AsyncMock(return_value=(True, 'allowed')),
        get_user=AsyncMock(return_value=User(id=42, name='QA')),
        reserve_quota_atomic=AsyncMock(return_value=(True, reservation, 'reserved')),
        settle_quota_delivery=AsyncMock(return_value=True),
    )
    bot = SimpleNamespace(
        config=SimpleNamespace(ADMINS=[], DISABLE_PREMIUM=False,
            NON_PREMIUM_DAILY_LIMIT=10, MESSAGE_DELETE_SECONDS=0,
            CUSTOM_FILE_CAPTION=None, BATCH_FILE_CAPTION=None,
            KEEP_ORIGINAL_CAPTION=False, AUTO_DELETE_MESSAGE=None),
        user_repo=repo,
        cache=SimpleNamespace(get=AsyncMock(return_value={
            'user_id':42,'files':[{'file_unique_id':'one'}, {'file_unique_id':'two'}]})),
        media_repo=SimpleNamespace(find_files_batch=AsyncMock(return_value={})),
        filestore_service=SimpleNamespace(get_batch_data=AsyncMock(return_value=[{},{}]),
            send_batch_files=AsyncMock(side_effect=asyncio.CancelledError)),
    )
    message=SimpleNamespace(from_user=SimpleNamespace(id=42),
        reply_text=AsyncMock(), delete=AsyncMock())
    return DeepLinkHandler(bot), repo, reservation, message


@pytest.mark.asyncio
@pytest.mark.parametrize('error', [RuntimeError, asyncio.CancelledError])
async def test_search_deeplink_settles_when_progress_message_fails(error):
    handler, repo, reservation, message = fixture()
    message.reply_text.side_effect=error('setup failed')
    with pytest.raises(error):
        await handler._send_all_from_search(SimpleNamespace(), message, 'owned-search')
    repo.settle_quota_delivery.assert_awaited_once_with(42, reservation, 0, uncertain=False)


@pytest.mark.asyncio
async def test_missing_media_is_definitely_unsent_not_uncertain(monkeypatch):
    handler, repo, reservation, message = fixture()
    monkeypatch.setattr('handlers.deeplink.telegram_api.call_api', AsyncMock())
    await handler._send_all_from_search(SimpleNamespace(delete_messages=AsyncMock()), message, 'owned-search')
    repo.settle_quota_delivery.assert_awaited_once_with(42, reservation, 0, uncertain=False)


@pytest.mark.asyncio
async def test_batch_cancel_before_send_refunds_reservation():
    handler, repo, reservation, message = fixture()
    with pytest.raises(asyncio.CancelledError):
        await handler._send_batch(SimpleNamespace(), message, 'batch')
    repo.settle_quota_delivery.assert_awaited_once_with(42, reservation, 0, uncertain=False)


@pytest.mark.asyncio
@pytest.mark.parametrize('tokenized', [False, True])
@pytest.mark.parametrize('cancel_during_send', [False, True])
async def test_batch_service_keeps_confirmed_progress_on_cancellation(monkeypatch, tokenized, cancel_during_send):
    from core.services.filestore import FileStoreService
    from core.utils.quota_delivery import bulk_delivery_quota

    repo=SimpleNamespace(settle_quota_delivery=AsyncMock(return_value=True),
                         release_quota=AsyncMock(return_value=True))
    reservation=QuotaReservation(2, date(2026,10,29), 'token' if tokenized else None)
    config=SimpleNamespace(CUSTOM_FILE_CAPTION=None, BATCH_FILE_CAPTION=None,
        KEEP_ORIGINAL_CAPTION=False, USE_ORIGINAL_CAPTION_FOR_BATCH=False,
        MESSAGE_DELETE_SECONDS=0, AUTO_DELETE_MESSAGE=None)
    service=FileStoreService(None, None, config)
    calls=0
    async def send(*args, **kwargs):
        nonlocal calls
        calls+=1
        if calls==2: raise asyncio.CancelledError()
        return SimpleNamespace()
    async def delay(*args):
        if not cancel_during_send: raise asyncio.CancelledError()
    monkeypatch.setattr('core.services.filestore.telegram_api.call_api', send)
    monkeypatch.setattr('core.services.filestore.asyncio.sleep', delay)
    with pytest.raises(asyncio.CancelledError):
        async with bulk_delivery_quota(repo,42,reservation) as progress:
            await service.send_batch_files(SimpleNamespace(send_cached_media=AsyncMock()),42,
                [{'file_id':'one'},{'file_id':'two'}], delivery_progress=progress)
    if tokenized:
        repo.settle_quota_delivery.assert_awaited_once_with(42,reservation,1,uncertain=cancel_during_send)
    else:
        repo.release_quota.assert_awaited_once()
        refunded=repo.release_quota.await_args.args[1]
        assert refunded==1 and refunded.quota_day=='2026-10-29'
