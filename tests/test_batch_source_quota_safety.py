"""Failed/changed source enumeration must never admit unreserved media sends."""
import base64
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from pyrogram import enums

from core.services.filestore import FileStoreService
from core.utils.quota_delivery import DeliveryProgress
from handlers.deeplink import DeepLinkHandler
from repositories.user import User


def config():
    return NS(ADMINS=[1],CHANNELS=[-100123],FILE_STORE_CHANNEL='',DISABLE_PREMIUM=False,
              NON_PREMIUM_DAILY_LIMIT=3,MESSAGE_DELETE_SECONDS=0,CUSTOM_FILE_CAPTION=None,
              BATCH_FILE_CAPTION=None,KEEP_ORIGINAL_CAPTION=False,USE_ORIGINAL_CAPTION_FOR_BATCH=False,
              AUTO_DELETE_MESSAGE=None)


@pytest.mark.asyncio
@pytest.mark.parametrize('partial',[False,True])
async def test_source_count_outage_denies_before_quota_and_delivery(partial):
    async def source(*args):
        if partial:yield NS(media=enums.MessageMediaType.DOCUMENT)
        raise ConnectionError('QA source unavailable')
    service=FileStoreService(None,None,config());service.send_channel_files=AsyncMock(return_value=(0,1,0))
    repo=NS(can_retrieve_file=AsyncMock(return_value=(True,'allowed')),
            get_user=AsyncMock(return_value=User(id=42,name='QA')),
            reserve_quota_atomic=AsyncMock(return_value=(True,1,'reserved')),
            release_quota=AsyncMock(return_value=True),can_receive_content=AsyncMock(return_value=True))
    bot=NS(config=service.config,filestore_service=service,user_repo=repo,iter_messages=source)
    message=NS(from_user=NS(id=42),reply=AsyncMock(return_value=NS(delete=AsyncMock())),reply_text=AsyncMock())
    encoded=base64.urlsafe_b64encode(b'1_2_-100123_batch').decode().rstrip('=')
    await DeepLinkHandler(bot)._send_dstore_files(None,message,encoded)
    repo.reserve_quota_atomic.assert_not_awaited();service.send_channel_files.assert_not_awaited()
    assert 'temporarily unavailable' in message.reply.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('limit',[0,1,2])
async def test_channel_delivery_never_attempts_more_media_than_reserved(monkeypatch,limit):
    docs=[NS(media=enums.MessageMediaType.DOCUMENT,caption=None,
             document=NS(file_unique_id=str(i),file_id='file'+str(i),file_name='qa.txt',file_size=10,mime_type='text/plain'),
             copy=AsyncMock(return_value=NS())) for i in range(2)]
    text=NS(media=None,empty=False,copy=AsyncMock(return_value=NS()))
    async def source(*args):
        for row in docs+[text]:yield row
    async def api(fn,*args,chat_id=None,**kwargs):return await fn(*args,**kwargs)
    monkeypatch.setattr('core.services.filestore.telegram_api.call_api',api)
    monkeypatch.setattr('core.services.filestore.asyncio.sleep',AsyncMock())
    service=FileStoreService(None,None,config());progress=DeliveryProgress()
    sent,_,media=await service.send_channel_files(NS(iter_messages=source),42,-100123,1,3,
        delivery_progress=progress,media_limit=limit)
    assert sum(d.copy.await_count for d in docs)==media==progress.attempted==progress.confirmed==limit
    assert sent==limit+1;text.copy.assert_awaited_once()


@pytest.mark.asyncio
async def test_count_stops_when_requested_quota_would_be_exceeded():
    visited=[]
    async def source(*args):
        for i in range(1000):visited.append(i);yield NS(media=enums.MessageMediaType.DOCUMENT)
    service=FileStoreService(None,None,config())
    assert await service.count_channel_media_items(NS(iter_messages=source),-100123,1,1000,max_items=4)==4
    assert len(visited)==4
