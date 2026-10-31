#!/usr/bin/env python3
"""Opt-in, non-destructive Redis operational state copy before a split cutover.

Dry-run by default. The bot MUST be stopped for the entire --apply run:
otherwise counters and live sessions can change during SCAN/DUMP/RESTORE.

Set REDIS_URI and REDIS_STATE_URI in the environment (not CLI arguments).
This script never deletes or rewrites source keys and never calls FLUSHDB.
"""
import argparse
import os
from collections import Counter

import redis
from redis.exceptions import ResponseError

from core.cache.routed_cache import STATE_PREFIXES, _server_identity
from core.cache.auth import redis_auth_kwargs


def is_state_key(key: bytes) -> bool:
    return key.decode("utf-8", "replace").startswith(STATE_PREFIXES)


def transfer_state(
    source, destination, apply: bool = False, replace_existing: bool = False
) -> dict:
    counts = Counter()
    for key in source.scan_iter(count=200):
        if not is_state_key(key):
            continue
        counts["identified"] += 1
        ttl = source.pttl(key)
        if ttl == -2:  # Key expired while inspecting it.
            counts["expired"] += 1
            continue
        if ttl == 0:
            # Never turn an almost-expired key into a persistent state key.
            counts["almost_expired"] += 1
            continue

        if ttl == -1 and key.startswith((
            b"rate_limit:", b"session:", b"search_results_",
            b"checksub_session:", b"deeplink_"
        )):
            # Session/rate-limit state must never become persistent by mistake.
            raise RuntimeError("Found an expiring state key without a TTL. Investigate before migration.")

        if destination.exists(key) and not replace_existing:
            counts["already_exists"] += 1
            continue

        if not apply:
            counts["would_copy"] += 1
            continue

        serialized = source.dump(key)
        if serialized is None:
            counts["expired"] += 1
            continue

        # RESTORE ttl=0 preserves a genuinely persistent key; positive PTTL
        # preserves the existing expiry with millisecond precision.
        try:
            destination.restore(key, max(0, ttl), serialized, replace=replace_existing)
            counts["copied"] += 1
        except ResponseError as error:
            if "BUSYKEY" in str(error).upper():
                counts["already_exists"] += 1
            else:
                raise

    return dict(counts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Copy state keys; by default only count and inspect."
    )
    parser.add_argument(
        "--bot-stopped", action="store_true",
        help="Required acknowledgement that all bot writers are stopped."
    )
    parser.add_argument(
        "--replace-existing", action="store_true",
        help="Advanced rollback only: overwrite destination state with latest source state."
    )
    args = parser.parse_args()
    if args.replace_existing and not args.apply:
        parser.error("--replace-existing requires --apply and --bot-stopped")
    if args.apply and not args.bot_stopped:
        parser.error("--apply requires --bot-stopped after stopping all bot replicas")

    source_uri = os.environ.get("REDIS_URI", "")
    destination_uri = os.environ.get("REDIS_STATE_URI", "")
    if not source_uri or not destination_uri:
        parser.error("REDIS_URI and REDIS_STATE_URI must both be set in the environment")
    if _server_identity(source_uri) == _server_identity(destination_uri):
        parser.error("State must be on a separate Redis server, not just another DB number")

    source = redis.Redis.from_url(
        source_uri, socket_connect_timeout=5, socket_timeout=10,
        **redis_auth_kwargs(
            source_uri, username=os.getenv("REDIS_USERNAME", ""),
            password_file=os.getenv("REDIS_PASSWORD_FILE", ""),
        )
    )
    destination = redis.Redis.from_url(
        destination_uri, socket_connect_timeout=5, socket_timeout=10,
        **redis_auth_kwargs(
            destination_uri, username=os.getenv("REDIS_STATE_USERNAME", ""),
            password_file=os.getenv("REDIS_STATE_PASSWORD_FILE", ""),
        )
    )
    try:
        source.ping()
        destination.ping()
        counts = transfer_state(
            source, destination,
            apply=args.apply,
            replace_existing=args.replace_existing,
        )
        print("State copy summary:", counts)
        print("Source keys were not deleted or modified.")
    finally:
        source.close()
        destination.close()


if __name__ == "__main__":
    main()
