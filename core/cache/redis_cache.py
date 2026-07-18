import asyncio
import sys
from typing import Optional, Any, Union, List, Callable
from functools import wraps
import redis.asyncio as aioredis
from datetime import UTC, datetime, timedelta

from core.cache.config import CacheTTLConfig, CacheKeyGenerator
from core.cache.serialization import serialize, deserialize, get_serialization_stats
from core.utils.logger import get_logger

logger = get_logger(__name__)

class CacheManager:
    """Redis cache manager with automatic serialization/deserialization"""

    _INCREMENT_WITH_EXPIRY_SCRIPT = """
    local count = redis.call('INCRBY', KEYS[1], ARGV[1])
    local ttl = redis.call('TTL', KEYS[1])
    if ttl < 0 then
        redis.call('EXPIRE', KEYS[1], ARGV[2])
    end
    return count
    """

    _DELETE_IF_VALUE_SCRIPT = """
    if redis.call('GET', KEYS[1]) == ARGV[1] then
        return redis.call('DEL', KEYS[1])
    end
    return 0
    """

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self.redis: Optional[aioredis.Redis] = None
        self._lock = asyncio.Lock()
        self._max_connections = 40 if 'uvloop' in sys.modules else 20
        self.ttl_config = CacheTTLConfig()  # Add this
        self.key_gen = CacheKeyGenerator()  # Add this

    async def initialize(self) -> None:
        """Initialize Redis connection"""
        async with self._lock:
            if self.redis is None:
                client = aioredis.from_url(
                    self.redis_url,
                    decode_responses=False,
                    max_connections=self._max_connections,
                    socket_timeout=30.0,  # Timeout for socket operations
                    socket_connect_timeout=10.0,  # Timeout for initial connection
                )

                try:
                    # Do not publish a client until its initial connection is
                    # known to work. This keeps a retry from seeing a partial
                    # initialization as a healthy manager.
                    await client.ping()
                except Exception:
                    try:
                        await client.aclose()
                    except Exception as close_error:
                        logger.debug(f"Error closing failed Redis client: {close_error}")
                    self.redis = None
                    raise

                self.redis = client
                if 'uvloop' in sys.modules:
                    logger.info(
                        f"Redis initialized with uvloop optimizations (max connections: {self._max_connections})")
                else:
                    logger.info(f"Redis initialized with standard asyncio (max connections: {self._max_connections})")

    async def close(self) -> None:
        """Close Redis connection properly"""
        if self.redis:
            client = self.redis
            self.redis = None
            try:
                await client.aclose()
                # Safely disconnect connection pool
                try:
                    await client.connection_pool.disconnect()
                except Exception as pool_error:
                    logger.warning(f"Error disconnecting connection pool: {pool_error}")
            except Exception as e:
                logger.error(f"Error closing Redis connection: {e}")
            finally:
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
            if expire is not None:
                expire = int(expire)
                if expire <= 0:
                    logger.warning(f"Refusing cache write with non-positive TTL for key {key}")
                    return False
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
        if not keys:
            return []
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

    async def increment_with_expiry(
            self,
            key: str,
            amount: int,
            seconds: int
    ) -> Optional[int]:
        """Atomically increment a raw Redis counter and ensure it has a TTL."""
        if not self.redis:
            return None
        if seconds <= 0:
            logger.warning(f"Refusing counter increment with non-positive TTL for key {key}")
            return None

        try:
            return int(await self.redis.eval(
                self._INCREMENT_WITH_EXPIRY_SCRIPT,
                1,
                key,
                amount,
                seconds
            ))
        except Exception as e:
            logger.error(f"Atomic cache increment error for key {key}: {e}")
            return None

    async def delete_if_value(self, key: str, expected_value: Any) -> bool:
        """Atomically delete a serialized key only if it still has an expected value."""
        if not self.redis:
            return False

        try:
            expected = serialize(expected_value)
            deleted = await self.redis.eval(
                self._DELETE_IF_VALUE_SCRIPT,
                1,
                key,
                expected
            )
            return bool(deleted)
        except Exception as e:
            logger.error(f"Conditional cache delete error for key {key}: {e}")
            return False

    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiration time for a key"""
        if not self.redis:
            return False
        if seconds <= 0:
            logger.warning(f"Refusing non-positive expiration for key {key}")
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
            return -1

        try:
            deleted = 0
            failed = 0
            batch_size = 100

            # Stream scan results into bounded batches. Repeat a small number
            # of passes because Redis SCAN may move while keys are deleted.
            for _ in range(3):
                matched = 0
                batch = []
                async for key in self.redis.scan_iter(match=pattern, count=batch_size):
                    matched += 1
                    batch.append(key)
                    if len(batch) < batch_size:
                        continue

                    try:
                        deleted += await self.redis.delete(*batch)
                    except Exception as batch_error:
                        failed += len(batch)
                        logger.warning(f"Failed to delete batch of {len(batch)} keys: {batch_error}")
                    batch = []

                try:
                    if batch:
                        deleted += await self.redis.delete(*batch)
                except Exception as batch_error:
                    failed += len(batch)
                    logger.warning(f"Failed to delete batch of {len(batch)} keys: {batch_error}")

                if matched == 0:
                    break
            
            if failed > 0:
                logger.warning(f"Pattern {pattern}: {deleted} deleted, {failed} failed")
            
            return deleted
        except Exception as e:
            logger.error(f"Error deleting pattern {pattern}: {e}")
            return -1

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

    async def zadd(self, key: str, score: float, member: str) -> bool:
        """Add member to sorted set with score"""
        if not self.redis:
            return False
        
        try:
            await self.redis.zadd(key, {member: score})
            return True
        except Exception as e:
            logger.error(f"Cache zadd error for key {key}: {e}")
            return False

    async def zincrby(self, key: str, amount: float, member: str) -> Optional[float]:
        """Increment score of member in sorted set"""
        if not self.redis:
            return None
        
        try:
            return await self.redis.zincrby(key, amount, member)
        except Exception as e:
            logger.error(f"Cache zincrby error for key {key}: {e}")
            return None

    async def zrevrange(self, key: str, start: int = 0, end: int = -1, with_scores: bool = False) -> List:
        """Get members from sorted set in reverse order (highest score first)"""
        if not self.redis:
            return []
        
        try:
            # Redis uses 'withscores' (no underscore) as parameter name
            return await self.redis.zrevrange(key, start, end, withscores=with_scores)
        except Exception as e:
            logger.error(f"Cache zrevrange error for key {key}: {e}")
            return []


def cache_premium_status(ttl: int = 600) -> Callable:
    """
    Cache premium status check results using Redis.

    Decorator for repository methods that check premium status.
    Expects the decorated method to have signature: (self, user) where user has an 'id' attribute.
    Uses self.cache (CacheManager instance) for caching.

    Args:
        ttl: Cache time-to-live in seconds (default 10 minutes)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self, user, *args, **kwargs) -> Any:
            # Get user_id for cache key
            user_id = getattr(user, 'id', None)
            if user_id is None:
                # Can't cache without user ID, just call the function
                return await func(self, user, *args, **kwargs)

            cache_key = CacheKeyGenerator.premium_status(user_id)

            # Try to get from cache
            try:
                if hasattr(self, 'cache') and self.cache:
                    cached_result = await self.cache.get(cache_key)
                    if cached_result is not None:
                        # MessagePack represents tuples as arrays. Restore the
                        # decorated method's tuple contract on cache hits.
                        return tuple(cached_result) if isinstance(cached_result, list) else cached_result
            except Exception as e:
                logger.warning(f"Cache get error for premium status: {e}")

            # Call original function
            result = await func(self, user, *args, **kwargs)

            # Cache the result, but never cache a positive premium decision
            # beyond the subscription's actual expiry time.
            try:
                if hasattr(self, 'cache') and self.cache:
                    cache_ttl = ttl
                    is_premium = bool(result[0]) if isinstance(result, (tuple, list)) and result else False
                    expiry = getattr(user, 'premium_expiry_date', None)
                    if is_premium and expiry:
                        if expiry.tzinfo is None:
                            expiry = expiry.replace(tzinfo=UTC)
                        remaining = int((expiry - datetime.now(UTC)).total_seconds())
                        if remaining <= 0:
                            return result
                        cache_ttl = min(cache_ttl, remaining)
                    await self.cache.set(cache_key, result, expire=cache_ttl)
            except Exception as e:
                logger.warning(f"Cache set error for premium status: {e}")

            return result

        return wrapper
    return decorator
