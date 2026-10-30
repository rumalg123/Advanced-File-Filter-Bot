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
        can_receive_content=AsyncMock(return_value=True),
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
async def test_batch_backend_outage_edits_status_and_refunds_unsent_quota():
    from core.database.errors import SearchBackendUnavailableError, FILE_LOOKUP_RETRY_MESSAGE
    handler,repo,reservation,message=fixture()
    progress=SimpleNamespace(edit_text=AsyncMock())
    message.reply_text.return_value=progress
    handler.bot.media_repo.find_files_batch.side_effect=SearchBackendUnavailableError('private backend details')
    await handler._send_all_from_search(SimpleNamespace(),message,'owned-search')
    progress.edit_text.assert_awaited_once_with(FILE_LOOKUP_RETRY_MESSAGE)
    repo.settle_quota_delivery.assert_awaited_once_with(42,reservation,0,uncertain=False)


@pytest.mark.asyncio
async def test_feature_file_list_outage_does_not_claim_files_are_missing():
    from core.database.errors import SearchBackendUnavailableError, FILE_LOOKUP_RETRY_MESSAGE
    from handlers.features import FeatureHandler
    handler=object.__new__(FeatureHandler)
    handler.bot=SimpleNamespace(media_repo=SimpleNamespace(find_files_batch=AsyncMock(
        side_effect=SearchBackendUnavailableError('private backend details'))))
    handler._reply_with_cleanup=AsyncMock()
    message=SimpleNamespace()
    await handler._send_file_list(message,'Favorites',['one'])
    handler._reply_with_cleanup.assert_awaited_once_with(message,FILE_LOOKUP_RETRY_MESSAGE)


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


@pytest.mark.asyncio
@pytest.mark.parametrize('workflow',['channel','typed_search'])
async def test_other_bulk_workflows_refund_when_status_setup_fails(workflow):
    import base64
    handler,repo,reservation,message=fixture()
    if workflow=='channel':
        handler.bot.filestore_service.count_channel_media_items=AsyncMock(return_value=2)
        message.reply=AsyncMock(side_effect=RuntimeError('status setup failed'))
        encoded=base64.urlsafe_b64encode(b'1_2_-100123_batch').decode().rstrip('=')
        invoke=handler._send_dstore_files(SimpleNamespace(),message,encoded)
    else:
        handler.bot.file_service=SimpleNamespace(search_files_with_access_check=AsyncMock(
            return_value=([SimpleNamespace(),SimpleNamespace()],0,2,True,'allowed')))
        message.reply_text.side_effect=RuntimeError('status setup failed')
        invoke=handler._send_all_files(SimpleNamespace(),message,'qa_title','document')
    with pytest.raises(RuntimeError,match='status setup failed'):
        await invoke
    repo.settle_quota_delivery.assert_awaited_once_with(42,reservation,0,uncertain=False)


@pytest.mark.asyncio
async def test_channel_service_preserves_confirmed_count_on_mid_send_cancellation(monkeypatch):
    from pyrogram import enums
    from core.services.filestore import FileStoreService
    from core.utils.quota_delivery import bulk_delivery_quota
    handler,repo,reservation,_=fixture()
    config=handler.bot.config
    config.USE_ORIGINAL_CAPTION_FOR_BATCH=False
    service=FileStoreService(None,None,config)
    async def messages(*args):
        for i in range(2):
            yield SimpleNamespace(media=enums.MessageMediaType.DOCUMENT,caption=None,
                document=SimpleNamespace(file_unique_id=str(i),file_id='tg-'+str(i),
                    file_name='qa.txt',file_size=10,mime_type='text/plain'),copy=AsyncMock())
    async def no_delay(*args):pass
    monkeypatch.setattr('core.services.filestore.asyncio.sleep',no_delay)
    monkeypatch.setattr('core.services.filestore.telegram_api.call_api',
        AsyncMock(side_effect=[SimpleNamespace(),asyncio.CancelledError()]))
    with pytest.raises(asyncio.CancelledError):
        async with bulk_delivery_quota(repo,42,reservation) as progress:
            await service.send_channel_files(SimpleNamespace(iter_messages=messages),42,-100123,1,2,
                delivery_progress=progress)
    repo.settle_quota_delivery.assert_awaited_once_with(42,reservation,1,uncertain=True)
