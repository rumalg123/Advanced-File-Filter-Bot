"""PH-006 bounded search observability and safe query compiler optimizations."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.database.errors import SearchBackendUnavailableError
from core.utils.search_observability import BUCKETS_MS, SearchTelemetry
from core.utils.search_matcher import _text_pattern
from repositories.media import MediaRepository


def test_histograms_keep_bounded_memory_and_calculate_bucket_percentiles():
    telemetry = SearchTelemetry(slow_query_ms=10000)
    assert telemetry.snapshot()["cache_hit_ratio"] is None

    for n in (1, 4, 5, 12, 55, 105, 220, 700, 3000, 9000, 11000):
        telemetry.observe("search", n)
    telemetry.observe("cache_hit", 5)
    telemetry.observe("cache_hit", 25)
    telemetry.observe("cache_miss", 200)

    snapshot = telemetry.snapshot()
    assert snapshot["scope"] == "current_process_since_start"
    assert snapshot["precision"] == "histogram_bucket_upper_bounds"
    assert snapshot["cache_hit_ratio"] == round(2 / 3, 4)
    assert snapshot["events"]["search"]["count"] == 11
    assert snapshot["events"]["search"]["p50_bucket_ms"] == 200
    assert snapshot["events"]["search"]["p95_bucket_ms"] == ">10000"
    assert len(telemetry._histograms["search"]) == len(BUCKETS_MS) + 1

    # Durations and queries are never retained as an unbounded list.
    assert not hasattr(telemetry, "queries")
    assert not hasattr(telemetry, "samples")
    assert "doctor x mafia" not in json.dumps(snapshot).lower()


def test_slow_query_log_uses_stage_and_duration_only(caplog):
    telemetry = SearchTelemetry(slow_query_ms=100)
    with caplog.at_level("WARNING"):
        telemetry.observe("count", 105)
        telemetry.observe("page", 20)
    assert "Slow media search count stage" in caplog.text
    assert "Slow media search page stage" not in caplog.text


def test_unknown_stage_cannot_expand_histogram_map_unboundedly():
    telemetry = SearchTelemetry()
    with pytest.raises(ValueError, match="Unknown"):
        telemetry.observe("arbitrary_user_query", 500)


def test_repeated_token_lookaheads_are_deduplicated_but_match_same_titles():
    pattern = _text_pattern("doctor doctor x mafia")
    assert pattern.count("doctor") == 1
    assert pattern.count("mafia") == 1
    # The previous regex required at least one doctor token, not two.
    import re

    assert re.search(pattern, "Doctor X Mafia S01E03", re.IGNORECASE)
    assert not re.search(pattern, "Doctor X S01E03", re.IGNORECASE)


class SmallCache:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, expire=None):
        self.values[key] = value
        return True

    async def delete(self, key):
        return self.values.pop(key, None) is not None


@pytest.mark.asyncio
async def test_media_repository_counts_cache_hit_miss_and_success(monkeypatch):
    telemetry = SearchTelemetry(slow_query_ms=100000)
    monkeypatch.setattr("repositories.media.search_telemetry", telemetry)
    repo = MediaRepository(None, SmallCache())
    repo.count = AsyncMock(return_value=0)
    repo.find_many = AsyncMock(return_value=[])

    assert await repo.search_files("doctor x") == ([], 0, 0)
    assert await repo.search_files("Doctor.X") == ([], 0, 0)

    snapshot = telemetry.snapshot()["events"]
    assert snapshot["cache_miss"]["count"] == 1
    assert snapshot["cache_hit"]["count"] == 1
    assert snapshot["count"]["count"] == 1
    assert snapshot["page"]["count"] == 1
    assert snapshot["search"]["count"] == 2
    assert snapshot["backend_error"]["count"] == 0
    repo.count.assert_awaited_once()


@pytest.mark.asyncio
async def test_media_repository_failure_telemetry_not_cached(monkeypatch):
    telemetry = SearchTelemetry(slow_query_ms=100000)
    monkeypatch.setattr("repositories.media.search_telemetry", telemetry)
    cache = SmallCache()
    repo = MediaRepository(None, cache)
    repo.count = AsyncMock(side_effect=TimeoutError("Internal MongoDB secret"))
    repo.find_many = AsyncMock()
    with pytest.raises(SearchBackendUnavailableError):
        await repo.search_files("Doctor X Mafia")
    assert telemetry.snapshot()["events"]["backend_error"]["count"] == 1
    assert telemetry.snapshot()["events"]["cache_miss"]["count"] == 1
    assert telemetry.snapshot()["events"]["search"]["count"] == 0
    assert repo.find_many.await_count == 0
    assert not any("search:" in k for k in cache.values)
