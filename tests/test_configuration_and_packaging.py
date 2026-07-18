import tomllib
from pathlib import Path

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
