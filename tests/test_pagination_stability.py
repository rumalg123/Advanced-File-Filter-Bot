"""PH-014: stable single-DB paging and bounded, read-only deep-offset EXPLAIN."""
import json
import os
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pymongo import MongoClient

from core.cache.config import CacheKeyGenerator
from repositories.media import MediaRepository, SINGLE_DB_SEARCH_SORT
from scripts.profile_media_search import is_local, profile


class Cache:
    def __init__(self):
        self.data = {}
        self.generation = 12

    async def ensure_search_generation(self, key, initial):
        return self.generation

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, expire=None):
        self.data[key] = value
        return True

    async def delete(self, key):
        self.data.pop(key, None)
        return True


@pytest.mark.asyncio
async def test_existing_offset_contract_uses_unique_tiebreaker_and_new_cache_namespace():
    cache = Cache()
    repo = MediaRepository(None, cache)
    repo.count = AsyncMock(return_value=25)
    repo.find_many = AsyncMock(return_value=[])

    files, next_offset, total = await repo.search_files("doctor x", offset=0, limit=10)
    assert (files, next_offset, total) == ([], 10, 25)
    kwargs = repo.find_many.await_args.kwargs
    assert kwargs["sort"] == [("indexed_at", -1), ("_id", -1)]
    assert kwargs["skip"] == 0
    assert kwargs["limit"] == 10
    assert kwargs["raise_on_error"] is True

    # Cached legacy (indexed_at-only) pages must not be reused.
    old_key = CacheKeyGenerator.search_results_versioned(
        "doctor x", None, 0, 10, True, cache.generation
    )
    assert old_key not in cache.data

    files, next_offset, total = await repo.search_files("doctor x", offset=20, limit=10)
    assert (files, next_offset, total) == ([], 0, 25)
    assert repo.find_many.await_args.kwargs["skip"] == 20
    assert repo.find_many.await_count == 2

    # The exact same query/page is cached without extra MongoDB work.
    assert await repo.search_files("doctor x", offset=20, limit=10) == ([], 0, 25)
    assert repo.find_many.await_count == 2


def test_profiler_rejects_unbounded_or_malformed_offsets_before_database_access():
    for offsets in ((), (-1,), (1_000_001,), (0, 1, 2, 3, 4, 5, 6), (True,)):
        with pytest.raises(ValueError, match="Offsets"):
            profile(None, ("doctor x",), offsets=offsets)

    with pytest.raises(ValueError, match="Too many"):
        profile(None, ("doctor x", "another", "third"), offsets=(0, 1, 2, 3, 4, 5),
                compare_legacy_sort=True)


@pytest.mark.integration
def test_real_mongo_tied_timestamps_have_repeatable_nonoverlapping_pages_and_safe_explain():
    uri = os.environ.get("TEST_MONGO_URI")
    if not uri:
        pytest.skip("Requires isolated CI MongoDB")
    assert is_local(uri), "Never use a production MongoDB for write tests"
    database_name = f"ph014_ci_{uuid4().hex}"

    with MongoClient(uri, serverSelectionTimeoutMS=5000) as client:
        db = client[database_name]
        collection = db.media_files
        try:
            collection.insert_many([
                {
                    "_id": f"file-{i:04d}",
                    "file_name": f"Doctor X Mafia Episode {i} 540p",
                    "file_type": "video",
                    "indexed_at": "2026-10-28T00:00:00+00:00",
                }
                for i in range(25)
            ])
            collection.create_index([("indexed_at", -1)], name="date_index")
            before_count = collection.count_documents({})
            before_indexes = sorted(collection.index_information())

            def pages():
                return [
                    [doc["_id"] for doc in collection.find(
                        {}, {"_id": 1}
                    ).sort(SINGLE_DB_SEARCH_SORT).skip(n).limit(10)]
                    for n in (0, 10, 20)
                ]

            actual = pages()
            assert pages() == actual
            flattened = [item for page in actual for item in page]
            assert len(flattened) == len(set(flattened)) == 25
            assert flattened == sorted(flattened, reverse=True)

            report = profile(
                db, ("doctor x mafia",), limit=10, offsets=(0, 10, 20),
                compare_legacy_sort=True, include_counts=True, max_time_ms=5000,
            )
            assert report["offsets"] == [0, 10, 20]
            assert report["sort"] == {"indexed_at": -1, "_id": -1}
            assert [p["offset"] for p in report["queries"][0]["pages"]] == [0, 10, 20]
            assert [p["nReturned"] for p in report["queries"][0]["pages"]] == [10, 10, 5]
            assert len(report["queries"][0]["legacy_pages"]) == 3
            assert "count" in report["queries"][0]
            assert "Doctor X Mafia" not in json.dumps(report)
            assert collection.count_documents({}) == before_count
            assert sorted(collection.index_information()) == before_indexes
        finally:
            client.drop_database(database_name)
