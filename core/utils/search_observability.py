"""PH-006: bounded, privacy-preserving media search telemetry.

In-process counters are intentionally low overhead and never store queries,
filenames, user IDs, filenames hashes, or MongoDB documents. Histograms use
fixed buckets instead of an unbounded list of measured durations.

Snapshots are process-local, since multi-replica aggregation is a separate
observability concern. This module performs no MongoDB or Redis writes.
"""
from collections import Counter
from threading import Lock
from typing import Any

from core.utils.logger import get_logger

logger = get_logger(__name__)

BUCKETS_MS = (5, 10, 25, 50, 100, 200, 500, 1000, 2000, 5000, 10000)
OBSERVATIONS = frozenset((
    "cache_hit", "cache_miss", "count", "page", "search",
    "backend_error", "generation_error",
))


class SearchTelemetry:
    """Thread-safe fixed-memory histograms for each stage of a search."""

    def __init__(self, slow_query_ms: float = 1000):
        if slow_query_ms <= 0:
            raise ValueError("Slow-query threshold must be positive")
        self.slow_query_ms = float(slow_query_ms)
        self._lock = Lock()
        self._histograms: dict[str, list[int]] = {
            event: [0] * (len(BUCKETS_MS) + 1) for event in OBSERVATIONS
        }
        self._counts: Counter[str] = Counter()
        self._durations_ms: Counter[str] = Counter()
        self._max_ms: dict[str, float] = {event: 0.0 for event in OBSERVATIONS}

    def observe(self, event: str, duration_ms: float) -> None:
        if event not in OBSERVATIONS:
            raise ValueError(f"Unknown search measurement: {event}")
        duration_ms = max(0.0, float(duration_ms))
        index = next(
            (i for i, limit in enumerate(BUCKETS_MS) if duration_ms <= limit),
            len(BUCKETS_MS),
        )
        with self._lock:
            self._counts[event] += 1
            self._histograms[event][index] += 1
            self._durations_ms[event] += duration_ms
            self._max_ms[event] = max(self._max_ms[event], duration_ms)

        if event in ("count", "page", "search") and duration_ms >= self.slow_query_ms:
            # Only a stage and latency: never log query text or credentials.
            logger.warning(
                "Slow media search %s stage (%.1f ms, threshold=%.1f ms)",
                event, duration_ms, self.slow_query_ms,
            )

    @staticmethod
    def _percentile(histogram: list[int], count: int, percentile: float) -> int | str | None:
        if count == 0:
            return None
        rank = max(1, int((percentile * count) + 0.999999))
        seen = 0
        for i, bucket_count in enumerate(histogram):
            seen += bucket_count
            if seen >= rank:
                return BUCKETS_MS[i] if i < len(BUCKETS_MS) else f">{BUCKETS_MS[-1]}"
        return f">{BUCKETS_MS[-1]}"

    def snapshot(self) -> dict[str, Any]:
        """Create a stable copy with no raw user/search material."""
        with self._lock:
            counts = dict(self._counts)
            hist = {name: list(buckets) for name, buckets in self._histograms.items()}
            total_ms = dict(self._durations_ms)
            maximum = dict(self._max_ms)

        outcomes = {}
        for event in sorted(OBSERVATIONS):
            count = counts.get(event, 0)
            outcomes[event] = {
                "count": count,
                "mean_ms": round(total_ms.get(event, 0.0) / count, 2) if count else None,
                "max_ms": round(maximum[event], 2) if count else None,
                # These are upper bounds of histogram buckets, not exact samples.
                "p50_bucket_ms": self._percentile(hist[event], count, 0.50),
                "p95_bucket_ms": self._percentile(hist[event], count, 0.95),
                "p99_bucket_ms": self._percentile(hist[event], count, 0.99),
            }

        hits = counts.get("cache_hit", 0)
        misses = counts.get("cache_miss", 0)
        return {
            "scope": "current_process_since_start",
            "precision": "histogram_bucket_upper_bounds",
            "slow_query_threshold_ms": self.slow_query_ms,
            "cache_hit_ratio": round(hits / (hits + misses), 4) if hits + misses else None,
            "events": outcomes,
        }


search_telemetry = SearchTelemetry()
