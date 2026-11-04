from datetime import UTC, datetime, timedelta
import pytest
from favorites_recent_support import storage

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_recent_pruning_keeps_a_concurrently_refreshed_entry(storage):
    repository,pool,db = storage
    base = datetime.now(UTC)-timedelta(days=1)
    await db.recent_files.insert_many([{'_id':f'42:old-{i}','user_id':42,
        'file_unique_id':f'old-{i}','last_accessed_at':base+timedelta(seconds=i)}
        for i in range(51)]+[{'_id':'99:other','user_id':99,'file_unique_id':'other','last_accessed_at':base}])
    async def refresh():
        await db.recent_files.update_one({'_id':'42:old-0'},
            {'$set':{'last_accessed_at':datetime.now(UTC)+timedelta(hours=1)}})
    pool.before_delete = refresh
    await repository.record_recent_file(42,'new')
    assert await db.recent_files.find_one({'_id':'42:old-0'}) is not None
    await repository.record_recent_file(42,'next')
    assert await db.recent_files.count_documents({'user_id':42})==50
    assert (await repository.get_recent_files(42))[0]=='old-0'
    assert await db.recent_files.count_documents({'user_id':99})==1


@pytest.mark.asyncio
async def test_recent_repeated_delivery_deduplicates_and_removal_is_owner_scoped(storage):
    repository,_,db = storage
    await repository.record_recent_file(42,'same')
    await repository.record_recent_file(42,'same')
    await repository.record_recent_file(99,'same')
    assert await db.recent_files.count_documents({'user_id':42})==1
    assert not await repository.remove_recent_file(42,'missing')
    assert await repository.remove_recent_file(42,'same')
    assert await repository.get_recent_files(99)==['same']
    assert await repository.clear_recent_files(42)==0
    assert await repository.clear_recent_files(99)==1
