"""PH-012 offline staging safety gate.

Requires a dedicated Telegram test bot, separate MongoDB cluster, explicit
test channels and a staging-only Compose deployment. The host comparison is
read-only. The container runtime check prevents accidental starts without
staging-only settings. No network calls, data writes or secret output.
"""
import argparse
import hmac
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values


class StagingSafetyError(ValueError):
    """Preflight failed; error messages must never expose secret values."""


REQUIRED_ACK = "I_HAVE_VERIFIED_ISOLATION"
CHANNEL_KEYS = (
    "LOG_CHANNEL", "INDEX_REQ_CHANNEL", "REQ_CHANNEL",
    "DELETE_CHANNEL", "FILE_STORE_CHANNEL", "AUTH_CHANNEL",
    "SUPPORT_GROUP_ID", "CHANNELS", "AUTH_GROUPS",
)


def load_env(path: str) -> dict[str, str]:
    source = Path(path)
    if not source.is_file():
        raise StagingSafetyError("Environment file is missing")
    try:
        return {str(k).upper(): str(v or "") for k, v in dotenv_values(
            source, interpolate=False
        ).items() if k is not None}
    except (OSError, UnicodeError, ValueError):
        raise StagingSafetyError("Environment file cannot be parsed") from None


def _mongo_hosts(uri: str) -> frozenset[str]:
    """Compare MongoDB endpoints without DNS/network calls or logging URIs."""
    try:
        parsed = urlsplit(uri)
        if parsed.scheme not in ("mongodb", "mongodb+srv"):
            raise ValueError("invalid scheme")
        netloc = parsed.netloc.rsplit("@", 1)[-1]
        hosts = set()
        for segment in netloc.split(","):
            host = segment.strip().lower()
            if host.startswith("["):
                host = host.split("]", 1)[0].lstrip("[")
            else:
                host = host.split(":", 1)[0]
            if not host or not re.fullmatch(r"[a-z0-9.\-_]+|[a-f0-9:]+", host):
                raise ValueError("invalid hostname")
            hosts.add(host)
        if not hosts:
            raise ValueError("empty server set")
        return frozenset(hosts)
    except (TypeError, ValueError):
        raise StagingSafetyError("Invalid MongoDB connection configuration") from None


def _channel_targets(config: dict) -> set[str]:
    values = set()
    for key in CHANNEL_KEYS:
        value = config.get(key, "")
        for token in re.split(r"[,\s]+", value):
            token = token.strip().casefold()
            if token and token not in ("0", "none", "null"):
                values.add(token)
    return values


def validate_runtime(stage: dict[str, str]) -> None:
    if stage.get("ENVIRONMENT", "").lower() != "staging":
        raise StagingSafetyError("ENVIRONMENT must be staging")
    if stage.get("STAGING_OPERATOR_ACK") != REQUIRED_ACK:
        raise StagingSafetyError("Explicit staging isolation acknowledgment required")
    token = stage.get("BOT_TOKEN", "")
    if not re.fullmatch(r"[0-9]{4,}:[A-Za-z0-9_-]{20,}", token):
        raise StagingSafetyError("Dedicated test Telegram bot token required")
    if stage.get("SESSION", "").lower().endswith("_staging") is False:
        raise StagingSafetyError("Telegram session must have a staging-only name")
    if not stage.get("DATABASE_NAME", "").lower().startswith("staging_"):
        raise StagingSafetyError("Staging MongoDB database name must start with staging_")
    _mongo_hosts(stage.get("DATABASE_URI", ""))
    if stage.get("DATABASE_URIS", "").strip() or stage.get("DATABASE_NAMES", "").strip():
        raise StagingSafetyError("Additional MongoDB databases must be disabled in staging")
    if stage.get("REDIS_STATE_URI", "").strip():
        raise StagingSafetyError("Staging Compose forbids external Redis state backend")
    if stage.get("REDIS_URI", "").strip() not in ("", "redis://redis:6379/0"):
        raise StagingSafetyError("Staging Redis must be the private Compose service")
    if stage.get("AUTO_UPDATE", "").lower() not in ("", "false", "0"):
        raise StagingSafetyError("Staging automatic updates must be disabled")
    if stage.get("UPDATE_ON_START", "").lower() not in ("", "false", "0"):
        raise StagingSafetyError("Staging startup updates must be disabled")
    if stage.get("PUBLIC_FILE_STORE", "").lower() not in ("", "false", "0"):
        raise StagingSafetyError("Public file storage must be disabled in staging")
    targets = _channel_targets(stage)
    if not stage.get("LOG_CHANNEL", "").strip() or stage["LOG_CHANNEL"] in ("0", "-0"):
        raise StagingSafetyError("Dedicated nonzero test log channel required")
    if not targets:
        raise StagingSafetyError("Dedicated test channels are required")


def validate_isolation(production: dict[str, str], stage: dict[str, str]) -> None:
    """Compare the effective, operator-supplied production/staging env files."""
    validate_runtime(stage)
    for key in ("BOT_TOKEN", "DATABASE_URI", "DATABASE_NAME"):
        if not production.get(key):
            raise StagingSafetyError("Production comparison data is incomplete")
    if hmac.compare_digest(
        production["BOT_TOKEN"].encode(), stage["BOT_TOKEN"].encode()
    ):
        raise StagingSafetyError("Staging must use a different Telegram bot token")
    if _mongo_hosts(production["DATABASE_URI"]) & _mongo_hosts(stage["DATABASE_URI"]):
        raise StagingSafetyError("Staging requires a separate MongoDB server/cluster")
    if (production["DATABASE_NAME"].lower() == stage["DATABASE_NAME"].lower()):
        raise StagingSafetyError("Production and staging database names must differ")
    if _channel_targets(production) & _channel_targets(stage):
        raise StagingSafetyError("Staging and production Telegram channels overlap")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--runtime", action="store_true",
                      help="Staging container guard; never makes network requests")
    mode.add_argument("--production-env",
                      help="Path to locally accessible production environment file")
    parser.add_argument("--staging-env", default=".env.staging",
                        help="Staging env file for offline comparison")
    args = parser.parse_args()
    try:
        if args.runtime:
            validate_runtime({k.upper(): v for k, v in os.environ.items()})
        else:
            validate_isolation(
                load_env(args.production_env), load_env(args.staging_env)
            )
    except StagingSafetyError as exc:
        # These messages are deliberately generic and contain no URI/token.
        print("STAGING PREFLIGHT BLOCKED: " + str(exc))
        return 2
    print("STAGING PREFLIGHT PASSED (offline checks only; no network probe)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
