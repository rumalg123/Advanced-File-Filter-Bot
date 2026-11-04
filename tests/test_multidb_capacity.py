"""Write-source choice must account for index growth as well as documents."""
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from core.database.multi_pool import DatabaseInfo, MultiDatabaseManager
from scripts.profile_media_search import is_local


class Pool:
    def __init__(self, database):
        self.database = database

    async def execute_with_retry(self, function, *args, **kwargs):
        return await function(*args, **kwargs)

    async def get_collection(self, name):
        return self.database[name]


def manager_for(pools):
    manager = object.__new__(MultiDatabaseManager)
    manager.__init__()
    manager.databases = [DatabaseInfo(uri='mongodb://localhost', name=f'qa{i}', pool=pool)
                         for i, pool in enumerate(pools)]
    return manager


def fake_pool(data_mib, index_mib):
    collection = SimpleNamespace(count_documents=AsyncMock(return_value=10))
    pool = Pool(SimpleNamespace(command=AsyncMock(return_value={
        'dataSize': data_mib * 1024**2, 'indexSize': index_mib * 1024**2,
        'storageSize': 9000 * 1024**2,
    })))
    pool.get_collection = AsyncMock(return_value=collection)
    return pool


@pytest.mark.asyncio
@pytest.mark.parametrize('data_mib,index_mib,switch', [
    (10, 0, False), (400, 200, True), (0, 600, True), (400, 112, True),
])
async def test_index_growth_and_exact_limit_select_the_available_write_source(data_mib, index_mib, switch):
    pools = [fake_pool(data_mib, index_mib), fake_pool(1, 1)]
    manager = manager_for(pools)
    manager.size_limit_gb = 0.5
    chosen = await manager.get_write_database()
    assert chosen is pools[int(switch)]
    assert manager.current_write_db_index == int(switch)
    assert manager.databases[0].size_gb == (data_mib + index_mib) / 1024
    assert manager.databases[0].files_count == 10


@pytest.mark.asyncio
async def test_real_mongo_index_footprint_can_trigger_switch_before_document_limit():
    uri = os.getenv('TEST_MONGO_URI')
    if not uri:
        pytest.skip('Requires disposable MongoDB')
    assert is_local(uri)
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=3000)
    names = ['qa_capacity_' + uuid4().hex for _ in range(2)]
    try:
        collection = client[names[0]].media_files
        await collection.insert_many([{'_id': str(i), 'title': str(i) + 'x' * 300} for i in range(200)])
        await collection.create_index('title')
        stats = await client[names[0]].command('dbStats')
        assert stats['indexSize'] > 0
        manager = manager_for([Pool(client[name]) for name in names])
        # Documents fit, but their required indexes put this source over its
        # configured budget. Physical allocation is not the logical quota.
        manager.size_limit_gb = (stats['dataSize'] + stats['indexSize'] / 2) / 1024**3
        chosen = await manager.get_write_database()
        assert chosen is manager.databases[1].pool
        assert manager.databases[0].files_count == 200
    finally:
        for name in names:
            await client.drop_database(name)
        client.close()
