"""Offline tests for the CI-only Telegram credential gate."""
import pytest

from scripts.qa_ci_guard import validate


def qa_env():
    return {
        "CI": "true",
        "GITHUB_REF": "refs/heads/QA",
        "QA_LIVE_ENABLED": "true",
        "API_ID": "123456",
        "API_HASH": "test-api-hash",
        "BOT_TOKEN": "123456:" + "A" * 35,
        "QA_ADMIN_SESSION": "placeholder-admin-session",
        "QA_USER_SESSION": "placeholder-user-session",
        "QA_OWNER_ID": "12345678",
        "ADMINS": "12345678",
        "QA_BOT_USERNAME": "dedicated_qa_bot",
        "QA_GROUP_ID": "-1001111111111",
        "CHANNELS": "-1002222222222",
        "LOG_CHANNEL": "-1003333333333",
        "ENVIRONMENT": "staging",
        "SESSION": "ci_qa_staging",
        "DATABASE_URI": "mongodb://127.0.0.1:27017/",
        "DATABASE_NAME": "staging_filefilter",
        "REDIS_URI": "redis://127.0.0.1:6379/0",
        "DATABASE_URIS": "",
        "DATABASE_NAMES": "",
        "REDIS_STATE_URI": "",
        "AUTO_UPDATE": "false",
        "UPDATE_ON_START": "false",
        "PUBLIC_FILE_STORE": "false",
    }


def test_ci_guard_accepts_isolated_config():
    validate(qa_env())


@pytest.mark.parametrize("key,value", [
    ("CI", "false"),
    ("GITHUB_REF", "refs/heads/main"),
    ("QA_LIVE_ENABLED", "false"),
    ("DATABASE_URI", "mongodb+srv://production.example/"),
    ("DATABASE_NAME", "production"),
    ("DATABASE_URIS", "mongodb://elsewhere"),
    ("REDIS_URI", "redis://public.example:6379/0"),
    ("REDIS_STATE_URI", "redis://127.0.0.1:6380/0"),
    ("SESSION", "production"),
    ("AUTO_UPDATE", "true"),
    ("PUBLIC_FILE_STORE", "true"),
    ("QA_GROUP_ID", "-1002222222222"),
    ("LOG_CHANNEL", "0"),
    ("QA_ADMIN_SESSION", "placeholder-user-session"),
    ("ADMINS", "998877"),
    ("QA_OWNER_ID", ""),
])
def test_ci_guard_rejects_unsafe_config(key, value):
    cfg = qa_env()
    cfg[key] = value
    with pytest.raises(ValueError):
        validate(cfg)
