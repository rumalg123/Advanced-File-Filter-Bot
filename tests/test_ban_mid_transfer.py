from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyrogram import enums

from core.services.filestore import FileStoreService
from handlers.deeplink import DeepLinkHandler
from repositories.media import MediaFile,FileType
from test_deeplink_bulk_quota import fixture as deep_fixture
from sendall_support import fixture as callback_fixture,run


def media(uid):
    return MediaFile(file_unique_id=uid,file_id='tg-'+uid,file_ref=None,file_name='QA.txt',
        file_size=10,file_type=FileType.DOCUMENT,mime_type='text/plain',caption=None)


@pytest.mark.asyncio
async def test_private_sendall_stops_after_ban_and_refunds_definitely_unsent_files(monkeypatch):
    handler,client,query,_,reservation=callback_fixture(monkeypatch)
    handler.bot.user_repo.can_receive_content=AsyncMock(side_effect=[True,False])
    await run(handler,client,query)
    assert client.send_cached_media.await_count==1
    handler.bot.user_repo.settle_quota_delivery.assert_awaited_once_with(42,reservation,1,uncertain=False)


@pytest.mark.asyncio
@pytest.mark.parametrize('workflow',['search','typed-search','json-batch','channel'])
async def test_other_bulk_entrypoints_stop_after_ban_without_charging_unsent_media(monkeypatch,workflow):
    handler,repo,reservation,message=deep_fixture()
    repo.can_receive_content=AsyncMock(side_effect=[True,False])
    handler.bot.config.USE_ORIGINAL_CAPTION_FOR_BATCH=False
    client=SimpleNamespace(send_cached_media=AsyncMock(return_value=SimpleNamespace()),delete_messages=AsyncMock())
    status=SimpleNamespace(chat=SimpleNamespace(id=42),id=100,edit_text=AsyncMock(),delete=AsyncMock())
    message.reply_text.return_value=status;message.reply=AsyncMock(return_value=status)
    async def api(operation,*args,chat_id=None,**kwargs):return await operation(*args,**kwargs)
    monkeypatch.setattr('handlers.deeplink.telegram_api.call_api',api)
    monkeypatch.setattr('handlers.deeplink.asyncio.sleep',AsyncMock())
    if workflow=='search':
        handler.bot.media_repo.find_files_batch.return_value={'one':media('one'),'two':media('two')}
        await handler._send_all_from_search(client,message,'owned-search')
    elif workflow=='typed-search':
        handler.bot.file_service=SimpleNamespace(search_files_with_access_check=AsyncMock(return_value=([media('one'),media('two')],0,2,True,None)))
        await handler._send_all_files(client,message,'qa','document')
    else:
        service=FileStoreService(None,None,handler.bot.config)
        handler.bot.filestore_service=service
        if workflow=='json-batch':
            service.get_batch_data=AsyncMock(return_value=[{'file_id':'tg-one'},{'file_id':'tg-two'}])
            await handler._send_batch(client,message,'batch')
        else:
            import base64
            copies=[]
            async def messages(*args):
                for uid in ['one','two']:
                    copy=AsyncMock(return_value=SimpleNamespace());copies.append(copy)
                    yield SimpleNamespace(media=enums.MessageMediaType.DOCUMENT,caption=None,
                        document=SimpleNamespace(file_unique_id=uid,file_id='tg-'+uid,file_name='QA.txt',file_size=10,mime_type='text/plain'),copy=copy)
            handler.bot.iter_messages=messages
            service.count_channel_media_items=AsyncMock(return_value=2)
            encoded=base64.urlsafe_b64encode(b'1_2_-100123_batch').decode().rstrip('=')
            await handler._send_dstore_files(client,message,encoded)
            assert sum(copy.await_count for copy in copies)==1
    if workflow!='channel':assert client.send_cached_media.await_count==1
    repo.settle_quota_delivery.assert_awaited_once_with(42,reservation,1,uncertain=False)
