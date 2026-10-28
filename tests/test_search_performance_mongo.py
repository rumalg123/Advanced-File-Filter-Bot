"""Real MongoDB explain test for PH-006, with a localhost-only CI server."""
import json
import os
from uuid import uuid4

import pytest
from pymongo import MongoClient

from scripts.profile_media_search import concise_plan, is_local, profile

pytestmark = pytest.mark.integration


def test_profiler_is_local_by_default():
    assert is_local("mongodb://127.0.0.1:27017")
    assert is_local("mongodb://localhost:27017")
    assert not is_local("mongodb://mongo.example.com:27017")
    assert not is_local("mongodb+srv://cluster.example.com")


def test_concise_plan_avoids_returning_sensitive_query_expressions():
    report = concise_plan({
        "executionStats": {
            "nReturned": 2, "totalDocsExamined": 90,
            "totalKeysExamined": 25, "executionTimeMillis": 7,
        },
        "queryPlanner": {
            "winningPlan": {"stage": "FETCH", "inputStage": {
                "stage": "IXSCAN", "indexName": "file_type_time_idx"
            }},
            "parsedQuery": {"file_name": "A private title"},
        },
    })
    assert report["indexesUsed"] == ["file_type_time_idx"]
    assert report["stages"] == ["FETCH", "IXSCAN"]
    assert "A private title" not in json.dumps(report)


def test_real_mongo_explain_preserves_exact_filename_search_semantics():
    uri = os.environ.get("TEST_MONGO_URI")
    if not uri:
        pytest.skip("Only run against the CI MongoDB service")
    assert is_local(uri), "Integration tests must never query a remote MongoDB"

    name = f"ph006_ci_{uuid4().hex}"
    with MongoClient(uri, serverSelectionTimeoutMS=5000) as client:
        db = client[name]
        try:
            db.media_files.insert_many([
                {
                    "_id": "fileA",
                    "file_name": "Doctor X Mafia in White S01E03 NF x264 540p mkv",
                    "file_type": "video",
                    "season": "01",
                    "episode": "03",
                    "resolution": "960x540",
                    "indexed_at": "2026-10-28T00:00:00",
                },
                {
                    "_id": "fileB",
                    "file_name": "Doctor X Mafia in White S01E02 NF x264 1080p mkv",
                    "file_type": "video",
                    "season": "01",
                    "episode": "02",
                    "resolution": "1920x1080",
                    "indexed_at": "2026-10-27T00:00:00",
                },
            ] + [
                {
                    "_id": f"filler-{i}",
                    "file_name": f"Unrelated Cartoon Release {i} 720p mkv",
                    "file_type": "video",
                    "indexed_at": "2026-10-25T00:00:00",
                }
                for i in range(200)
            ])
            db.media_files.create_index([("indexed_at", -1)], name="date_index")
            db.media_files.create_index([
                ("file_name", "text"), ("caption", "text")
            ], name="text_search_idx")

            before_count = db.media_files.count_documents({})
            before_indexes = sorted(db.media_files.index_information())
            report = profile(
                db,
                ("Doctor X Mafia in White S01E03 NF x264 540p mkv",
                 "doctor x mafia", "s01e03", "540p"),
                include_counts=True,
                include_index_stats=True,
                max_time_ms=5000,
            )
            assert report["document_count"] == before_count
            assert report["limit"] == 10
            assert report["queries"][0]["page"]["nReturned"] == 1
            assert report["queries"][1]["page"]["nReturned"] == 2
            assert report["queries"][2]["page"]["nReturned"] == 1
            assert report["queries"][3]["page"]["nReturned"] >= 1
            assert report["queries"][0]["page"]["totalDocsExamined"] >= 1
            assert "text_search_idx" in report["indexes"]
            assert any(x["name"] == "text_search_idx" for x in report["index_usage"])
            assert all("query_id" in q and "page" in q and "count" in q
                       for q in report["queries"])
            assert "Doctor X" not in json.dumps(report)
            # The profiler itself cannot alter existing data or indexes.
            assert db.media_files.count_documents({}) == before_count
            assert sorted(db.media_files.index_information()) == before_indexes
        finally:
            client.drop_database(name)
