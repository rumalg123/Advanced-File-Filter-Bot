"""Real MongoDB integration coverage for channel indexing jobs.

CI sets TEST_MONGO_URI to local MongoDB service. Never accepts a remote host.
"""
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from repositories.channel_index_jobs import ChannelIndexJobRepository

pytestmark = pytest.mark.integration


def localhost_uri():
    uri = os.getenv("TEST_MONGO_URI", "")
    if not uri:
        pytest.skip("No ephemeral MongoDB integration service")
    host = urlsplit(uri).hostname
    if host not in ("localhost", "127.0.0.1"):
        pytest.fail("PH-005 integration test refuses non-local MongoDB")
    return uri


@pytest.mark.asyncio
async def test_real_mongodb_lease_recovery_dead_letters_and_ttl_index():
    client = AsyncIOMotorClient(localhost_uri(), serverSelectionTimeoutMS=5000)
    database_name = f"ph005_ci_{uuid4().hex}"
    db = client[database_name]
    collection = db.channel_index_jobs
    pool = SimpleNamespace(get_collection=AsyncMock(return_value=collection))
    queue = ChannelIndexJobRepository(pool, lease_seconds=30)
    try:
        await client.admin.command("ping")
        await queue.ensure_indexes()

        indexes = await collection.index_information()
        assert {"channel_job_pending", "channel_job_reclaim",
                "channel_job_done_retention"}.issubset(indexes)
        assert indexes["channel_job_done_retention"]["expireAfterSeconds"] == 2592000

        snapshot = {
            "_id": "test-telegram-file-id",
            "file_unique_id": "test-unique-file-id",
            "file_name": "Doctor X Mafia In White S01E03 540p",
            "file_type": "video",
        }
        assert await queue.enqueue(-100123, 321, snapshot)
        assert not await queue.enqueue(-100123, 321, snapshot)
        assert await collection.count_documents({"_id": "-100123:321"}) == 1

        leased = await queue.claim()
        assert leased["_id"] == "-100123:321"
        assert leased["attempts"] == 1
        assert await queue.claim() is None

        # Simulate a crashed worker by making its lease expire.
        await collection.update_one(
            {"_id": leased["_id"]},
            {"$set": {"lease_until": datetime.now(UTC) - timedelta(seconds=5)}},
        )
        reclaimed = await queue.claim()
        assert reclaimed["attempts"] == 2
        assert reclaimed["lease_token"] != leased["lease_token"]
        assert not await queue.acknowledge(leased)
        assert await queue.acknowledge(reclaimed)
        assert (await collection.find_one({"_id": reclaimed["_id"]}))["status"] == "done"

        # Retry an entirely separate job until it becomes a dead letter.
        assert await queue.enqueue(-100123, 322, snapshot)
        for attempt in range(queue.MAX_ATTEMPTS):
            job = await queue.claim()
            assert job and job["_id"] == "-100123:322"
            state = await queue.fail(job, "deliberately injected indexing failure")
            if attempt + 1 < queue.MAX_ATTEMPTS:
                assert state == "pending"
                await collection.update_one(
                    {"_id": job["_id"]},
                    {"$set": {
                        "next_attempt_at": datetime.now(UTC) - timedelta(seconds=5)
                    }},
                )
            else:
                assert state == "dead"

        assert (await queue.counts())["dead"] == 1
        assert await queue.retry_dead("-100123:322")
        assert (await queue.counts())["pending"] == 1

    finally:
        # Only the isolated, localhost-only, randomly named CI database.
        await client.drop_database(database_name)
        client.close()
