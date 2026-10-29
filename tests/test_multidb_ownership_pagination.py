"""PH-025/026 isolated multi-DB ownership and bounded pagination tests.

All DB writes are limited to disposable localhost MongoDB names. Production
still uses one database and multi-DB is not enabled by these tests.
"""
import asyncio
import os
from datetime import datetime
from uuid import uuid4

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from core.database.multi_pool import DatabaseInfo, MultiDatabaseManager
from scripts.profile_media_search import is_local


class Pool:
    def __init__(self, database):
        self.db = database

    async def get_collection(self, name):
        return self.db[name]

    async def execute_with_retry(self, fn, *args, **kwargs):
        return await fn(*args, **kwargs)


def multi_manager(*databases):
    # Avoid affecting the production module singleton or its global pools.
    manager = object.__new__(MultiDatabaseManager)
    manager.__init__()
    manager.databases = [
        DatabaseInfo(uri="localhost", name=f"fixture_{i}", pool=Pool(db))
        for i, db in enumerate(databases)
    ]
    return manager


@pytest.fixture
def local_mongo_uri():
    uri = os.environ.get("TEST_MONGO_URI")
    if not uri:
        pytest.skip("Disposable MongoDB CI service required")
    assert is_local(uri), "Never run integration writes against remote MongoDB"
    return uri


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ph025_one_owner_one_write_and_duplicate_owners_fail_closed(local_mongo_uri):
    name = "ph025_" + uuid4().hex
    client = AsyncIOMotorClient(local_mongo_uri, serverSelectionTimeoutMS=5000)
    a, b = client[name + "a"].FILES, client[name + "b"].FILES
    manager = multi_manager(client[name + "a"], client[name + "b"])
    try:
        await a.insert_many([{"_id": "only-a", "state": 1},
                             {"_id": "duplicate", "state": 1}])
        await b.insert_many([{"_id": "only-b", "state": 1},
                             {"_id": "duplicate", "state": 1}])

        assert await manager.update_one_across_databases(
            "FILES", {"_id": "only-b"}, {"$set": {"state": 2}}
        )
        assert (await b.find_one({"_id": "only-b"}))["state"] == 2
        assert await a.find_one({"_id": "only-b"}) is None
        # A matched no-op is still a successful update.
        assert await manager.update_one_across_databases(
            "FILES", {"_id": "only-b"}, {"$set": {"state": 2}}
        )
        assert await manager.update_one_across_databases(
            "FILES", {"_id": "only-a"}, {"$set": {"state": 3}},
            upsert=True
        )
        assert (await a.find_one({"_id": "only-a"}))["state"] == 3

        with pytest.raises(RuntimeError, match="Ambiguous"):
            await manager.update_one_across_databases(
                "FILES", {"_id": "duplicate"}, {"$set": {"state": 4}}
            )
        assert (await a.find_one({"_id": "duplicate"}))["state"] == 1
        assert (await b.find_one({"_id": "duplicate"}))["state"] == 1

        assert not await manager.update_one_across_databases(
            "FILES", {"_id": "missing"}, {"$set": {"state": 4}}
        )
        with pytest.raises(RuntimeError, match="PH-028"):
            await manager.update_one_across_databases(
                "FILES", {"_id": "missing"}, {"$set": {"state": 4}},
                upsert=True
            )
        assert await a.find_one({"_id": "missing"}) is None
        assert await b.find_one({"_id": "missing"}) is None

        manager.databases[1].is_active = False
        with pytest.raises(RuntimeError, match="unavailable"):
            await manager.update_one_across_databases(
                "FILES", {"_id": "only-a"}, {"$set": {"state": 5}}
            )
        assert (await a.find_one({"_id": "only-a"}))["state"] == 3
    finally:
        await client.drop_database(name + "a")
        await client.drop_database(name + "b")
        client.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ph025_single_database_upsert_preserves_legacy_behavior(local_mongo_uri):
    name = "ph025single_" + uuid4().hex
    client = AsyncIOMotorClient(local_mongo_uri, serverSelectionTimeoutMS=5000)
    manager = multi_manager(client[name])
    try:
        assert await manager.update_one_across_databases(
            "FILES", {"_id": "new"}, {"$set": {"state": "created"}}, upsert=True
        )
        assert (await client[name].FILES.find_one({"_id": "new"}))["state"] == "created"
        assert await manager.update_one_across_databases(
            "FILES", {"_id": "new"}, {"$set": {"state": "created"}}
        )
        assert await client[name].FILES.count_documents({}) == 1
    finally:
        await client.drop_database(name)
        client.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ph026_deep_pages_are_stable_bounded_and_nonoverlapping(local_mongo_uri):
    name = "ph026_" + uuid4().hex
    client = AsyncIOMotorClient(local_mongo_uri, serverSelectionTimeoutMS=5000)
    dbs = [client[f"{name}{i}"] for i in range(3)]
    manager = multi_manager(*dbs)
    records = []
    try:
        for i, database in enumerate(dbs):
            batch = []
            for j in range(1250):
                # Repeated timestamps exercise stable _id tie breaking.
                date = datetime(2026, 10, 29, 10, (j // 25) % 60).isoformat()
                item = {"_id": f"{i}-{j:05d}", "indexed_at": date, "tag": i}
                batch.append(item)
                records.append(item)
            await database.FILES.insert_many(batch)

        expected = sorted(
            records,
            key=lambda d: (d["indexed_at"], d["_id"]),
            reverse=True
        )
        sort = [("indexed_at", -1)]  # _id must be appended automatically
        pages = []
        for offset, size in [(0, 50), (50, 50), (1050, 150), (3200, 100)]:
            result = await manager.search_across_all_databases(
                "FILES", {}, limit=size, skip=offset, sort=sort
            )
            assert [x["_id"] for x in result] == [
                x["_id"] for x in expected[offset:offset + size]
            ]
            assert len({x["_id"] for x in result}) == len(result)
            pages.append(result)
        assert not ({x["_id"] for x in pages[0]} & {x["_id"] for x in pages[1]})
        again = await manager.search_across_all_databases(
            "FILES", {}, limit=150, skip=1050, sort=sort
        )
        assert [x["_id"] for x in again] == [x["_id"] for x in pages[2]]

        assert await manager.search_across_all_databases(
            "FILES", {}, limit=0, skip=500, sort=sort
        ) == []
        for invalid in ({"limit": -1}, {"skip": -1}, {"skip": 1.3}):
            with pytest.raises(ValueError):
                await manager.search_across_all_databases(
                    "FILES", {}, sort=sort, **invalid
                )

        # Search did not change any original collection or create an index.
        for database in dbs:
            assert await database.FILES.count_documents({}) == 1250
            assert sorted(await database.FILES.index_information()) == ["_id_"]
    finally:
        for i in range(3):
            await client.drop_database(f"{name}{i}")
        client.close()


@pytest.mark.asyncio
async def test_ph026_allows_only_bounded_cursor_pages_and_closes_on_failure():
    class Cursor:
        def __init__(self, docs, fail=False):
            self.docs = docs
            self.fail = fail
            self.requests = []
            self.closed = False
            self.pos = 0

        def sort(self, fields):
            self.docs = sorted(
                self.docs, key=lambda d: (d["indexed_at"], d["_id"]),
                reverse=True
            )
            return self

        def batch_size(self, size):
            assert size <= 64
            return self

        async def to_list(self, *, length):
            assert length <= 64 and length is not None
            self.requests.append(length)
            if self.fail:
                raise RuntimeError("simulated DB failure")
            data = self.docs[self.pos:self.pos + length]
            self.pos += len(data)
            return data

        async def close(self):
            self.closed = True

    class Collection:
        def __init__(self, cursor):
            self.cursor = cursor
        def find(self, query):
            return self.cursor

    class TestPool:
        def __init__(self, cursor):
            self.collection = Collection(cursor)
        async def get_collection(self, name):
            return self.collection

    first = Cursor([{"_id": f"A{i:05}", "indexed_at": "2026-10-29"} for i in range(400)])
    second = Cursor([{"_id": f"B{i:05}", "indexed_at": "2026-10-29"} for i in range(400)])
    manager = object.__new__(MultiDatabaseManager)
    manager.__init__()
    manager.databases = [
        DatabaseInfo(uri="local", name="A", pool=TestPool(first)),
        DatabaseInfo(uri="local", name="B", pool=TestPool(second)),
    ]
    result = await manager.search_across_all_databases(
        "FILES", {}, skip=510, limit=20, sort=[("indexed_at", -1)]
    )
    assert len(result) == 20
    assert first.closed and second.closed
    assert first.requests and second.requests
    assert max(first.requests + second.requests) <= 64

    broken = Cursor([{"_id": "X", "indexed_at": "2026-10-29"}], fail=True)
    other = Cursor([{"_id": "Y", "indexed_at": "2026-10-29"}])
    manager.databases = [
        DatabaseInfo(uri="local", name="broken", pool=TestPool(broken)),
        DatabaseInfo(uri="local", name="healthy", pool=TestPool(other)),
    ]
    with pytest.raises(RuntimeError, match="simulated DB failure"):
        await manager.search_across_all_databases(
            "FILES", {}, skip=0, limit=3, sort=[("indexed_at", -1)]
        )
    assert broken.closed and other.closed
    manager.databases[0].is_active = False
    with pytest.raises(RuntimeError, match="unavailable"):
        await manager.search_across_all_databases("FILES", {}, limit=1)
