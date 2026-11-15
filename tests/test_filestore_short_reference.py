"""Long file refs must be updated through the record's MongoDB identity."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import base64

import pytest
from pyrogram import enums

from core.services.filestore import FileStoreService
from repositories.media import MediaFile,FileType


@pytest.mark.asyncio
@pytest.mark.parametrize('protect',[False,True])
async def test_long_reference_shortening_updates_file_unique_id(monkeypatch,protect):
    file=MediaFile('qa-unique','telegram-file-id','r'*80,'qa.txt',10,FileType.DOCUMENT,'text/plain',None)
    repo=NS(find_file=AsyncMock(return_value=file),update=AsyncMock(return_value=True))
    service=FileStoreService(repo,None,NS())
    media=NS(file_unique_id=file.file_unique_id)
    message=NS(reply_to_message=NS(media=enums.MessageMediaType.DOCUMENT,document=media))
    client=NS(get_me=AsyncMock(return_value=NS(username='qa_bot')))
    async def api(fn,*args,chat_id=None,**kwargs):return await fn(*args,**kwargs)
    monkeypatch.setattr('core.services.filestore.telegram_api.call_api',api)
    link=await service.create_file_link(client,message,protect)
    repo.update.assert_awaited_once()
    assert repo.update.await_args.args[0]==file.file_unique_id
    token=link.split('start=')[1];assert len(token)<=64
    decoded=base64.urlsafe_b64decode(token+'===').decode()
    assert decoded==('filep_' if protect else 'file_')+repo.update.await_args.args[1]['file_ref']
