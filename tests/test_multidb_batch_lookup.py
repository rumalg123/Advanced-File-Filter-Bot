"""Delivery batches must distinguish unavailable sources from absent files."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.database.errors import SearchBackendUnavailableError
from repositories.media import MediaRepository


def row(uid='u'):
    return {'_id': 'file-'+uid, 'file_unique_id': uid, 'file_ref': 'ref-'+uid,
        'file_name': 'QA file', 'file_size': 1, 'file_type': 'document', 'mime_type': None,
        'caption': None, 'indexed_at': '2026-10-29T00:00:00+00:00'}


def repository(*, owned=False, documents=None, error=None):
    cache=SimpleNamespace(get=AsyncMock(return_value=None), set=AsyncMock())
    manager=SimpleNamespace(media_owners=None,
        find_many_in_all_databases=AsyncMock(return_value=documents or [], side_effect=error))
    cursor=SimpleNamespace(to_list=AsyncMock(side_effect=lambda **kwargs: [dict(d) for d in documents or []]))
    collection=SimpleNamespace(find=lambda *args,**kwargs:cursor)
    pool=SimpleNamespace(get_collection=AsyncMock(return_value=collection))
    async def execute(fn,*args,**kwargs):return await fn(*args,**kwargs)
    pool.execute_with_retry=execute
    manager.get_all_databases=AsyncMock(return_value=[pool],side_effect=error)
    if owned:
        async def find(uid):
            if uid=='missing':return None
            if uid=='bad':raise ConnectionError('owner unavailable')
            return row(uid)
        manager.media_owners=SimpleNamespace(find=AsyncMock(side_effect=find))
    repo=MediaRepository(None,cache,manager)
    return repo,cache,manager


@pytest.mark.asyncio
async def test_unavailable_database_is_not_reported_as_missing_or_partially_cached():
    repo,cache,_=repository(error=ConnectionError('simulated source failure'))
    with pytest.raises(SearchBackendUnavailableError):await repo.find_files_batch(['u','missing'])
    cache.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_canonical_owners_are_not_silently_overwritten():
    repo,cache,_=repository(documents=[row(),dict(row(),_id='other-file')])
    with pytest.raises(SearchBackendUnavailableError):await repo.find_files_batch(['u'])
    cache.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_distributed_batch_preserves_missing_and_duplicate_input_contract():
    repo,_,_=repository(documents=[row()])
    result=await repo.find_files_batch(['u','missing','u'])
    assert result['u'].file_id=='file-u' and result['missing'] is None


@pytest.mark.asyncio
async def test_registry_batch_uses_authoritative_owner_even_when_cache_contains_stale_data():
    repo,cache,manager=repository(owned=True)
    cache.get.return_value=row('stale')
    result=await repo.find_files_batch(['u','missing'])
    assert result['u'].file_unique_id=='u' and result['missing'] is None
    manager.find_many_in_all_databases.assert_not_awaited()
    with pytest.raises(SearchBackendUnavailableError):await repo.find_files_batch(['u','bad'])
    cache.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_batch_does_not_contact_any_source():
    repo,_,manager=repository()
    assert await repo.find_files_batch([])=={}
    manager.find_many_in_all_databases.assert_not_awaited()
