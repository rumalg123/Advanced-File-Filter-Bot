"""Reference shortening resolves the same media record through actual MongoDB."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from pyrogram import enums

from core.services.filestore import FileStoreService
from repositories.media import MediaFile,FileType,MediaRepository
from test_repository_crud_contracts import Cache,mongo_pool  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize('protect',[False,True])
async def test_shortened_links_resolve_the_original_mongo_record(mongo_pool,monkeypatch,protect):
    cache=Cache();cache.advance_search_generation=AsyncMock(return_value=17)
    cache.ensure_search_generation=AsyncMock(return_value=17)
    repo=MediaRepository(mongo_pool,cache)
    file=MediaFile('qa-unique','qa-canonical-file-id','r'*80,'qa.txt',10,FileType.DOCUMENT,'text/plain',None)
    assert (await repo.save_media(file))[0]
    service=FileStoreService(repo,cache,NS())
    message=NS(reply_to_message=NS(media=enums.MessageMediaType.DOCUMENT,document=NS(file_unique_id=file.file_unique_id)))
    client=NS(get_me=AsyncMock(return_value=NS(username='qa_bot')))
    async def api(fn,*args,chat_id=None,**kwargs):return await fn(*args,**kwargs)
    monkeypatch.setattr('core.services.filestore.telegram_api.call_api',api)
    link=await service.create_file_link(client,message,protect)
    assert link and len(link.split('start=')[1])<=64
    reference,is_protected=service.decode_file_identifier(link.split('start=')[1])
    restored=await repo.find_file(reference)
    assert restored.file_id==file.file_id and restored.file_unique_id==file.file_unique_id
    assert is_protected is protect
    assert (await (await repo.get_collection()).find_one({'_id':file.file_id}))['file_ref']==reference
