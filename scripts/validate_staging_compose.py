"""PH-012: Validate the fully resolved staging Compose config (read-only).

Accepts JSON from 'docker compose -f docker-compose.staging.yml config --format json'.
Never prints environment variables, Telegram tokens, or MongoDB URLs.
"""
import json
import sys


class UnsafeStagingCompose(ValueError):
    pass


def validate_compose(document: dict) -> None:
    services = document.get("services", {})
    if set(services) != {"redis", "file-filter-bot"}:
        raise UnsafeStagingCompose("Unexpected staging service set")
    if not document.get("name", "").endswith("-staging"):
        raise UnsafeStagingCompose("Compose project must be staging-only")
    for name, service in services.items():
        if service.get("ports"):
            raise UnsafeStagingCompose("Staging must not publish host ports")
        if service.get("container_name"):
            raise UnsafeStagingCompose("Staging must not use fixed container names")
        if service.get("network_mode") in ("host", "service:"):
            raise UnsafeStagingCompose("Staging host networking is forbidden")
        for mount in service.get("volumes", []):
            if mount.get("type") == "volume":
                vol = mount.get("source", "")
                if "staging" not in vol:
                    raise UnsafeStagingCompose("Staging reuses a non-staging volume")
    bot = services["file-filter-bot"]
    if "staging-bot" not in bot.get("profiles", []):
        raise UnsafeStagingCompose("Telegram bot must require an explicit profile")
    env = bot.get("environment", {})
    for key, expected in (
        ("AUTO_UPDATE", "false"),
        ("UPDATE_ON_START", "false"),
        ("ENVIRONMENT", "staging"),
        ("REDIS_URI", "redis://redis:6379/0"),
        ("REDIS_STATE_URI", ""),
    ):
        if str(env.get(key, "")).lower() != expected:
            raise UnsafeStagingCompose("Unsafe staging environment configuration")
    if not any("staging_preflight.py --runtime" in " ".join(bot.get("entrypoint", []))
               for _ in (0,)):
        raise UnsafeStagingCompose("Missing container runtime staging guard")
    networks = document.get("networks", {})
    if any(network.get("external") for network in networks.values()):
        raise UnsafeStagingCompose("Staging must not attach external networks")


def main() -> int:
    try:
        document = json.load(sys.stdin)
        validate_compose(document)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        # Safety checks use static messages; never print resolved env values.
        print("STAGING COMPOSE BLOCKED: " + str(exc))
        return 2
    print("STAGING COMPOSE VERIFIED (structural checks only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
