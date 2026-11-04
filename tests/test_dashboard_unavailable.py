"""BUG-120: unavailable verification/statistics must not look like confirmed data."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock

import pytest

from core.cache.config import CacheKeyGenerator
from core.database.errors import SearchBackendUnavailableError
from dashboard_support import dashboard_fixture
from handlers.features import FeatureHandler
from repositories.media import MediaRepository
from test_search_backend_failure import MemoryCache


@pytest.mark.asyncio
async def test_failed_candidate_lookup_cannot_be_returned_as_confirmed_unmet_search():
    row={'_id':'missing','query':'Missing','count':3}
    service,repository,media,_=dashboard_fixture([row])
    media.has_matching_file.side_effect=RuntimeError('private database details')
    with pytest.raises(SearchBackendUnavailableError):await service.dashboard()
    repository.resolve_zero_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancelled_lookup_propagates_without_deleting_analytics():
    row={'_id':'missing','query':'Missing','count':3}
    service,repository,media,_=dashboard_fixture([row])
    media.has_matching_file.side_effect=asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):await service.dashboard()
    repository.resolve_zero_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_literal_query_invalid_under_current_filters_is_retained_but_not_presented():
    row={'_id':'movie year:','query':'movie year:','count':3}
    service,repository,media,_=dashboard_fixture([row])
    assert (await service.dashboard())['zero_results']==[]
    media.has_matching_file.assert_not_awaited()
    repository.resolve_zero_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_error_keeps_confirmed_match_out_of_unmet_list_without_aborting_read():
    row={'_id':'found','query':'Found','count':3}
    service,repository,media,_=dashboard_fixture([row])
    media.has_matching_file.return_value=True
    repository.resolve_zero_result.side_effect=RuntimeError('cleanup unavailable')
    assert (await service.dashboard())['zero_results']==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('error',[RuntimeError('private count details'),SearchBackendUnavailableError('private URI')])
async def test_admin_receives_safe_retry_feedback_for_failed_dashboard_build(error):
    handler=object.__new__(FeatureHandler)
    handler.service=SimpleNamespace(dashboard=AsyncMock(side_effect=error))
    message=SimpleNamespace(reply_text=AsyncMock())
    await handler.content_dashboard_command(None,message)
    text=message.reply_text.await_args.args[0]
    assert 'temporarily unavailable' in text.lower() and 'private' not in text
    assert 'Files:' not in text


class Pool:
    def __init__(self,collection):self.collection=collection
    async def get_collection(self,name):return self.collection
    async def execute_with_retry(self,method,*args,**kwargs):return await method(*args,**kwargs)


def stats_fixture(error=None,cached=None):
    cache=MemoryCache()
    if cached is not None:cache.values[CacheKeyGenerator.file_stats()]=cached
    facets=[{'total':[{'count':3}],'total_size':[{'size':4096}],
             'by_type':[{'_id':'document','count':3,'size':4096}]}]
    cursor=SimpleNamespace(to_list=AsyncMock(return_value=facets,side_effect=error))
    collection=SimpleNamespace(aggregate=Mock(return_value=cursor))
    return MediaRepository(Pool(collection),cache),cache,collection


@pytest.mark.asyncio
async def test_single_database_aggregation_failure_cannot_become_zero_file_statistics():
    repo,cache,_=stats_fixture(error=RuntimeError('aggregation unavailable'))
    with pytest.raises(RuntimeError):await repo.get_file_stats()
    assert not cache.writes
    # Other aggregation callers retain their existing compatibility behavior.
    assert await repo.aggregate([])==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('cached',[
    {},{'total_files':0}, {'total_files':-1,'total_size':1,'by_type':{}},
    {'total_files':'3','total_size':4096,'by_type':{}},
    {'total_files':True,'total_size':4096,'by_type':{}},
    {'total_files':3,'total_size':None,'by_type':{}},
    {'total_files':3,'total_size':4096,'by_type':[]},
])
async def test_malformed_stats_cache_recomputes_instead_of_reporting_bad_totals(cached):
    repo,cache,collection=stats_fixture(cached=cached)
    result=await repo.get_file_stats()
    assert result['total_files']==3 and result['total_size']==4096
    collection.aggregate.assert_called_once()
    assert CacheKeyGenerator.file_stats() in cache.deletes


@pytest.mark.asyncio
async def test_valid_statistics_cache_still_avoids_database_aggregation():
    expected={'total_files':3,'total_size':4096,'by_type':{}}
    repo,_,collection=stats_fixture(cached=expected)
    assert await repo.get_file_stats()==expected
    collection.aggregate.assert_not_called()
