#!/usr/bin/env python3
"""PH-016: read-only media index inventory and drift report.

Reads DATABASE_URI and DATABASE_NAME from the process environment; never
loads .env. Does not print MongoDB credentials, hostname, documents, search
queries, raw index expressions or data. Only listIndexes and optional
$indexStats. Default localhost-only; remote use requires --allow-remote.

This tool DOES NOT create, drop, hide, rename or modify indexes.
"""
import argparse
from itertools import islice
import json
import os

from pymongo import MongoClient

from core.database.media_indexes import (
    compare_index_definition,
    index_definition,
    media_index_manifest,
)
from scripts.profile_media_search import is_local

MAX_INDEXES = 200


def public_index_definition(index):
    """Report key/options metadata, never raw partial-filter values."""
    view = index_definition(index)
    for option in ("partialFilterExpression", "wildcardProjection"):
        if option in view["options"]:
            view["options"][option] = "<redacted>"
    return view


def audit_media_indexes(collection, *, include_usage=False, max_time_ms=3000):
    """Compare observed MongoDB specs with the single source-of-truth manifest.

    All returned fields are sanitized index metadata; not documents or URLs.
    Usage stats are per-node and resettable, so zero operations is NOT proof
    of redundancy. Key prefixes are candidates for analysis, never drops.
    """
    if not 100 <= max_time_ms <= 10000:
        raise ValueError("max_time_ms must be 100..10000")
    # PyMongo Collection.list_indexes() has no maxTimeMS kwarg. The CLI's
    # MongoClient socketTimeoutMS bounds the remote read instead.
    observed = list(islice(collection.list_indexes(), MAX_INDEXES + 1))
    if len(observed) > MAX_INDEXES:
        raise ValueError("Media index count exceeds safe inventory limit")
    by_name = {spec["name"]: dict(spec) for spec in observed}
    if len(by_name) != len(observed):
        raise ValueError("Duplicate index names reported")
    manifest = media_index_manifest(include_search_tokens=any(
        item.get("name") in ("media_search_terms_v1", "media_stable_page_v1") for item in observed
    ))
    declared_names = {spec["name"] for spec in manifest}
    report = {
        "collection": "media_files",
        "mode": "read_only",
        "observed_count": len(observed),
        "declared_count": len(manifest),
        "indexes": [],
        "unmanaged_indexes": [],
        "prefix_candidates": [],
    }
    for spec in manifest:
        name = spec["name"]
        actual = by_name.get(name)
        if actual is None:
            status = "missing"
        else:
            status = "matching" if compare_index_definition(spec, actual) else "definition_drift"
        report["indexes"].append({
            "name": name,
            "status": status,
            "expected": public_index_definition(spec),
            "observed": public_index_definition(actual) if actual is not None else None,
        })
    for spec in observed:
        if spec["name"] not in declared_names and spec["name"] != "_id_":
            report["unmanaged_indexes"].append({
                "name": spec["name"],
                "definition": public_index_definition(spec),
            })

    # A key-prefix relationship alone is NOT sufficient evidence of redundancy.
    # Ignore text indexes, which are represented differently by MongoDB.
    for first in observed:
        for second in observed:
            if first["name"] == second["name"]:
                continue
            a = index_definition(first)["keys"]
            z = index_definition(second)["keys"]
            if (a and len(a) < len(z) and z[:len(a)] == a
                    and all(kind != "text" for _, kind in a + z)):
                report["prefix_candidates"].append({
                    "shorter": first["name"], "longer": second["name"],
                    "status": "requires_query_plan_and_option_review",
                })
    report["prefix_candidates"].sort(key=lambda p: (p["shorter"], p["longer"]))

    if include_usage:
        usage = {}
        cursor = collection.aggregate([{"$indexStats": {}}], maxTimeMS=max_time_ms)
        for item in islice(cursor, MAX_INDEXES * 20 + 1):
            # Stats are per host. Do not include hostnames/shards in reports.
            name = item.get("name")
            if not isinstance(name, str):
                continue
            entry = usage.setdefault(name, {"sampled_nodes": 0, "access_ops": 0, "since": []})
            entry["sampled_nodes"] += 1
            count = item.get("accesses", {}).get("ops")
            if isinstance(count, int):
                entry["access_ops"] += count
            since = item.get("accesses", {}).get("since")
            if hasattr(since, "isoformat"):
                entry["since"].append(since.isoformat())
        if sum(x["sampled_nodes"] for x in usage.values()) > MAX_INDEXES * 20:
            raise ValueError("Index usage stats exceed safe inventory limit")
        report["index_usage"] = usage
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-remote", action="store_true",
                        help="Operator acknowledgement to query an external database")
    parser.add_argument("--include-index-stats", action="store_true",
                        help="Requires clusterMonitor; only per-node since-restart counts")
    parser.add_argument("--max-time-ms", type=int, default=3000)
    args = parser.parse_args()
    if not 100 <= args.max_time_ms <= 10000:
        parser.error("--max-time-ms must be 100..10000")
    uri = os.environ.get("DATABASE_URI")
    name = os.environ.get("DATABASE_NAME")
    if not uri or not name:
        parser.error("DATABASE_URI and DATABASE_NAME are required in the environment")
    if not args.allow_remote and not is_local(uri):
        parser.error("Remote index audit requires explicit --allow-remote")
    try:
        with MongoClient(
            uri, appname="PH016-ReadOnlyMediaIndexAudit",
            serverSelectionTimeoutMS=5000,
            socketTimeoutMS=args.max_time_ms + 3000,
        ) as client:
            report = audit_media_indexes(
                client[name].media_files, include_usage=args.include_index_stats,
                max_time_ms=args.max_time_ms,
            )
        print(json.dumps(report, sort_keys=True, indent=2))
    except Exception:
        # Avoid including credential-bearing PyMongo exception details.
        parser.exit(1, "Media index inventory failed; check role/network/timeout locally.\n")


if __name__ == "__main__":
    main()
