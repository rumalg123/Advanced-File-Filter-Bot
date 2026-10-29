"""Legacy operator migration uses only bounded disposable MongoDB fixtures."""
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from migrate_media_metadata import MediaMetadataMigration
from scripts.profile_media_search import is_local


class Pool:
    def __init__(self, db): self.database=db
    async def get_collection(self, name):return self.database[name]
    async def execute_with_retry(self, fn, *args, **kwargs):return await fn(*args, **kwargs)


@pytest_asyncio.fixture
async def pools():
    uri=os.getenv('TEST_MONGO_URI')
    if not uri:pytest.skip('Requires disposable local MongoDB')
    assert is_local(uri)
    client=AsyncIOMotorClient(uri,serverSelectionTimeoutMS=3000)
    names=['qa_migration_'+uuid4().hex for _ in range(2)]
    try:yield [Pool(client[name]) for name in names]
    finally:
        for name in names:await client.drop_database(name)
        client.close()


@pytest.mark.parametrize('size',[0,-1,True,1.5,1001])
def test_migration_rejects_unsafe_batch_bounds(size):
    with pytest.raises(ValueError):MediaMetadataMigration(None,batch_size=size)


@pytest.mark.asyncio
@pytest.mark.parametrize('limit',[0,-1,True,1.5,1000001])
async def test_migration_rejects_invalid_global_limit(limit):
    with pytest.raises(ValueError):await MediaMetadataMigration([]).run(limit=limit)


@pytest.mark.asyncio
async def test_real_mongo_dry_run_apply_preservation_and_global_limit(pools):
    for pool in pools:
        await pool.database.media_files.insert_many([
            {'_id':'one','file_name':'QA Show S01E03 1080p.mkv','caption':'<b>Title</b>'},
            {'_id':'two','file_name':'Unspecified file','caption':None},
            {'_id':'three','file_name':'QA Show S02E01 720p','season':'09','episode':'08','resolution':'540p'},
        ])
    migration=MediaMetadataMigration(pools,batch_size=2)
    await migration.run(dry_run=True,limit=4)
    assert migration.stats['processed']==4 and migration.stats['updated']==2
    assert (await pools[0].database.media_files.find_one({'_id':'one'})).get('season') is None
    migration=MediaMetadataMigration(pools,batch_size=2)
    await migration.run(limit=4)
    assert migration.stats['processed']==4 and migration.stats['updated']==2
    changed=await pools[0].database.media_files.find_one({'_id':'one'})
    assert changed['season']=='01' and changed['episode']=='03' and changed['resolution']=='1080p'
    assert datetime.fromisoformat(changed['updated_at']).utcoffset()==timedelta(0)
    assert (await pools[0].database.media_files.find_one({'_id':'three'}))['season']=='09'


@pytest.mark.asyncio
async def test_migration_skips_concurrent_text_edits_and_counts_actual_writes(pools):
    pool=pools[0];col=pool.database.media_files
    await col.insert_one({'_id':'one','file_name':'Old Show S01E03 1080p'})
    stale=await col.find_one({})
    await col.update_one({}, {'$set':{'file_name':'New Show S09E08 540p','season':'09'}})
    migration=MediaMetadataMigration(pool)
    assert await migration._process_batch(pool,col,[stale],False)==0
    current=await col.find_one({})
    assert current['season']=='09' and current.get('episode') is None


@pytest.mark.asyncio
async def test_migration_document_and_bulk_failure_accounting(pools):
    pool=pools[0];col=pool.database.media_files
    migration=MediaMetadataMigration(pool)
    invalid={'_id':'bad','file_name':None,'caption':object()}
    good={'_id':'good','file_name':'Show S01E01 540p'}
    assert await migration._process_batch(pool,col,[invalid],False)==0
    assert migration.stats['errors']==1
    broken=SimpleNamespace(bulk_write=AsyncMock(side_effect=ConnectionError('simulated write outage')))
    assert await migration._process_batch(pool,broken,[good],False)==0
    assert migration.stats['errors']==2
    pool.execute_with_retry=AsyncMock(side_effect=ConnectionError('read outage'))
    with pytest.raises(ConnectionError):await migration.run()
