import asyncio
import sys
from typing import Optional, Any, Union, List
import redis.asyncio as aioredis
from datetime import timedelta

from core.cache.config import CacheTTLConfig, CacheKeyGenerator
from core.cache.serialization import serialize, deserialize, get_serialization_stats
from core.utils.logger import get_logger

logger = get_logger(__name__)

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
        """Close Redis connection properly"""
        if self.redis:
            try:
                await self.redis.close()
                # Safely disconnect connection pool
                try:
                    await self.redis.connection_pool.disconnect()
                except Exception as pool_error:
                    logger.warning(f"Error disconnecting connection pool: {pool_error}")
            except Exception as e:
                logger.error(f"Error closing Redis connection: {e}")
            finally:
                self.redis = None
                logger.info("Redis connection closed")

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache with optimized deserialization"""
        if not self.redis:
            return None

        try:
            value = await self.redis.get(key)
            if value:
                return deserialize(value)
            return None
        except Exception as e:
            logger.error(f"Cache get error for key {key}: {e}")
            return None

    async def set(
            self,
            key: str,
            value: Any,
            expire: Optional[Union[int, timedelta]] = None
    ) -> bool:
        """Set value in cache with optimized serialization"""
        if not self.redis:
            return False

        try:
            # Use optimized serialization
            serialized = serialize(value)

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
        """Get multiple values from cache with optimized deserialization"""
        if not self.redis:
            return [None] * len(keys)

        try:
            values = await self.redis.mget(keys)
            results = []
            for value in values:
                if value:
                    results.append(deserialize(value))
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

    async def ttl(self, key: str) -> int:
        """Get time to live for a key in seconds"""
        if not self.redis:
            return -1
        
        try:
            return await self.redis.ttl(key)
        except Exception as e:
            logger.error(f"Cache TTL error for key {key}: {e}")
            return -1

    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern"""
        if not self.redis:
            return 0

        try:
            deleted = 0
            failed = 0
            keys_to_delete = []
            
            # Collect all keys first
            async for key in self.redis.scan_iter(match=pattern):
                keys_to_delete.append(key)
            
            # Delete in batches for better performance
            batch_size = 100
            for i in range(0, len(keys_to_delete), batch_size):
                batch = keys_to_delete[i:i + batch_size]
                try:
                    if batch:
                        result = await self.redis.delete(*batch)
                        deleted += result
                except Exception as batch_error:
                    failed += len(batch)
                    logger.warning(f"Failed to delete batch of {len(batch)} keys: {batch_error}")
            
            if failed > 0:
                logger.warning(f"Pattern {pattern}: {deleted} deleted, {failed} failed")
            
            return deleted
        except Exception as e:
            logger.error(f"Error deleting pattern {pattern}: {e}")
            return 0

    async def get_cache_stats(self) -> dict:
        """Get comprehensive cache statistics"""
        stats = {
            'redis_info': {},
            'serialization_stats': get_serialization_stats(),
            'connection_info': {
                'is_connected': self.redis is not None,
                'max_connections': self._max_connections
            }
        }
        
        if self.redis:
            try:
                # Get Redis info
                redis_info = await self.redis.info()
                stats['redis_info'] = {
                    'used_memory': redis_info.get('used_memory', 0),
                    'used_memory_human': redis_info.get('used_memory_human', '0B'),
                    'keyspace_hits': redis_info.get('keyspace_hits', 0),
                    'keyspace_misses': redis_info.get('keyspace_misses', 0),
                    'connected_clients': redis_info.get('connected_clients', 0),
                    'total_commands_processed': redis_info.get('total_commands_processed', 0),
                    'instantaneous_ops_per_sec': redis_info.get('instantaneous_ops_per_sec', 0)
                }
                
                # Calculate hit rate
                hits = stats['redis_info']['keyspace_hits']
                misses = stats['redis_info']['keyspace_misses']
                total = hits + misses
                stats['redis_info']['hit_rate'] = (hits / total * 100) if total > 0 else 0
                
            except Exception as e:
                logger.error(f"Error getting Redis stats: {e}")
                stats['redis_info']['error'] = str(e)
        
        return stats