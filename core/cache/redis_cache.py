import asyncio
import json
import sys
from enum import Enum
from typing import Optional, Any, Union, List
import redis.asyncio as aioredis
from datetime import timedelta, datetime
import pickle

from core.cache.config import CacheTTLConfig, CacheKeyGenerator
from core.utils.logger import get_logger

logger = get_logger(__name__)

class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles datetime objects"""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, Enum):
            return obj.value
        return super().default(obj)

class CacheManager:
    """Redis cache manager with automatic serialization/deserialization"""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self.redis: Optional[aioredis.Redis] = None
        self._lock = asyncio.Lock()
        self._max_connections = 40 if 'uvloop' in sys.modules else 20
        self.ttl_config = CacheTTLConfig()  # Add this
        self.key_gen = CacheKeyGenerator()  # Add this

    async def initialize(self) -> None:
        """Initialize Redis connection"""
        import sys
        async with self._lock:
            if self.redis is None:
                self.redis = aioredis.from_url(
                    self.redis_url,
                    decode_responses=False,
                    max_connections=self._max_connections,
                    # Remove socket_keepalive options entirely as they're causing issues
                )

                # Test connection
                await self.redis.ping()
                if 'uvloop' in sys.modules:
                    logger.info(
                        f"Redis initialized with uvloop optimizations (max connections: {self._max_connections})")
                else:
                    logger.info(f"Redis initialized with standard asyncio (max connections: {self._max_connections})")

    async def close(self) -> None:
        """Close Redis connection"""
        if self.redis:
            await self.redis.close()
            self.redis = None
            logger.info("Redis connection closed")

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        if not self.redis:
            return None

        try:
            value = await self.redis.get(key)
            if value:
                # Try to deserialize as JSON first, then pickle
                try:
                    return json.loads(value.decode('utf-8'))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    try:
                        return pickle.loads(value)
                    except:
                        return value.decode('utf-8')
        except Exception as e:
            logger.error(f"Cache get error for key {key}: {e}")
            return None

    async def set(
            self,
            key: str,
            value: Any,
            expire: Optional[Union[int, timedelta]] = None
    ) -> bool:
        """Set value in cache with optional expiration"""
        if not self.redis:
            return False

        try:
            # Serialize value
            if isinstance(value, (dict, list)):
                # Use custom encoder for datetime serialization
                serialized = json.dumps(value, cls=DateTimeEncoder).encode('utf-8')
            else:
                serialized = pickle.dumps(value)

            # Convert timedelta to seconds
            if isinstance(expire, timedelta):
                expire = int(expire.total_seconds())

            # Set with expiration if provided
            if expire:
                await self.redis.setex(key, expire, serialized)
            else:
                await self.redis.set(key, serialized)
            return True
        except Exception as e:
            logger.error(f"Cache set error for key {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete key from cache"""
        if not self.redis:
            return False

        try:
            await self.redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Cache delete error for key {key}: {e}")
            return False

    async def exists(self, key: str) -> bool:
        """Check if key exists in cache"""
        if not self.redis:
            return False

        try:
            return bool(await self.redis.exists(key))
        except Exception as e:
            logger.error(f"Cache exists error for key {key}: {e}")
            return False

    async def mget(self, keys: List[str]) -> List[Optional[Any]]:
        """Get multiple values from cache"""
        if not self.redis:
            return [None] * len(keys)

        try:
            values = await self.redis.mget(keys)
            results = []
            for value in values:
                if value:
                    try:
                        results.append(json.loads(value.decode('utf-8')))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        try:
                            results.append(pickle.loads(value))
                        except:
                            results.append(value.decode('utf-8'))
                else:
                    results.append(None)
            return results
        except Exception as e:
            logger.error(f"Cache mget error: {e}")
            return [None] * len(keys)

    async def increment(self, key: str, amount: int = 1) -> Optional[int]:
        """Increment a counter in cache"""
        if not self.redis:
            return None

        try:
            return await self.redis.incrby(key, amount)
        except Exception as e:
            logger.error(f"Cache increment error for key {key}: {e}")
            return None

    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiration time for a key"""
        if not self.redis:
            return False

        try:
            return await self.redis.expire(key, seconds)
        except Exception as e:
            logger.error(f"Cache expire error for key {key}: {e}")
            return False

    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern"""
        if not self.redis:
            return 0

        try:
            deleted = 0
            async for key in self.redis.scan_iter(match=pattern):
                await self.redis.delete(key)
                deleted += 1
            return deleted
        except Exception as e:
            logger.error(f"Error deleting pattern {pattern}: {e}")
            return 0