"""PH-027/028: no partial results, read-only global identity audit and write gate.

Integration test writes ONLY to disposable localhost databases, never to
production Atlas. Separate independent MongoDBs are emulated by two database
names on the local disposable CI MongoDB service.
"""
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from core.database.multi_pool import (
    DatabaseInfo, MultiDatabaseManager, MultiDatabaseReadError,
)
from repositories.media import MediaRepository
from scripts.profile_media_search import is_local


class Pool:
    def __init__(self, db, fail=False):
        self.db = db
        self.fail = fail

    async def get_collection(self, name):
        if self.fail:
            raise ConnectionError("simulated unavailable DB: secret://credentials")
        return self.db[name]

    async def execute_with_retry(self, func, *args, **kwargs):
        if self.fail:
            raise ConnectionError("simulated database timeout")
        return await func(*args, **kwargs)


def manager_for(*pools):
    # Do not mutate the global module-level singleton's state.
    manager = object.__new__(MultiDatabaseManager)
    manager.__init__()
    manager.databases = [
        DatabaseInfo(uri="localhost", name=f"shard-{i}", pool=pool)
        for i, pool in enumerate(pools)
    ]
    return manager


@pytest.fixture
def disposable_mongo_uri():
    uri = os.environ.get("TEST_MONGO_URI")
    if not uri:
        pytest.skip("Requires disposable CI MongoDB")
    assert is_local(uri), "Never write test documents to remote MongoDB"
    return uri


@pytest.mark.integration
@pytest.mark.asyncio
async def test_partial_count_find_search_and_aggregate_never_return_false_empty(disposable_mongo_uri):
    name = "ph027_" + uuid4().hex
    client = AsyncIOMotorClient(disposable_mongo_uri, serverSelectionTimeoutMS=5000)
    db_a, db_b = client[name+"a"], client[name+"b"]
    manager = manager_for(Pool(db_a), Pool(db_b))
    try:
        await db_a.FILES.insert_one({"_id": "a", "indexed_at": "2026-10-29", "file_unique_id": "a"})
        await db_b.FILES.insert_one({"_id": "b", "indexed_at": "2026-10-29", "file_unique_id": "b"})
        assert await manager.count_across_all_databases("FILES", {}) == 2
        assert len(await manager.find_many_in_all_databases("FILES", {})) == 2
        assert (await manager.find_file_in_all_databases("FILES", {"_id": "b"}))[1] == 1
        assert len(await manager.aggregate_across_all_databases("FILES", [{"$match": {}}])) == 2
        assert len(await manager.search_across_all_databases("FILES", {}, limit=10)) == 2

        # Simulate a failure after another source has successfully returned
        # data. None of these APIs may report zero, partial or "not found".
        manager.databases[1].pool = Pool(db_b, fail=True)
        for coro in (
            manager.count_across_all_databases("FILES", {}),
            manager.find_many_in_all_databases("FILES", {}),
            manager.find_file_in_all_databases("FILES", {"_id": "a"}),
            manager.aggregate_across_all_databases("FILES", [{"$match": {}}]),
            manager.search_across_all_databases("FILES", {}, limit=5),
            manager.get_collection_from_all("FILES"),
        ):
            with pytest.raises((MultiDatabaseReadError, ConnectionError, RuntimeError)):
                await coro
        # The source is still configured, but unavailable; never suppress it.
        manager.databases[1].is_active = False
        with pytest.raises(MultiDatabaseReadError, match="unavailable"):
            await manager.count_across_all_databases("FILES", {})
        with pytest.raises(MultiDatabaseReadError, match="unavailable"):
            await manager.get_all_databases()
    finally:
        await client.drop_database(name+"a")
        await client.drop_database(name+"b")
        client.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_duplicate_identity_lookup_fails_closed_and_audit_only_reads(disposable_mongo_uri):
    name = "ph028_" + uuid4().hex
    client = AsyncIOMotorClient(disposable_mongo_uri, serverSelectionTimeoutMS=5000)
    a, b = client[name+"a"], client[name+"b"]
    manager = manager_for(Pool(a), Pool(b))
    try:
        await a.FILES.insert_many([
            {"_id": "id-1", "file_unique_id": "shared-unique", "file_ref": "ref-a"},
            {"_id": "duplicate-id", "file_unique_id": "left", "file_ref": "shared-ref"},
        ])
        await b.FILES.insert_many([
            {"_id": "id-2", "file_unique_id": "shared-unique", "file_ref": "ref-b"},
            {"_id": "duplicate-id", "file_unique_id": "right", "file_ref": "shared-ref"},
        ])
        with pytest.raises(MultiDatabaseReadError, match="duplicate_owner"):
            await manager.find_file_in_all_databases(
                "FILES", {"file_unique_id": "shared-unique"}
            )
        report = await manager.audit_media_identity_uniqueness("FILES")
        assert report["complete"] is True
        assert report["databases_checked"] == 2
        assert report["cross_database_duplicates"] == {
            "_id": 1, "file_unique_id": 1, "file_ref": 1
        }
        assert not report["global_uniqueness_proven"]
        # No raw media identities are sent in aggregate output.
        assert "shared-unique" not in repr(report)
        assert "duplicate-id" not in repr(report)
        with pytest.raises(MultiDatabaseReadError, match="identity_audit"):
            await manager.audit_media_identity_uniqueness("FILES", max_docs_per_db=1)
        for db in (a, b):
            assert await db.FILES.count_documents({}) == 2
            assert sorted(await db.FILES.index_information()) == ["_id_"]
    finally:
        await client.drop_database(name+"a")
        await client.drop_database(name+"b")
        client.close()


@pytest.mark.asyncio
async def test_media_creation_is_blocked_before_database_write_in_multi_mode():
    manager = manager_for(SimpleNamespace(), SimpleNamespace())
    repo = object.__new__(MediaRepository)
    repo.is_multi_db = True
    repo.multi_db_manager = manager
    repo.find_file = AsyncMock(return_value=None)
    data = SimpleNamespace(file_unique_id="same", file_name="File")
    assert await repo.save_media(data) == (False, 2, None)
    repo.find_file.assert_awaited_once_with("same")
    # This must not request a write pool or execute any insert.
    manager.get_optimal_write_database = AsyncMock(
        side_effect=AssertionError("Should not select DB for an insert")
    )
    assert await repo.save_media(data) == (False, 2, None)
    manager.get_optimal_write_database.assert_not_awaited()


@pytest.mark.asyncio
async def test_identity_audit_rejects_invalid_caps_and_missing_source():
    manager = manager_for(SimpleNamespace(), SimpleNamespace())
    for cap in (0, -1, 100001, True, None, "100"):
        with pytest.raises(ValueError):
            await manager.audit_media_identity_uniqueness("FILES", max_docs_per_db=cap)
    manager.databases[1].is_active = False
    with pytest.raises(MultiDatabaseReadError, match="unavailable"):
        await manager.audit_media_identity_uniqueness("FILES", max_docs_per_db=5)
