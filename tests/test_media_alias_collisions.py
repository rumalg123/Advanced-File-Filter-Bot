"""A conflicting alias is not proof of a duplicate canonical media identity."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from repositories.media import MediaFile, MediaRepository, FileType
from test_repository_crud_contracts import Cache, mongo_pool
from test_media_reference_compatibility import encoded


@pytest.mark.asyncio
async def test_alias_collision_without_canonical_duplicate_is_an_error(mongo_pool):
    col=mongo_pool.database.media_files
    await col.create_index('file_ref',unique=True,sparse=True,name='file_ref_index')
    repo=MediaRepository(mongo_pool,Cache())
    repo.cache_invalidator=SimpleNamespace(invalidate_all_search_results=AsyncMock(),invalidate_file_stats=AsyncMock())
    first=MediaFile('first',encoded(1001),'shared-ref','First',10,FileType.DOCUMENT,None,None)
    second=MediaFile('second',encoded(1002),'shared-ref','Second',10,FileType.DOCUMENT,None,None)
    assert (await repo.save_media(first))[:2]==(True,1)
    assert await repo.save_media(second)==(False,2,None)


@pytest.mark.asyncio
async def test_existing_alias_cannot_be_misidentified_as_incoming_canonical_file(mongo_pool):
    repo=MediaRepository(mongo_pool,Cache())
    repo.cache_invalidator=SimpleNamespace(invalidate_all_search_results=AsyncMock(),invalidate_file_stats=AsyncMock())
    first=MediaFile('first',encoded(1001),'second','First',10,FileType.DOCUMENT,None,None)
    second=MediaFile('second',encoded(1002),'fresh-ref','Second',10,FileType.DOCUMENT,None,None)
    assert (await repo.save_media(first))[:2]==(True,1)
    assert await repo.save_media(second)==(False,2,None)
    assert await mongo_pool.database.media_files.count_documents({})==1
