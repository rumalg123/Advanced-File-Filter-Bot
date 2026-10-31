"""BUG-121: stale dashboard cleanup must retain newly recorded demand."""
import pytest

from dashboard_support import dashboard_fixture
from favorites_recent_support import storage


@pytest.mark.asyncio
@pytest.mark.integration
async def test_observed_cleanup_does_not_delete_a_newer_search(storage):
    repository,_,db=storage
    await repository.track_zero_result(7,'Missing movie')
    snapshot=(await repository.top_zero_results())[0]
    await repository.track_zero_result(8,'Missing movie')
    assert not await repository.resolve_zero_result('Missing movie',observed=snapshot)
    current=await db.search_analytics.find_one({'_id':'missing movie'})
    assert current['count']==2
    assert await repository.resolve_zero_result('Missing movie',observed=current)
    assert await db.search_analytics.count_documents({})==0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_legacy_snapshot_missing_counters_cannot_delete_newly_initialized_fields(storage):
    repository,_,db=storage
    await db.search_analytics.insert_one({'_id':'missing','query':'Missing'})
    snapshot=(await repository.top_zero_results())[0]
    await repository.track_zero_result(7,'Missing')
    assert not await repository.resolve_zero_result('Missing',observed=snapshot)
    assert (await db.search_analytics.find_one({'_id':'missing'}))['count']==1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reconciliation_cannot_erase_demand_arriving_during_match_validation(storage):
    repository,_,db=storage
    await repository.track_zero_result(7,'Movie')
    rows=await repository.top_zero_results()
    service,_,media,_=dashboard_fixture(rows)
    service.repository=repository
    async def checker(*args,**kwargs):
        await repository.track_zero_result(8,'Movie')
        return True
    media.has_matching_file.side_effect=checker
    await service._reconcile_zero_results(rows,limit=10)
    assert (await db.search_analytics.find_one({'_id':'movie'}))['count']==2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_case_and_whitespace_counts_are_global_without_persisted_user_identity(storage):
    repository,_,db=storage
    for user,query in [(7,'Missing movie'),(8,' missing   MOVIE ')]:
        await repository.track_zero_result(user,query)
    rows=await repository.top_zero_results()
    assert len(rows)==1 and rows[0]['count']==2 and rows[0]['_id']=='missing movie'
    assert 'user_id' not in rows[0]
    assert await repository.resolve_zero_result(' MISSING movie ')
    assert await db.search_analytics.count_documents({})==0
