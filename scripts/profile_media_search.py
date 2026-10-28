#!/usr/bin/env python3
"""PH-006: read-only MongoDB media search plan profiler.

Reads DATABASE_URI and DATABASE_NAME from the process environment, not CLI
arguments or an automatically loaded .env file. Never prints credentials,
raw filenames, captions, query strings or Mongo documents. Only invokes
"explain", "listIndexes" (implicitly via index_information), and optionally
"$indexStats". No collection writes, index creation, or data migrations.

By default it only accepts localhost. An operator must explicitly pass
--allow-remote to inspect a remote/staging/production deployment.
"""
import argparse
import hashlib
import json
import os
from urllib.parse import urlsplit

from pymongo import MongoClient

from core.utils.search_matcher import build_media_search_filter
from core.utils.validators import normalize_query

DEFAULT_QUERIES = (
    "doctor x mafia",
    "doctor x mafia s01e03 540p",
    "s01e03",
    "540p",
)


def is_local(uri: str) -> bool:
    """Avoid accidental remote probing without an explicit operator flag."""
    from pymongo.uri_parser import parse_uri

    try:
        parsed = parse_uri(uri)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid DATABASE_URI") from exc
    return all(host.split(":")[0].strip("[]") in (
        "127.0.0.1", "localhost", "::1",
    ) for host, _ in parsed["nodelist"])


def concise_plan(explanation: dict) -> dict:
    execution = explanation.get("executionStats", {})
    planner = explanation.get("queryPlanner", {})
    stages = set()
    indexes = set()

    def visit(node):
        if isinstance(node, dict):
            if isinstance(node.get("stage"), str):
                stages.add(node["stage"])
            if isinstance(node.get("indexName"), str):
                indexes.add(node["indexName"])
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for v in node:
                visit(v)

    visit(planner.get("winningPlan", {}))
    return {
        "nReturned": execution.get("nReturned"),
        "totalDocsExamined": execution.get("totalDocsExamined"),
        "totalKeysExamined": execution.get("totalKeysExamined"),
        "executionTimeMillis": execution.get("executionTimeMillis"),
        "stages": sorted(stages),
        "indexesUsed": sorted(indexes),
    }


def profile(
    database,
    queries: tuple[str, ...],
    *,
    limit: int = 10,
    max_time_ms: int = 3000,
    use_caption: bool = True,
    include_counts: bool = False,
    include_index_stats: bool = False,
) -> dict:
    """Perform explain-only read operations, returning aggregate statistics."""
    output = {
        "collection": "media_files",
        "document_count": database.media_files.estimated_document_count(
            maxTimeMS=max_time_ms
        ),
        "indexes": sorted(database.media_files.index_information()),
        "limit": limit,
        "max_time_ms": max_time_ms,
        "queries": [],
    }
    if include_index_stats:
        output["index_usage"] = sorted(
            (
                {
                    "name": d.get("name"),
                    "access_ops": d.get("accesses", {}).get("ops"),
                }
                for d in database.media_files.aggregate(
                    [{"$indexStats": {}}], maxTimeMS=max_time_ms
                )
            ),
            key=lambda d: d["name"] or "",
        )

    for query in queries:
        normalized = normalize_query(query)
        # Exactly the same filter compiler used by the Telegram media search.
        predicate = build_media_search_filter(normalized, use_caption=use_caption)
        find_command = {
            "find": "media_files",
            "filter": predicate,
            "sort": {"indexed_at": -1},
            "limit": limit,
            "maxTimeMS": max_time_ms,
        }
        row = {
            "query_id": hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12],
            "token_count": len(normalized.split()),
        }
        explanation = database.command(
            "explain", find_command, verbosity="executionStats", maxTimeMS=max_time_ms
        )
        row["page"] = concise_plan(explanation)

        if include_counts:
            count_command = {
                "aggregate": "media_files",
                "pipeline": [{"$match": predicate}, {"$count": "total"}],
                "cursor": {},
                "maxTimeMS": max_time_ms,
            }
            count_explanation = database.command(
                "explain", count_command,
                verbosity="executionStats", maxTimeMS=max_time_ms,
            )
            # Aggregate explain can have a "stages" wrapper and different
            # structure. Record only the subset that is actually available.
            if "queryPlanner" not in count_explanation:
                stages = count_explanation.get("stages", [])
                source = next((stage.get("$cursor") for stage in stages
                               if isinstance(stage, dict) and "$cursor" in stage), {})
            else:
                source = count_explanation
            row["count"] = concise_plan(source)
        output["queries"].append(row)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", action="append", dest="queries", default=None,
                        help="Repeatable query; never printed, only a short digest")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--max-time-ms", type=int, default=3000)
    parser.add_argument("--no-caption", action="store_true")
    parser.add_argument("--include-counts", action="store_true",
                        help="Explain the potentially expensive exact match count")
    parser.add_argument("--index-stats", action="store_true",
                        help="Read index usage counters without modifying indexes")
    parser.add_argument("--allow-remote", action="store_true",
                        help="Explicit acknowledgement to profile a remote MongoDB")
    args = parser.parse_args()

    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100")
    if not 100 <= args.max_time_ms <= 10000:
        parser.error("--max-time-ms must be 100..10000")

    uri = os.getenv("DATABASE_URI")
    name = os.getenv("DATABASE_NAME")
    if not uri or not name:
        parser.error("DATABASE_URI and DATABASE_NAME must be set in the environment")
    if not args.allow_remote and not is_local(uri):
        parser.error("Remote MongoDB requires explicit --allow-remote")

    with MongoClient(
        uri, appname="PH006-ReadOnlySearchProfiler",
        serverSelectionTimeoutMS=5000, socketTimeoutMS=args.max_time_ms + 3000,
    ) as client:
        # Client is read-only by contract: all methods in profile() are read
        # methods. No authentication credentials are logged.
        report = profile(
            client[name], tuple(args.queries or DEFAULT_QUERIES),
            limit=args.limit, max_time_ms=args.max_time_ms,
            use_caption=not args.no_caption,
            include_counts=args.include_counts,
            include_index_stats=args.index_stats,
        )
        print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
