"""PH-012: disposable local MongoDB and Redis recovery fixtures.

These tests prove copy/replay semantics and TTL recovery on CI services.
They do NOT claim that a real Atlas cloud snapshot or Redis RDB/AOF file
has been restored. They NEVER contact production or flush a Redis database.
"""
import os
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from bson import BSON
from motor.motor_asyncio import AsyncIOMotorClient
from redis.asyncio import Redis


pytestmark = pytest.mark.integration


def _local_target(uri: str, expected_port: int, *, kind: str):
    parsed = urlsplit(uri)
    assert parsed.scheme == kind
    assert (parsed.hostname or "").lower() in ("127.0.0.1", "localhost")
    assert parsed.port == expected_port
    assert not parsed.username and not parsed.password


@pytest.mark.asyncio
async def test_disposable_mongo_fixture_copy_recovers_documents_and_index():
    uri = os.getenv("TEST_MONGO_URI")
    if not uri:
        pytest.skip("Local CI MongoDB service not available")
    _local_target(uri, 27017, kind="mongodb")
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
    prefix = f"ph012_ci_{uuid4().hex}"
    source_db, recovered_db = f"{prefix}_source", f"{prefix}_recovery"
    assert source_db.startswith("ph012_ci_")
    assert recovered_db.startswith("ph012_ci_")
    try:
        originals = [
            {
                "_id": f"media-{i:03d}",
                "file_unique_id": f"ph012-u-{i:03d}",
                "file_id": f"testtelegram-{i:03d}",
                "file_name": f"Doctor X Test S01E{i:02d}.mkv",
                "season": "01",
                "episode": f"{i:02d}",
            }
            for i in range(12)
        ]
        assert await client[source_db].list_collection_names() == []
        assert await client[recovered_db].list_collection_names() == []
        src = client[source_db]["media_files"]
        dest = client[recovered_db]["media_files"]
        await src.insert_many(originals)
        await src.create_index("file_unique_id", unique=True)
        # Roundtrip each BSON document to demonstrate type fidelity in a
        # logical fixture. Actual Atlas/mongodump backup remains a manual gate.
        snapshot = [
            BSON.encode(d)
            async for d in src.find({}).sort("_id", 1)
        ]
        await dest.insert_many([BSON(b).decode() for b in snapshot])
        await dest.create_index("file_unique_id", unique=True)
        restored = [d async for d in dest.find({}).sort("_id", 1)]
        assert len(restored) == len(originals) == 12
        assert [BSON.encode(d) for d in restored] == snapshot
        assert (await dest.count_documents({})) == (await src.count_documents({}))
        indexes = await dest.index_information()
        assert any(idx.get("unique") and
                   idx.get("key") == [("file_unique_id", 1)]
                   for idx in indexes.values())
    finally:
        # These two UUID-tagged databases were created by this test ONLY.
        await client.drop_database(source_db)
        await client.drop_database(recovered_db)
        client.close()


@pytest.mark.asyncio
async def test_disposable_redis_raw_dump_restore_preserves_session_and_ttl():
    uri = os.getenv("TEST_REDIS_STATE_URI")
    if not uri:
        pytest.skip("Local CI state Redis service not available")
    _local_target(uri, 6380, kind="redis")
    client = Redis.from_url(uri, socket_connect_timeout=5, socket_timeout=5)
    nonce = uuid4().hex
    old = f"session:ph012-ci-original:{nonce}"
    new = f"session:ph012-ci-recovered:{nonce}"
    try:
        payload = b"PH012-inert-session-fixture-no-secret"
        assert await client.set(old, payload, px=120_000)
        prior_ttl = await client.pttl(old)
        assert 0 < prior_ttl <= 120_000
        dumped = await client.dump(old)
        assert dumped is not None
        await client.restore(new, prior_ttl, dumped)
        assert await client.get(new) == await client.get(old)
        restored_ttl = await client.pttl(new)
        assert 0 < restored_ttl <= prior_ttl
        # No other sessions or keys are deleted.
        assert await client.exists(old) == 1
    finally:
        await client.delete(old, new)
        await client.aclose()
