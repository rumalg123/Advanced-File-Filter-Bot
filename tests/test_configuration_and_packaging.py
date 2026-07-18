import tomllib
from pathlib import Path
from types import SimpleNamespace

from config.settings import ChannelConfig


ROOT = Path(__file__).resolve().parents[1]


def test_negative_channel_ids_are_preserved():
    config = ChannelConfig(channels="-1001234567890,123")
    assert config.get_channel_list() == [-1001234567890, 123]


def test_dependency_manifests_use_same_pinned_wzgram_commit():
    expected_commit = "1b3dd187c448d6d9daca0a2d3b131ad1323fcb8e"
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert any("wzgram" in dependency and expected_commit in dependency for dependency in dependencies)
    assert not any(dependency.lower() == "pyrofork" for dependency in dependencies)
    assert expected_commit in requirements


def test_published_filter_commands_have_registered_aliases():
    source = (ROOT / "handlers" / "filter.py").read_text(encoding="utf-8")
    assert '["del", "delf", "deletef"]' in source
    assert '["delall", "delallf", "deleteallf"]' in source


def test_healthchecks_probe_the_http_endpoint():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "sys.exit(0)" not in compose
    assert "curl --fail" in compose
    assert "curl --fail" in dockerfile


def test_test_files_are_not_ignored():
    ignore_rules = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "*test*.py" not in ignore_rules


def test_application_rate_limiter_does_not_collide_with_wzgram(monkeypatch):
    from bot import MediaSearchBot
    from pyrogram import Client

    wzgram_transport_limiter = object()

    def fake_client_init(self, **_kwargs):
        self.rate_limiter = wzgram_transport_limiter

    monkeypatch.setattr(Client, "__init__", fake_client_init)

    app_limiter = SimpleNamespace(check_rate_limit=object(), reset_rate_limit=object())
    config = SimpleNamespace(
        SESSION="test",
        API_ID=1,
        API_HASH="test",
        BOT_TOKEN="123:test",
        WORKERS=1,
    )
    bot = MediaSearchBot(
        config=config,
        db_pool=object(),
        cache_manager=object(),
        rate_limiter=app_limiter,
    )

    assert bot.rate_limiter is wzgram_transport_limiter
    assert bot.app_rate_limiter is app_limiter


def test_handlers_use_application_rate_limiter_namespace():
    search_source = (ROOT / "handlers" / "search.py").read_text(encoding="utf-8")
    admin_source = (
        ROOT / "handlers" / "commands_handlers" / "admin.py"
    ).read_text(encoding="utf-8")

    assert "self.bot.rate_limiter" not in search_source
    assert "self.bot.rate_limiter" not in admin_source
    assert "self.bot.app_rate_limiter" in search_source
    assert "self.bot.app_rate_limiter" in admin_source
