"""Valid legacy Wzgram IDs can omit file_reference bytes."""
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyrogram.file_id import FileId, FileType as TelegramFileType

from core.utils.helpers import extract_file_ref
from repositories.media import MediaFile, MediaRepository, FileType
from test_repository_crud_contracts import Cache, mongo_pool


def encoded(media_id,reference=b''):
    return FileId(file_type=TelegramFileType.DOCUMENT,dc_id=2,media_id=media_id,
                  access_hash=123456,file_reference=reference).encode()


def test_valid_ids_without_reference_bytes_get_distinct_stable_fallbacks():
    first,second=encoded(1001),encoded(1002)
    assert FileId.decode(first).file_reference==b''
    one,two=extract_file_ref(first),extract_file_ref(second)
    assert one and two and one!=two
    assert extract_file_ref(first)==one


def test_nonempty_telegram_reference_retains_existing_encoding():
    reference=b'qa-reference'
    assert extract_file_ref(encoded(1001,reference))==base64.urlsafe_b64encode(reference).decode().rstrip('=')


@pytest.mark.asyncio
async def test_two_legacy_files_save_under_real_unique_sparse_reference_index(mongo_pool):
    col=mongo_pool.database.media_files
    await col.create_index('file_ref',unique=True,sparse=True,name='file_ref_index')
    await col.create_index('file_unique_id',unique=True,name='unique_file_id_idx')
    repo=MediaRepository(mongo_pool,Cache())
    repo.cache_invalidator=SimpleNamespace(invalidate_all_search_results=AsyncMock(),invalidate_file_stats=AsyncMock())
    for number in (1001,1002):
        file_id=encoded(number)
        media=MediaFile('qa-legacy-'+str(number),file_id,extract_file_ref(file_id),
            'QA legacy '+str(number),10,FileType.DOCUMENT,'application/octet-stream',None)
        assert (await repo.save_media(media))[:2]==(True,1)
    assert await col.count_documents({})==2


@pytest.mark.asyncio
async def test_nullable_input_references_are_normalized_only_when_saving(mongo_pool):
    col=mongo_pool.database.media_files
    await col.create_index('file_ref',unique=True,sparse=True,name='file_ref_index')
    repo=MediaRepository(mongo_pool,Cache())
    repo.cache_invalidator=SimpleNamespace(invalidate_all_search_results=AsyncMock(),invalidate_file_stats=AsyncMock())
    for number in (1001,1002):
        media=MediaFile('qa-null-'+str(number),encoded(number),None,'QA nullable',10,
                        FileType.DOCUMENT,'application/octet-stream',None)
        assert (await repo.save_media(media))[:2]==(True,1)
        assert media.file_ref is None  # preserve caller input
        assert (await col.find_one({'file_unique_id':media.file_unique_id}))['file_ref']
    # Reading an old null reference must not invent an unpersisted link alias.
    legacy=MediaFile('qa-old',encoded(1003),None,'QA old null',10,FileType.DOCUMENT,
                     'application/octet-stream',None)
    await col.insert_one(repo._entity_to_dict(legacy))
    assert (await repo.find_file('qa-old')).file_ref is None
    assert (await repo.find_file('qa-old')).file_ref is None
