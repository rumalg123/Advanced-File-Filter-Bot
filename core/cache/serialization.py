"""Redis cache serializer.

The legacy cache wire format (j/m/cj/cm) is retained. Old pickle cache
entries (p/cp and unprefixed binary pickle) are NEVER executed. Old safe
JSON/MessagePack and plain-text cache values can still be read.
"""
import json
import zlib
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Dict

import msgpack
from core.utils.logger import get_logger

logger = get_logger(__name__)


class SerializationMethod(Enum):
    JSON = "json"
    PICKLE = "pickle"  # Legacy hint only; maps to MessagePack
    MSGPACK = "msgpack"
    COMPRESSED_JSON = "compressed_json"
    COMPRESSED_PICKLE = "compressed_pickle"  # Legacy hint only
    COMPRESSED_MSGPACK = "compressed_msgpack"


class OptimizedSerializer:
    """Backward-compatible cache wire format, without executable codecs."""

    COMPRESSION_THRESHOLD = 1024
    MAX_ENCODED_BYTES = 16 * 1024 * 1024
    MAX_DECODED_BYTES = 32 * 1024 * 1024
    PICKLE_DISABLED = True  # Historical public flag; pickle is now unconditional.
    METHOD_PREFERENCES = {
        dict: SerializationMethod.MSGPACK,
        list: SerializationMethod.MSGPACK,
        str: SerializationMethod.JSON,
        int: SerializationMethod.JSON,
        float: SerializationMethod.JSON,
        bool: SerializationMethod.JSON,
        type(None): SerializationMethod.JSON,
    }

    def __init__(self, compression_level: int = 6):
        self.compression_level = compression_level
        self._stats = {
            "serializations": 0, "compressions": 0,
            "bytes_saved": 0, "method_usage": {},
            "rejected_unsafe": 0, "rejected_invalid": 0,
        }

    def get_stats(self) -> Dict[str, Any]:
        return {**self._stats, "method_usage": dict(self._stats["method_usage"])}

    def _choose_method(self, data: Any,
                       hint: Optional[SerializationMethod] = None) -> SerializationMethod:
        if hint == SerializationMethod.PICKLE:
            return SerializationMethod.MSGPACK
        if hint == SerializationMethod.COMPRESSED_PICKLE:
            return SerializationMethod.COMPRESSED_MSGPACK
        if hint is not None:
            if not isinstance(hint, SerializationMethod):
                raise TypeError("Unknown serialization method hint")
            return hint
        return self.METHOD_PREFERENCES.get(type(data), SerializationMethod.MSGPACK)

    def _serialize_json(self, data: Any) -> bytes:
        def encode(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            if isinstance(obj, Enum):
                return obj.value
            raise TypeError("Unsupported cache JSON value")
        return json.dumps(
            data, default=encode, separators=(",", ":")
        ).encode("utf-8")

    def _serialize_msgpack(self, data: Any) -> bytes:
        def encode(obj):
            if isinstance(obj, datetime):
                return {"__datetime__": obj.isoformat()}
            if isinstance(obj, Enum):
                return obj.value
            raise TypeError("Unsupported cache MessagePack value")
        return msgpack.packb(data, default=encode, use_bin_type=True)

    def _serialize_pickle(self, data: Any) -> bytes:
        raise TypeError("Pickle is permanently disabled for cache serialization")

    def serialize(self, data: Any,
                  method_hint: Optional[SerializationMethod] = None) -> bytes:
        try:
            method = self._choose_method(data, method_hint)
            is_json = method in (
                SerializationMethod.JSON, SerializationMethod.COMPRESSED_JSON
            )
            raw = self._serialize_json(data) if is_json else self._serialize_msgpack(data)
            if len(raw) > self.MAX_DECODED_BYTES:
                raise ValueError("Decoded cache payload exceeds limit")
            prefix = b"j" if is_json else b"m"
            wants_compression = (
                method in (SerializationMethod.COMPRESSED_JSON,
                           SerializationMethod.COMPRESSED_MSGPACK)
                or len(raw) >= self.COMPRESSION_THRESHOLD
            )
            result = prefix + raw
            if wants_compression:
                compressed = zlib.compress(raw, self.compression_level)
                if len(compressed) < len(raw) * 0.9:
                    result = b"c" + prefix + compressed
                    self._stats["compressions"] += 1
                    self._stats["bytes_saved"] += len(raw) - len(result)
            if len(result) > self.MAX_ENCODED_BYTES:
                raise ValueError("Encoded cache payload exceeds limit")
            self._stats["serializations"] += 1
            name = method.value
            methods = self._stats["method_usage"]
            methods[name] = methods.get(name, 0) + 1
            return result
        except Exception as exc:
            logger.warning("Refused cache value that cannot be encoded safely")
            raise TypeError("Cache value is not safely serializable") from exc

    def _deserialize_json(self, data: bytes) -> Any:
        return json.loads(data.decode("utf-8"))

    def _deserialize_msgpack(self, data: bytes) -> Any:
        def hook(obj):
            if isinstance(obj, dict) and "__datetime__" in obj:
                return datetime.fromisoformat(obj["__datetime__"])
            return obj
        return msgpack.unpackb(
            data, object_hook=hook, raw=False,
            max_buffer_size=self.MAX_DECODED_BYTES,
        )

    def _deserialize_pickle(self, data: bytes) -> Any:
        """Legacy API, deliberately fails closed instead of calling pickle."""
        self._stats["rejected_unsafe"] += 1
        logger.warning("Ignored unsafe legacy pickle Redis cache entry")
        return None

    def _safe_decompress(self, data: bytes) -> bytes:
        inflater = zlib.decompressobj()
        raw = inflater.decompress(data, self.MAX_DECODED_BYTES + 1)
        if (len(raw) > self.MAX_DECODED_BYTES or inflater.unconsumed_tail
                or not inflater.eof or inflater.unused_data):
            raise ValueError("Invalid or oversized compressed Redis cache value")
        remaining = self.MAX_DECODED_BYTES + 1 - len(raw)
        tail = inflater.flush(remaining)
        if len(raw) + len(tail) > self.MAX_DECODED_BYTES:
            raise ValueError("Inflated Redis cache value exceeds limit")
        return raw + tail

    def deserialize(self, data: bytes) -> Any:
        """Return cache miss for unsafe/corrupt values, never execute pickle."""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            return None
        data = bytes(data)
        if not data:
            return None
        if len(data) > self.MAX_ENCODED_BYTES:
            self._stats["rejected_invalid"] += 1
            return None

        # Historic wire tags. Pickled values are intentionally not migrated
        # on a live Redis read. Existing keys are not deleted or overwritten.
        if data[:1] == b"p" or data[:2] == b"cp":
            return self._deserialize_pickle(data)

        try:
            if data[:2] in (b"cj", b"cm"):
                inflated = self._safe_decompress(data[2:])
                if data[:2] == b"cj":
                    return self._deserialize_json(inflated)
                return self._deserialize_msgpack(inflated)
            if data[:1] == b"j":
                try:
                    return self._deserialize_json(data[1:])
                except (ValueError, UnicodeError, TypeError):
                    return self._deserialize_legacy_data(data)
            if data[:1] == b"m":
                try:
                    return self._deserialize_msgpack(data[1:])
                except Exception:
                    return self._deserialize_legacy_data(data)
            return self._deserialize_legacy_data(data)
        except Exception:
            self._stats["rejected_invalid"] += 1
            logger.warning("Ignored malformed Redis cache entry")
            return None

    def _deserialize_legacy_data(self, data: bytes) -> Any:
        """Safely decode unprefixed JSON/MessagePack/UTF-8, not pickle."""
        if len(data) > self.MAX_ENCODED_BYTES:
            return None
        try:
            return self._deserialize_json(data)
        except (ValueError, UnicodeError, TypeError):
            pass
        try:
            return self._deserialize_msgpack(data)
        except Exception:
            pass
        try:
            # ASCII pickle bytecode stays inert text if it reaches here.
            return data.decode("utf-8")
        except UnicodeError:
            return None

    def estimate_memory_usage(self, data: Any) -> Dict[str, int]:
        """Estimate safe codecs only. Never invoke pickle for measurements."""
        estimates = {}
        for name, encoder in (
            ("json", self._serialize_json),
            ("msgpack", self._serialize_msgpack),
        ):
            try:
                encoded = encoder(data)
                estimates[name] = len(encoded)
                estimates[f"compressed_{name}"] = len(
                    zlib.compress(encoded, self.compression_level)
                )
            except (TypeError, ValueError):
                continue
        return estimates


_serializer = OptimizedSerializer()


def serialize(data: Any, method_hint: Optional[SerializationMethod] = None) -> bytes:
    return _serializer.serialize(data, method_hint)


def deserialize(data: bytes) -> Any:
    return _serializer.deserialize(data)


def get_serialization_stats() -> Dict[str, Any]:
    return _serializer.get_stats()


def estimate_memory_usage(data: Any) -> Dict[str, int]:
    return _serializer.estimate_memory_usage(data)
