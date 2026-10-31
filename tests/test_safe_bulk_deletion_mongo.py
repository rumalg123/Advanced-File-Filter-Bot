"""PH-007: real bounded delete integration test, always local disposable MongoDB."""
import os
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from core.services.bulk_media_deletion import MediaBulkDeletion
from core.services.bulk_delete_policy import BulkDeleteRejected
from core.utils.search_matcher import build_media_search_filter
from scripts.profile_media_search import is_local

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_real_mongodb_batches_delete_only_confirmed_matching_documents():
    uri = os.environ.get("TEST_MONGO_URI")
    if not uri:
        pytest.skip("Requires ephemeral local MongoDB service")
    assert is_local(uri), "Refuse non-local MongoDB during destructive tests"

    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
    name = f"ph007_ci_{uuid4().hex}"
    db = client[name]
    col = db.media_files
    try:
        await col.insert_many([
            {"_id": f"doctor-{i:04d}", "file_unique_id": f"doctor-uid-{i}",
             "file_ref": f"doctor-ref-{i}",
             "file_name": f"Doctor X Mafia S01E{i:03d} 540p",
             "file_type": "video"}
            for i in range(215)
        ] + [
            {"_id": f"other-{i}", "file_unique_id": f"other-{i}",
             "file_name": f"Unrelated series {i}", "file_type": "video"}
            for i in range(3)
        ])

        class Pool:
            async def execute_with_retry(self, operation, *args, **kwargs):
                return await operation(*args, **kwargs)

        invalidator = SimpleNamespace(
            invalidate_file_cache=AsyncMock(return_value=True),
            invalidate_all_search_results=AsyncMock(return_value=True),
        )
        media = SimpleNamespace(
            is_multi_db=False,
            collection=AsyncMock(return_value=col),
            db_pool=Pool(),
            cache_invalidator=invalidator,
            _build_search_filter=lambda query, *args:
                build_media_search_filter(query, *args),
        )
        service = MediaBulkDeletion(media)
        preview = await service.preview("doctor x mafia")
        assert preview.count == 215
        assert len(preview.sample) == 5
        assert await col.count_documents({}) == 218

        with pytest.raises(BulkDeleteRejected):
            await service.execute("doctor x mafia", expected_count=216)
        assert await col.count_documents({}) == 218

        removed = await service.execute("doctor x mafia", expected_count=215)
        assert removed == 215
        assert await col.count_documents({}) == 3
        assert await col.count_documents({"file_name": {"$regex": "^Unrelated"}}) == 3
        assert invalidator.invalidate_all_search_results.await_count == 3
        assert invalidator.invalidate_file_cache.await_count == 215
        assert (await service.preview("doctor x mafia")).count == 0
    finally:
        # Only drops the random, localhost-only CI database created above.
        await client.drop_database(name)
        client.close()
