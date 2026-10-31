"""Fail-closed guard for credential-bearing GitHub Actions Telegram QA runs.

Never print credential values, resolved environment dumps, or MongoDB URIs.
The runner uses only loopback database services and dedicated QA chat IDs.
"""
import os
import re
import sys


def validate(env: dict[str, str]) -> None:
    if env.get("CI") != "true" or env.get("GITHUB_REF") != "refs/heads/QA":
        raise ValueError("Real Telegram QA is restricted to CI on refs/heads/QA")
    if env.get("QA_LIVE_ENABLED") != "true":
        raise ValueError("Real Telegram QA requires explicit QA_LIVE_ENABLED=true")
    for name in ("API_ID", "API_HASH", "BOT_TOKEN",
                 "QA_ADMIN_SESSION", "QA_USER_SESSION",
                 "QA_OWNER_ID", "QA_BOT_USERNAME",
                 "QA_GROUP_ID", "CHANNELS", "LOG_CHANNEL"):
        if not env.get(name, "").strip():
            raise ValueError(f"Missing QA configuration: {name}")

    if not env["API_ID"].isdigit() or int(env["API_ID"]) <= 0:
        raise ValueError("API_ID must be a positive integer")
    if not re.fullmatch(r"[0-9]{4,}:[A-Za-z0-9_-]{20,}", env["BOT_TOKEN"]):
        raise ValueError("QA_BOT_TOKEN must have Telegram token format")
    if not re.fullmatch(r"[A-Za-z0-9_]{5,}", env["QA_BOT_USERNAME"].lstrip("@")):
        raise ValueError("QA_BOT_USERNAME format is invalid")
    if not env["QA_OWNER_ID"].isdigit() or int(env["QA_OWNER_ID"]) <= 0:
        raise ValueError("QA_OWNER_ID must be a positive integer")
    if env.get("ADMINS") != env["QA_OWNER_ID"]:
        raise ValueError("ADMINS must equal the dedicated QA_OWNER_ID")
    if env["QA_ADMIN_SESSION"] == env["QA_USER_SESSION"]:
        raise ValueError("QA user sessions must be different")

    if env.get("ENVIRONMENT") != "staging":
        raise ValueError("ENVIRONMENT must be staging")
    if not env.get("SESSION", "").endswith("_staging"):
        raise ValueError("Bot session must have a staging-only name")
    if env.get("DATABASE_URI") != "mongodb://127.0.0.1:27017/":
        raise ValueError("MongoDB must be the ephemeral local CI instance")
    if env.get("DATABASE_NAME") != "staging_filefilter":
        raise ValueError("MongoDB name must be staging_filefilter")
    if env.get("REDIS_URI") != "redis://127.0.0.1:6379/0":
        raise ValueError("Redis must be the ephemeral local CI instance")
    for key in ("DATABASE_URIS", "DATABASE_NAMES", "REDIS_STATE_URI"):
        if env.get(key, "").strip():
            raise ValueError(f"{key} must be empty in first-stage QA")
    for key in ("AUTO_UPDATE", "UPDATE_ON_START", "PUBLIC_FILE_STORE"):
        if env.get(key, "").lower() != "false":
            raise ValueError(f"{key} must be disabled")

    chat_ids = (env["QA_GROUP_ID"], env["CHANNELS"], env["LOG_CHANNEL"])
    if len(set(chat_ids)) != len(chat_ids):
        raise ValueError("QA group, index channel and log channel must differ")
    if any(not re.fullmatch(r"-100[0-9]+", chat) for chat in chat_ids):
        raise ValueError("QA chats must use numeric supergroup/channel IDs")


if __name__ == "__main__":
    try:
        validate(dict(os.environ))
    except ValueError as exc:
        print(f"QA isolation validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    print("QA isolation guard passed for dedicated local services.")
