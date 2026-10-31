"""PH-009: unsafe pickle must never execute through any Redis cache API."""
import json
import pickle
import zlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import msgpack
import pytest

from core.cache.serialization import (
    OptimizedSerializer, SerializationMethod, deserialize, serialize
)
from core.cache.redis_cache import CacheManager


class DangerousObject:
    def __reduce__(self):
        # This callable must never be invoked by the application.
        return (eval, ("__import__('builtins').__dict__.__setitem__('PH009_EXECUTED', True)",))


def test_malicious_pickle_never_executes_for_any_legacy_prefix(monkeypatch):
    import builtins
    if hasattr(builtins, "PH009_EXECUTED"):
        delattr(builtins, "PH009_EXECUTED")

    malicious = pickle.dumps(DangerousObject(), protocol=4)
    serializer = OptimizedSerializer()
    for raw in (
        malicious, b"p" + malicious,
        b"cp" + zlib.compress(malicious),
        b"p" + pickle.dumps({"safe": True}),
    ):
        assert serializer.deserialize(raw) is None
        assert not hasattr(builtins, "PH009_EXECUTED")
    # The original ASCII pickle protocol is also rejected, without
    # converting its opcodes to inert-but-confusing session text.
    protocol_zero = pickle.dumps(DangerousObject(), protocol=0)
    assert serializer.deserialize(protocol_zero) is None
    assert not hasattr(builtins, "PH009_EXECUTED")
    assert serializer.get_stats()["rejected_unsafe"] >= 4


def test_no_runtime_pickle_load_path_or_pickle_import():
    source = (Path(__file__).parents[1] / "core/cache/serialization.py").read_text()
    assert "import pickle" not in source
    assert "pickle.loads(" not in source
    assert "pickle.load(" not in source
    assert "pickle.dumps(" not in source


def test_all_legacy_safe_wire_formats_remain_readable():
    serializer = OptimizedSerializer()
    values = [
        {"number": 3, "name": "Doctor X"},
        ["s01e03", 540],
        None,
        "doctor x",
        True,
        0,
    ]
    for value in values:
        for hint in (
            SerializationMethod.JSON, SerializationMethod.MSGPACK,
            SerializationMethod.COMPRESSED_JSON,
            SerializationMethod.COMPRESSED_MSGPACK,
        ):
            encoded = serializer.serialize(value, hint)
            assert serializer.deserialize(encoded) == value

    raw = {"legacy": ["doctor", "x"], "number": 3}
    assert serializer.deserialize(json.dumps(raw).encode()) == raw
    assert serializer.deserialize(msgpack.packb(raw, use_bin_type=True)) == raw
    assert serializer.deserialize(b"hello from legacy cache") == "hello from legacy cache"
    assert serializer.deserialize(b"caption.") == "caption."


def test_existing_prefix_and_compression_contract_unchanged():
    serializer = OptimizedSerializer()
    payload = {"files": ["Doctor X Mafia " * 50] * 20}
    assert serializer.serialize(payload, SerializationMethod.COMPRESSED_JSON).startswith(b"cj")
    assert serializer.serialize(payload, SerializationMethod.COMPRESSED_MSGPACK).startswith(b"cm")
    assert serializer.deserialize(serializer.serialize(payload)) == payload


def test_pickle_hints_cannot_reenable_executable_serialization():
    serializer = OptimizedSerializer()
    serializer.PICKLE_DISABLED = False  # Legacy toggle no longer controls safety.
    payload = {"token": "abc"}
    for hint in (SerializationMethod.PICKLE, SerializationMethod.COMPRESSED_PICKLE):
        encoded = serializer.serialize(payload, hint)
        assert encoded[:1] != b"p" and encoded[:2] != b"cp"
        assert serializer.deserialize(encoded) == payload

    with pytest.raises(TypeError, match="disabled"):
        serializer._serialize_pickle(payload)
    assert "pickle" not in serializer.estimate_memory_usage(payload)


def test_malformed_compressed_and_oversized_cache_payloads_fail_closed():
    serializer = OptimizedSerializer()
    compressed_bomb = zlib.compress(b"Z" * (serializer.MAX_DECODED_BYTES + 64), 9)
    for unsafe in (
        b"cj" + compressed_bomb,
        b"cm" + compressed_bomb,
        b"cj" + zlib.compress(b'{"incomplete":true}')[:-2],
        b"cm" + b"\xff" * 50,
        b"j" + b"x" * (serializer.MAX_ENCODED_BYTES + 1),
    ):
        assert serializer.deserialize(unsafe) is None


def test_safe_value_roundtrip_with_legacy_datetime_and_unsupported_value():
    now = datetime(2026, 10, 28, 20, tzinfo=UTC)
    serializer = OptimizedSerializer()
    value = {"timestamp": now}
    assert serializer.deserialize(serializer.serialize(value)) == value
    assert serializer.deserialize(
        serializer.serialize(value, SerializationMethod.JSON)
    ) == {"timestamp": now.isoformat()}
    with pytest.raises(TypeError):
        serialize({"set": {1, 2, 3}})


@pytest.mark.asyncio
async def test_cache_manager_treats_pickle_as_miss_without_overwriting_key():
    legacy = b"p" + pickle.dumps({"permission": "admin"}, protocol=4)
    redis = SimpleNamespace(
        get=AsyncMock(return_value=legacy),
        set=AsyncMock(), setex=AsyncMock(), delete=AsyncMock(),
    )
    manager = CacheManager("redis://unused")
    manager.redis = redis
    assert await manager.get("session:legacy:42") is None
    redis.delete.assert_not_awaited()
    redis.set.assert_not_awaited()
    redis.setex.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_manager_mget_mixed_safe_and_pickle_keeps_order():
    safe = serialize({"name": "Doctor X"})
    old = b"cp" + zlib.compress(pickle.dumps({"unsafe": True}))
    redis = SimpleNamespace(mget=AsyncMock(return_value=[safe, old, None, safe]))
    manager = CacheManager("redis://unused")
    manager.redis = redis
    assert await manager.mget(["a", "b", "c", "d"]) == [
        {"name": "Doctor X"}, None, None, {"name": "Doctor X"}
    ]


def test_serialization_statistics_have_no_sensitive_payloads():
    serializer = OptimizedSerializer()
    serializer.serialize({"bot_token": "secret-token"})
    serializer.deserialize(b"p" + pickle.dumps({"bot_token": "secret-token"}))
    stats = serializer.get_stats()
    assert "secret-token" not in json.dumps(stats)
    assert stats["rejected_unsafe"] == 1
