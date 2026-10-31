"""PH-010 opt-in Redis ACL file authentication and secret safety tests."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.cache.auth import redis_auth_kwargs
from core.cache.redis_cache import CacheManager
from scripts.generate_redis_acl import generate


def test_existing_redis_url_uses_no_new_auth_defaults():
    assert redis_auth_kwargs("redis://redis:6379/0") == {}
    assert redis_auth_kwargs("rediss://example.invalid:6379/1") == {}
    assert redis_auth_kwargs("redis://user:pass@redis:6379/0") == {}


def test_password_file_auth_reads_secret_without_exposing_in_repr(tmp_path):
    path = tmp_path / "redis_password"
    secret = "strong-test-credential-only-in-file-123456789"
    path.write_text(secret + "\n")
    result = redis_auth_kwargs(
        "redis://redis:6379/0", username="filebot",
        password_file=str(path),
    )
    assert result == {"password": secret, "username": "filebot"}
    assert secret not in repr(path)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"username": "filebot"},
        {"username": "filebot", "password_file": "relative/path"},
        {"username": "filebot", "password_file": "/missing/ph010/credential"},
    ],
)
def test_bad_credentials_fail_closed_without_secret_in_errors(kwargs):
    with pytest.raises(ValueError):
        redis_auth_kwargs("redis://redis:6379/0", **kwargs)


def test_reject_duplicate_uri_password_and_secret_file(tmp_path):
    path = tmp_path / "secret"
    path.write_text("a very long credential string abcdefghijklmnopqrst")
    with pytest.raises(ValueError, match="cannot be mixed"):
        redis_auth_kwargs(
            "redis://user:embedded-password@redis:6379/0",
            username="filebot", password_file=str(path),
        )


@pytest.mark.parametrize("password", ["", "short", "a" * 4097, "long\nembedded\nnewline12345"])
def test_reject_weak_oversized_or_multiline_secret(tmp_path, password):
    path = tmp_path / "secret"
    path.write_text(password)
    with pytest.raises(ValueError):
        redis_auth_kwargs(
            "redis://redis:6379", username="filebot",
            password_file=str(path),
        )


def test_generator_creates_independent_non_overwriting_acl_files(tmp_path):
    folder = tmp_path / "secrets"
    names = generate(folder)
    assert len(names) == 4
    assert folder.stat().st_mode & 0o777 == 0o700
    cache_secret = (folder / "redis-cache.password").read_text().strip()
    state_secret = (folder / "redis-state.password").read_text().strip()
    assert len(cache_secret) >= 32
    assert len(state_secret) >= 32
    assert cache_secret != state_secret
    for prefix, secret in (("redis-cache", cache_secret), ("redis-state", state_secret)):
        acl = (folder / f"{prefix}.acl").read_text()
        assert "user default off\n" in acl
        assert f"user filebot on >{secret} ~* &* +@all -@dangerous\n" in acl
        assert redis_auth_kwargs(
            "redis://redis:6379", username="filebot",
            password_file=str(folder / f"{prefix}.password")
        )["password"] == secret
    with pytest.raises(FileExistsError):
        generate(folder)


@pytest.mark.asyncio
async def test_cache_manager_passes_file_credentials_to_redis_client(monkeypatch, tmp_path):
    secret = "filebasedstrongpasswordwhichisneverlogged123"
    path = tmp_path / "secret"
    path.write_text(secret + "\n")
    created = {}
    client = SimpleNamespace(ping=AsyncMock(return_value=True), aclose=AsyncMock())

    def fake_from_url(url, **kwargs):
        created["uri"] = url
        created["kwargs"] = kwargs
        return client

    monkeypatch.setattr("core.cache.redis_cache.aioredis.from_url", fake_from_url)
    cache = CacheManager(
        "redis://cache:6379/0", username="filebot",
        password_file=str(path),
    )
    await cache.initialize()
    assert created["kwargs"]["username"] == "filebot"
    assert created["kwargs"]["password"] == secret
    assert created["uri"] == "redis://cache:6379/0"
    assert cache.redis is client


@pytest.mark.asyncio
async def test_authentication_error_does_not_publish_failed_connection(monkeypatch, tmp_path):
    path = tmp_path / "password"
    path.write_text("an-invalid-but-long-passphrase-for-testing")
    client = SimpleNamespace(
        ping=AsyncMock(side_effect=PermissionError("NOAUTH")),
        aclose=AsyncMock(),
    )
    monkeypatch.setattr(
        "core.cache.redis_cache.aioredis.from_url",
        lambda *_a, **_kw: client,
    )
    cache = CacheManager(
        "redis://cache:6379/0", username="filebot",
        password_file=str(path)
    )
    with pytest.raises(PermissionError, match="NOAUTH"):
        await cache.initialize()
    client.aclose.assert_awaited_once()
    assert cache.redis is None


def test_auth_overlay_has_no_public_redis_ports_or_plain_password_values():
    base = Path(__file__).parents[1]
    overlay = (base / "docker-compose.redis-auth.yml").read_text()
    assert "redis_cache_password" in overlay
    assert "redis_state_password" in overlay
    assert "--aclfile" in overlay
    assert "password=" not in overlay.lower()
    assert "ports:" not in overlay
    assert (base / ".gitignore").read_text().find(".secrets/") >= 0
