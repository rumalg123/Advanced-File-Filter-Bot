"""
Optimized cache serialization with compression and binary formats
Reduces Redis memory usage and network overhead
"""

import json
import pickle
import zlib
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Dict

import msgpack

from core.utils.logger import get_logger

logger = get_logger(__name__)


class SerializationMethod(Enum):
    """Available serialization methods"""
    JSON = "json"
    PICKLE = "pickle"
    MSGPACK = "msgpack"
    COMPRESSED_JSON = "compressed_json"
    COMPRESSED_PICKLE = "compressed_pickle"
    COMPRESSED_MSGPACK = "compressed_msgpack"


class OptimizedSerializer:
    """Optimized serializer with compression and method selection"""
    
    # Size thresholds for compression (bytes)
    COMPRESSION_THRESHOLD = 1024  # 1KB
    
    # Method preferences based on data type
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
        """
        Initialize serializer
        compression_level: 1-9, higher = better compression but slower
        """
        self.compression_level = compression_level
        self._stats = {
            'serializations': 0,
            'compressions': 0,
            'bytes_saved': 0,
            'method_usage': {}
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get serialization statistics"""
        return self._stats.copy()
    
    def _choose_method(self, data: Any, hint: Optional[SerializationMethod] = None) -> SerializationMethod:
        """Choose optimal serialization method based on data type and size"""
        if hint:
            return hint
        
        data_type = type(data)
        return self.METHOD_PREFERENCES.get(data_type, SerializationMethod.PICKLE)
    
    def _serialize_json(self, data: Any) -> bytes:
        """Serialize using JSON with datetime support"""
        def json_encoder(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            elif isinstance(obj, Enum):
                return obj.value
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
        
        return json.dumps(data, default=json_encoder, separators=(',', ':')).encode('utf-8')
    
    def _serialize_msgpack(self, data: Any) -> bytes:
        """Serialize using MessagePack (more efficient than JSON)"""
        def msgpack_encoder(obj):
            if isinstance(obj, datetime):
                return {'__datetime__': obj.isoformat()}
            elif isinstance(obj, Enum):
                return obj.value
            return obj
        
        return msgpack.packb(data, default=msgpack_encoder, use_bin_type=True)
    
    def _serialize_pickle(self, data: Any) -> bytes:
        """Serialize using pickle (most compatible)"""
        return pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
    
    def serialize(self, data: Any, method_hint: Optional[SerializationMethod] = None) -> bytes:
        """
        Serialize data with optimal method and compression
        Returns: serialized bytes with method prefix
        """
        try:
            # Choose serialization method
            method = self._choose_method(data, method_hint)
            
            # Serialize based on method
            if method == SerializationMethod.JSON or method == SerializationMethod.COMPRESSED_JSON:
                serialized = self._serialize_json(data)
            elif method == SerializationMethod.MSGPACK or method == SerializationMethod.COMPRESSED_MSGPACK:
                serialized = self._serialize_msgpack(data)
            else:  # PICKLE or COMPRESSED_PICKLE
                serialized = self._serialize_pickle(data)
            
            original_size = len(serialized)
            
            # Apply compression if beneficial
            if (method.value.startswith('compressed') or 
                original_size >= self.COMPRESSION_THRESHOLD):
                
                compressed = zlib.compress(serialized, self.compression_level)
                
                # Only use compression if it actually saves space
                if len(compressed) < original_size * 0.9:  # At least 10% savings
                    method_prefix = f"c{method.value[:1]}".encode('ascii')  # 'cj', 'cp', 'cm'
                    result = method_prefix + compressed
                    self._stats['compressions'] += 1
                    self._stats['bytes_saved'] += original_size - len(result)
                else:
                    # Compression not beneficial
                    method_prefix = method.value[:1].encode('ascii')  # 'j', 'p', 'm'
                    result = method_prefix + serialized
            else:
                method_prefix = method.value[:1].encode('ascii')  # 'j', 'p', 'm'
                result = method_prefix + serialized
            
            # Update stats
            self._stats['serializations'] += 1
            method_name = method.value
            self._stats['method_usage'][method_name] = self._stats['method_usage'].get(method_name, 0) + 1
            
            return result
            
        except Exception as e:
            logger.error(f"Serialization failed: {e}")
            # Fallback to pickle
            fallback = b'p' + pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
            self._stats['serializations'] += 1
            return fallback
    
    def _deserialize_json(self, data: bytes) -> Any:
        """Deserialize JSON with datetime parsing"""
        return json.loads(data.decode('utf-8'))
    
    def _deserialize_msgpack(self, data: bytes) -> Any:
        """Deserialize MessagePack with datetime parsing"""
        def msgpack_decoder(obj):
            if isinstance(obj, dict) and '__datetime__' in obj:
                return datetime.fromisoformat(obj['__datetime__'])
            return obj
        
        return msgpack.unpackb(data, object_hook=msgpack_decoder, raw=False)
    
    def _deserialize_pickle(self, data: bytes) -> Any:
        """Deserialize pickle data"""
        return pickle.loads(data)
    
    def deserialize(self, data: bytes) -> Any:
        """
        Deserialize data based on method prefix with robust fallback handling
        """
        if not data or len(data) < 1:
            return None
        
        try:
            # Handle legacy data first (no method prefix)
            # If first byte is not one of our method prefixes, it's legacy data
            first_byte = data[:1]
            if first_byte not in [b'j', b'p', b'm', b'c']:
                return self._deserialize_legacy_data(data)
            
            # Extract method from prefix
            method_prefix = data[:1]
            serialized_data = data[1:]
            
            # Handle compression - check for compressed methods
            is_compressed = False
            method_char = method_prefix
            
            if method_prefix == b'c' and len(data) >= 2:
                # Compressed format - next byte is the actual method
                method_char = data[1:2]
                serialized_data = data[2:]
                is_compressed = True
            
            # Decompress if needed
            if is_compressed:
                try:
                    serialized_data = zlib.decompress(serialized_data)
                except zlib.error as e:
                    logger.warning(f"Failed to decompress data: {e}, trying legacy fallback")
                    return self._deserialize_legacy_data(data)
            
            # Deserialize based on method
            if method_char == b'j':  # JSON
                return self._deserialize_json(serialized_data)
            elif method_char == b'm':  # MessagePack
                return self._deserialize_msgpack(serialized_data)
            elif method_char == b'p':  # Pickle
                return self._deserialize_pickle(serialized_data)
            else:
                # Unknown method, try legacy fallback
                return self._deserialize_legacy_data(data)
        
        except Exception as e:
            logger.debug(f"Deserialization failed, trying legacy fallback: {e}")
            return self._deserialize_legacy_data(data)
    
    def _deserialize_legacy_data(self, data: bytes) -> Any:
        """Fallback deserialization for legacy data without method prefixes"""
        try:
            # Try JSON first (most common legacy format)
            return json.loads(data.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            try:
                # Try pickle (binary format)
                return pickle.loads(data)
            except:
                try:
                    # Try as plain string
                    return data.decode('utf-8')
                except UnicodeDecodeError:
                    # Last resort - return None for corrupted data
                    logger.warning(f"Could not deserialize data of length {len(data)}")
                    return None
    
    def estimate_memory_usage(self, data: Any) -> Dict[str, int]:
        """Estimate memory usage for different serialization methods"""
        estimates = {}
        
        try:
            # JSON
            json_size = len(self._serialize_json(data))
            estimates['json'] = json_size
            estimates['compressed_json'] = len(zlib.compress(
                self._serialize_json(data), self.compression_level
            ))
            
            # MessagePack
            msgpack_size = len(self._serialize_msgpack(data))
            estimates['msgpack'] = msgpack_size
            estimates['compressed_msgpack'] = len(zlib.compress(
                self._serialize_msgpack(data), self.compression_level
            ))
            
            # Pickle
            pickle_size = len(self._serialize_pickle(data))
            estimates['pickle'] = pickle_size
            estimates['compressed_pickle'] = len(zlib.compress(
                self._serialize_pickle(data), self.compression_level
            ))
            
        except Exception as e:
            logger.warning(f"Error estimating memory usage: {e}")
        
        return estimates


# Global serializer instance
_serializer = OptimizedSerializer()


def serialize(data: Any, method_hint: Optional[SerializationMethod] = None) -> bytes:
    """Serialize data using optimized method"""
    return _serializer.serialize(data, method_hint)


def deserialize(data: bytes) -> Any:
    """Deserialize data"""
    return _serializer.deserialize(data)


def get_serialization_stats() -> Dict[str, Any]:
    """Get serialization statistics"""
    return _serializer.get_stats()


def estimate_memory_usage(data: Any) -> Dict[str, int]:
    """Estimate memory usage for different methods"""
    return _serializer.estimate_memory_usage(data)