"""PH-016 media index ownership, audit safety and MongoDB integration."""
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pymongo import MongoClient

from core.database.indexes import IndexOptimizer
from core.database.media_indexes import (
    compare_index_definition, index_definition, media_index_manifest,
)
from scripts.audit_media_indexes import audit_media_indexes
from scripts.profile_media_search import is_local


def test_manifest_is_unique_stable_and_defensively_copied():
    first = media_index_manifest()
    assert len(first) == 16
    assert len({spec["name"] for spec in first}) == len(first)
    assert first[0]["name"] == "text_search_idx"
    assert any(spec["name"] == "file_ref_index" and spec["options"]["unique"]
               for spec in first)
    first[0]["keys"].clear()
    first[1]["options"]["arbitrary"] = True
    second = media_index_manifest()
    assert second[0]["keys"] and "arbitrary" not in second[1]["options"]


def test_text_index_server_format_and_implicit_defaults_are_equivalent():
    manifest = media_index_manifest()
    text_spec = next(x for x in manifest if x["name"] == "text_search_idx")
    server = {
        "name": "text_search_idx",
        "key": {"_fts": "text", "_ftsx": 1},
        "weights": {"caption": 1, "file_name": 1},
        "default_language": "english",
        "language_override": "language",
    }
    assert compare_index_definition(text_spec, server)
    assert index_definition(server)["keys"] == [
        ["caption", "text"], ["file_name", "text"]
    ]
    assert not compare_index_definition(text_spec, {
        **server, "default_language": "spanish",
    })
    assert not compare_index_definition(text_spec, {
        **server, "weights": {"caption": 2, "file_name": 1},
    })


class Cursor:
    def __init__(self, items):
        self.items = items

    def __iter__(self):
        return iter(self.items)

    async def to_list(self, length=None):
        return list(self.items)


class AuditCollection:
    def __init__(self, docs):
        self.docs = docs
        self.index_usage = []
        self.list_calls = 0
        self.create_index = AsyncMock()
        self.drop_index = AsyncMock()

    def list_indexes(self, **kwargs):
        assert kwargs == {"maxTimeMS": 3000}
        self.list_calls += 1
        return Cursor(self.docs)

    def aggregate(self, pipeline, **kwargs):
        assert pipeline == [{"$indexStats": {}}]
        assert kwargs == {"maxTimeMS": 3000}
        return iter(self.index_usage)


def test_read_only_audit_detects_missing_drift_unmanaged_and_prefix_candidates():
    c = AuditCollection([
        {"name": "_id_", "key": {"_id": 1}},
        {"name": "date_index", "key": {"indexed_at": -1}},
        {"name": "unique_file_id_idx", "key": {"file_unique_id": 1}},
        {"name": "shadow_sort", "key": {"indexed_at": -1, "_id": -1}},
        {"name": "custom_sensitive", "key": {"user_id": 1},
         "partialFilterExpression": {"secret": "private-value"}},
    ])
    report = audit_media_indexes(c)
    status = {x["name"]: x["status"] for x in report["indexes"]}
    assert status["date_index"] == "matching"
    assert status["unique_file_id_idx"] == "definition_drift"
    assert status["episode_idx"] == "missing"
    assert {i["name"] for i in report["unmanaged_indexes"]} == {
        "shadow_sort", "custom_sensitive"
    }
    assert {"shorter": "date_index", "longer": "shadow_sort",
            "status": "requires_query_plan_and_option_review"} in report["prefix_candidates"]
    assert "private-value" not in str(report)
    assert c.create_index.await_count == c.drop_index.await_count == 0


def test_optional_index_usage_is_node_scoped_and_redacts_hostnames():
    from datetime import datetime, UTC
    c = AuditCollection([{"name": "_id_", "key": {"_id": 1}}])
    c.index_usage = [
        {"name": "_id_", "host": "secret-mongo-host",
         "accesses": {"ops": 2, "since": datetime(2026, 10, 28, tzinfo=UTC)}},
        {"name": "_id_", "host": "another-secret-host",
         "accesses": {"ops": 3, "since": datetime(2026, 10, 29, tzinfo=UTC)}},
    ]
    result = audit_media_indexes(c, include_usage=True)
    assert result["index_usage"]["_id_"]["access_ops"] == 5
    assert result["index_usage"]["_id_"]["sampled_nodes"] == 2
    assert "secret-mongo" not in str(result)


@pytest.mark.asyncio
async def test_optimizer_does_not_rebuild_matching_indexes_or_touch_mismatch():
    manifest = media_index_manifest()
    existing = [
        {"name": s["name"], "key": dict(s["keys"]), **s["options"]}
        for s in manifest
    ]
    # Break one unique constraint; this must be a flagged failure, not success.
    next(d for d in existing if d["name"] == "unique_file_id_idx").pop("unique")
    collection = SimpleNamespace(
        list_indexes=lambda: Cursor(existing),
        create_index=AsyncMock(),
        drop_index=AsyncMock(),
    )

    class Pool:
        async def get_collection(self, name):
            assert name == "media_files"
            return collection

        async def execute_with_retry(self, fn, *args, **kwargs):
            return await fn(*args, **kwargs)

    result = await IndexOptimizer(Pool()).create_media_indexes()
    assert len(result) == 16
    assert result["media_unique_file_id_idx"] is False
    assert all(ok for name, ok in result.items()
               if name != "media_unique_file_id_idx")
    collection.create_index.assert_not_awaited()
    collection.drop_index.assert_not_awaited()


@pytest.mark.asyncio
async def test_optimizer_creates_missing_legacy_index_once_without_drop():
    collection = SimpleNamespace(
        list_indexes=lambda: Cursor([{"name": "_id_", "key": {"_id": 1}}]),
        create_index=AsyncMock(return_value="created"),
        drop_index=AsyncMock(),
    )

    class Pool:
        async def get_collection(self, name):
            return collection

        async def execute_with_retry(self, fn, *args, **kwargs):
            return await fn(*args, **kwargs)

    results = await IndexOptimizer(Pool()).create_media_indexes()
    assert len(results) == 16
    assert all(results.values())
    assert collection.create_index.await_count == 16
    collection.drop_index.assert_not_awaited()


@pytest.mark.integration
def test_real_mongodb_inventory_is_non_mutating_and_detects_text_index():
    uri = os.environ.get("TEST_MONGO_URI")
    if not uri:
        pytest.skip("Ephemeral CI MongoDB only")
    assert is_local(uri), "Never run write fixtures against a remote database"
    name = f"ph016_ci_{uuid4().hex}"
    with MongoClient(uri, serverSelectionTimeoutMS=5000) as client:
        coll = client[name].media_files
        try:
            coll.insert_one({"_id": "fixture", "file_name": "PH016 staging example"})
            coll.create_index(
                [("file_name", "text"), ("caption", "text")],
                name="text_search_idx", default_language="english",
            )
            coll.create_index([("file_type", 1), ("indexed_at", -1)],
                              name="file_type_time_idx")
            before = list(coll.list_indexes())
            doc = coll.find_one({"_id": "fixture"})
            report = audit_media_indexes(coll)
            match = {i["name"]: i["status"] for i in report["indexes"]}
            assert match["text_search_idx"] == "matching"
            assert match["file_type_time_idx"] == "matching"
            assert match["resolution_idx"] == "missing"
            assert report["observed_count"] == 3
            assert report["unmanaged_indexes"] == []
            assert list(coll.list_indexes()) == before
            assert coll.find_one({"_id": "fixture"}) == doc
        finally:
            client.drop_database(name)
