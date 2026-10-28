#!/usr/bin/env python3
"""PH-009: bounded, READ-ONLY inventory of Redis serialization tags.

No pickle loading, no Redis writes and no key/value names in output.
The inventory is an estimate: a plain-text key beginning with p may look like
an old pickle tag, and an unprefixed value cannot always be classified safely.
"""
import argparse
import json
import os
from collections import Counter
from urllib.parse import urlsplit

import redis


def classify(prefix: bytes) -> str:
    if prefix[:2] == b"cp" or prefix[:1] == b"p":
        return "possibly_pickle_tagged"
    if prefix[:2] in (b"cj", b"cm"):
        return "compressed_safe_tagged"
    if prefix[:1] in (b"j", b"m"):
        return "safe_tagged_or_ambiguous_plaintext"
    if prefix[:1] == b"\x80" and len(prefix) > 1 and prefix[1] <= 5:
        return "possibly_untagged_binary_pickle"
    return "untagged_or_other"


def inventory(client, max_keys: int = 5000) -> dict:
    if max_keys <= 0:
        raise ValueError("max_keys must be positive")
    counters = Counter()
    seen = 0
    cursor = 0
    while True:
        cursor, keys = client.scan(cursor=cursor, count=min(200, max_keys))
        for key in keys:
            if seen >= max_keys:
                break
            seen += 1
            key_type = client.type(key)
            if key_type not in (b"string", "string"):
                counters["non_string_keys"] += 1
                continue
            # Only read the first two bytes, never contents or key names.
            prefix = client.getrange(key, 0, 1)
            counters[classify(prefix)] += 1
            ttl = client.pttl(key)
            if ttl == -1:
                counters["string_keys_without_ttl"] += 1
            elif ttl >= 0:
                counters["string_keys_with_ttl"] += 1
        if cursor == 0 or seen >= max_keys:
            break
    return {
        "scanned_keys": seen,
        "max_keys": max_keys,
        "scan_completed": cursor == 0 and seen < max_keys,
        "approximate_counts": dict(sorted(counters.items())),
        "read_only": True,
        "warning": "Format classification is approximate; no values were decoded",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-keys", type=int, default=5000)
    parser.add_argument(
        "--state", action="store_true",
        help="Inventory REDIS_STATE_URI instead of REDIS_URI"
    )
    parser.add_argument(
        "--allow-remote", action="store_true",
        help="Allow read-only inventory of a non-loopback Redis host"
    )
    args = parser.parse_args()
    if not 1 <= args.max_keys <= 100000:
        parser.error("--max-keys must be 1..100000")

    uri = os.environ.get("REDIS_STATE_URI" if args.state else "REDIS_URI", "")
    if not uri:
        parser.error("Redis URL not configured in the environment")
    parsed = urlsplit(uri)
    if parsed.scheme not in ("redis", "rediss") or not parsed.hostname:
        parser.error("Expected a redis:// or rediss:// URI")
    if (not args.allow_remote and
            parsed.hostname.lower() not in ("127.0.0.1", "localhost", "::1")):
        parser.error("Remote Redis requires explicit --allow-remote")

    client = redis.Redis.from_url(uri, socket_connect_timeout=3, socket_timeout=5)
    try:
        client.ping()
        print(json.dumps(inventory(client, max_keys=args.max_keys),
                         indent=2, sort_keys=True))
    finally:
        client.close()


if __name__ == "__main__":
    main()
