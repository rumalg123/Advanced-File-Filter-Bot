"""PH-012: offline production/staging identity isolation, no network calls."""
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.staging_preflight import (
    REQUIRED_ACK, StagingSafetyError, load_env,
    validate_isolation, validate_runtime, _mongo_hosts
)
from scripts.validate_staging_compose import (
    UnsafeStagingCompose, validate_compose
)


def configs():
    prod = {
        "ENVIRONMENT": "production",
        "BOT_TOKEN": "100000:" + "A" * 35,
        "DATABASE_URI": "mongodb+srv://produser:secret@prod1.example.mongodb.net/",
        "DATABASE_NAME": "PIRO",
        "LOG_CHANNEL": "-1001111222233",
        "CHANNELS": "-1001111222234",
    }
    stage = {
        "ENVIRONMENT": "staging",
        "STAGING_OPERATOR_ACK": REQUIRED_ACK,
        "BOT_TOKEN": "200000:" + "B" * 35,
        "SESSION": "filefilter_staging",
        "DATABASE_URI": "mongodb+srv://stguser:secret@staging1.example.mongodb.net/",
        "DATABASE_NAME": "staging_filefilter",
        "DATABASE_URIS": "",
        "DATABASE_NAMES": "",
        "LOG_CHANNEL": "-1009999888877",
        "CHANNELS": "-1009999888878",
        "REDIS_STATE_URI": "",
        "AUTO_UPDATE": "false",
        "UPDATE_ON_START": "false",
        "PUBLIC_FILE_STORE": "false",
    }
    return prod, stage


def test_distinct_credentials_database_and_channels_accepted_without_network():
    prod, stage = configs()
    validate_isolation(prod, stage)
    validate_runtime(stage)


@pytest.mark.parametrize("key,value", [
    ("BOT_TOKEN", "100000:" + "A" * 35),
    ("DATABASE_URI", "mongodb+srv://differentuser:secret@prod1.example.mongodb.net/"),
    ("DATABASE_NAME", "PIRO"),
    ("CHANNELS", "-1001111222234"),
    ("LOG_CHANNEL", "-1001111222233"),
])
def test_accidental_production_crossover_is_blocked(key, value):
    prod, stage = configs()
    stage[key] = value
    with pytest.raises(StagingSafetyError):
        validate_isolation(prod, stage)


@pytest.mark.parametrize("key,value", [
    ("ENVIRONMENT", "production"),
    ("STAGING_OPERATOR_ACK", ""),
    ("BOT_TOKEN", "REPLACE_WITH_TOKEN"),
    ("SESSION", "Media_search"),
    ("DATABASE_NAME", "PIRO"),
    ("DATABASE_URIS", "mongodb://other.example:27017"),
    ("DATABASE_NAMES", "realprod"),
    ("REDIS_URI", "redis://public.example:6379/0"),
    ("REDIS_STATE_URI", "redis://prod-state:6379/0"),
    ("AUTO_UPDATE", "true"),
    ("UPDATE_ON_START", "true"),
    ("PUBLIC_FILE_STORE", "true"),
    ("LOG_CHANNEL", "0"),
])
def test_runtime_guard_fails_closed_for_bad_staging_settings(key, value):
    _, stage = configs()
    stage[key] = value
    with pytest.raises(StagingSafetyError):
        validate_runtime(stage)


def test_missing_production_context_is_not_assumed_safe():
    _, stage = configs()
    with pytest.raises(StagingSafetyError, match="incomplete"):
        validate_isolation({}, stage)


def test_multi_host_production_cluster_overlap_is_rejected():
    prod, stage = configs()
    prod["DATABASE_URI"] = "mongodb://u:p@host-a.example:27017,host-b.example:27017/"
    stage["DATABASE_URI"] = "mongodb://u:p@host-b.example:27018/"
    with pytest.raises(StagingSafetyError, match="separate MongoDB"):
        validate_isolation(prod, stage)
    assert _mongo_hosts(prod["DATABASE_URI"]) == frozenset(
        {"host-a.example", "host-b.example"}
    )


def test_dotenv_parsing_never_prints_secrets_and_does_not_execute(tmp_path, capsys):
    prod, stage = configs()
    stage_file = tmp_path / "staging.env"
    stage_file.write_text("\n".join(f"{key}={value}" for key, value in stage.items()))
    loaded = load_env(str(stage_file))
    assert loaded["BOT_TOKEN"] == stage["BOT_TOKEN"]
    validate_isolation(prod, loaded)
    assert capsys.readouterr().out == ""


def valid_resolved_compose():
    return {
        "name": "advanced-file-filter-staging",
        "services": {
            "redis": {
                "volumes": [{"type": "volume", "source": "advanced-file-filter-staging_staging-redis-data"}]
            },
            "file-filter-bot": {
                "profiles": ["staging-bot"],
                "entrypoint": ["/bin/sh", "-ec", "python scripts/staging_preflight.py --runtime && exec bash start.sh"],
                "environment": {
                    "ENVIRONMENT": "staging", "AUTO_UPDATE": "false",
                    "UPDATE_ON_START": "false", "REDIS_URI": "redis://redis:6379/0",
                    "REDIS_STATE_URI": "",
                },
                "volumes": [{"type": "volume", "source": "advanced-file-filter-staging_staging-bot-data"}]
            },
        },
        "networks": {"advanced-file-filter-staging_staging-network": {"driver": "bridge"}}
    }


def test_staging_compose_contract_succeeds_without_production_resources():
    validate_compose(valid_resolved_compose())


@pytest.mark.parametrize("modify", [
    lambda d: d["services"]["file-filter-bot"].update({"ports": [{"published": "8000"}]}),
    lambda d: d["services"]["redis"].update({"container_name": "file-filter-redis"}),
    lambda d: d["services"]["file-filter-bot"].pop("profiles"),
    lambda d: d["services"]["file-filter-bot"]["environment"].update({"AUTO_UPDATE": "true"}),
    lambda d: d["services"]["redis"]["volumes"][0].update({"source": "redis-data"}),
    lambda d: d["networks"]["advanced-file-filter-staging_staging-network"].update({"external": True}),
])
def test_staging_compose_blocks_unsafe_drift(modify):
    config = valid_resolved_compose()
    modify(config)
    with pytest.raises(UnsafeStagingCompose):
        validate_compose(config)


def test_docker_context_excludes_sensitive_runtime_files():
    dockerignore = (Path(__file__).parents[1] / ".dockerignore").read_text()
    for pattern in (".env", ".env.*", ".secrets", "*.session", "backups", "data"):
        assert pattern in dockerignore
    staging_compose = (Path(__file__).parents[1] / "docker-compose.staging.yml").read_text()
    assert "container_name" not in staging_compose.split("services:", 1)[1].split("volumes:", 1)[0]
    assert "ports:" not in staging_compose
