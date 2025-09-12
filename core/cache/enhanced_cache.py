"""
Enhanced caching utilities with LRU/TTL and metrics
"""
import asyncio
import time
from typing import Any, Dict, Optional, Callable, Tuple
from dataclasses import dataclass
from functools import wraps
from collections import OrderedDict

from core.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CacheStats:
    """Cache performance metrics"""
    hits: int = 0
    misses: int = 0
    sets: int = 0
    evictions: int = 0
    errors: int = 0
    
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate"""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/monitoring"""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "sets": self.sets,
            "evictions": self.evictions,
            "errors": self.errors,
            "hit_rate": self.hit_rate,
            "total_requests": self.hits + self.misses
        }


class LRUTTLCache:
    """LRU cache with TTL support and metrics"""
    
    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict = OrderedDict()
        self._timestamps: Dict[str, float] = {}
        self._stats = CacheStats()
        self._lock = asyncio.Lock()
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache with TTL check"""
        async with self._lock:
            current_time = time.time()
            
            # Check if key exists and hasn't expired
            if key in self._cache:
                timestamp = self._timestamps.get(key, 0)
                if current_time - timestamp < self.default_ttl:
                    # Move to end (most recently used)
                    self._cache.move_to_end(key)
                    self._stats.hits += 1
                    
                    logger.debug(f"Cache hit: {key}", extra={
                        "event": "cache_hit",
                        "key": key,
                        "hit_rate": self._stats.hit_rate
                    })
                    
                    return self._cache[key]
                else:
                    # Expired, remove it
                    del self._cache[key]
                    del self._timestamps[key]
                    self._stats.evictions += 1
            
            self._stats.misses += 1
            logger.debug(f"Cache miss: {key}", extra={
                "event": "cache_miss",
                "key": key,
                "hit_rate": self._stats.hit_rate
            })
            
            return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in cache with TTL"""
        async with self._lock:
            # Remove oldest entries if at capacity
            while len(self._cache) >= self.max_size:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                del self._timestamps[oldest_key]
                self._stats.evictions += 1
            
            self._cache[key] = value
            self._timestamps[key] = time.time()
            self._stats.sets += 1
            
            logger.debug(f"Cache set: {key}", extra={
                "event": "cache_set",
                "key": key,
                "cache_size": len(self._cache)
            })
    
    async def delete(self, key: str) -> bool:
        """Delete key from cache"""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                del self._timestamps[key]
                return True
            return False
    
    async def clear(self) -> None:
        """Clear all cache entries"""
        async with self._lock:
            self._cache.clear()
            self._timestamps.clear()
            logger.info("Cache cleared", extra={"event": "cache_clear"})
    
    def get_stats(self) -> CacheStats:
        """Get cache statistics"""
        return self._stats
    
    async def cleanup_expired(self) -> int:
        """Remove expired entries and return count removed"""
        async with self._lock:
            current_time = time.time()
            expired_keys = []
            
            for key, timestamp in self._timestamps.items():
                if current_time - timestamp >= self.default_ttl:
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self._cache[key]
                del self._timestamps[key]
                self._stats.evictions += 1
            
            if expired_keys:
                logger.info(f"Cleaned up {len(expired_keys)} expired cache entries", extra={
                    "event": "cache_cleanup",
                    "expired_count": len(expired_keys)
                })
            
            return len(expired_keys)


# Global cache instances for common use cases
user_cache = LRUTTLCache(max_size=5000, default_ttl=300)  # 5 minutes for user data
premium_cache = LRUTTLCache(max_size=2000, default_ttl=600)  # 10 minutes for premium status
channel_cache = LRUTTLCache(max_size=500, default_ttl=1800)  # 30 minutes for channel info
link_cache = LRUTTLCache(max_size=1000, default_ttl=900)  # 15 minutes for link metadata


def cached(
    cache_instance: LRUTTLCache,
    ttl: Optional[int] = None,
    key_func: Optional[Callable] = None
) -> Callable:
    """Decorator to cache function results"""
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # Generate cache key
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = f"{func.__name__}:{hash((args, tuple(sorted(kwargs.items()))))}"
            
            # Try to get from cache
            try:
                cached_result = await cache_instance.get(cache_key)
                if cached_result is not None:
                    return cached_result
            except Exception as e:
                logger.warning(f"Cache get error: {e}", extra={
                    "event": "cache_error",
                    "operation": "get",
                    "key": cache_key
                })
                cache_instance._stats.errors += 1
            
            # Call original function
            result = await func(*args, **kwargs)
            
            # Cache the result
            try:
                await cache_instance.set(cache_key, result, ttl)
            except Exception as e:
                logger.warning(f"Cache set error: {e}", extra={
                    "event": "cache_error", 
                    "operation": "set",
                    "key": cache_key
                })
                cache_instance._stats.errors += 1
            
            return result
        
        return wrapper
    return decorator


# Specific cache decorators for common use cases
def cache_user_data(ttl: int = 300) -> Callable:
    """Cache user data with default 5 minute TTL"""
    return cached(
        user_cache,
        ttl=ttl,
        key_func=lambda user_id, *args, **kwargs: f"user:{user_id}"
    )


def cache_premium_status(ttl: int = 600) -> Callable:
    """Cache premium status with default 10 minute TTL"""
    return cached(
        premium_cache,
        ttl=ttl,
        key_func=lambda user_id, *args, **kwargs: f"premium:{user_id}"
    )


def cache_channel_info(ttl: int = 1800) -> Callable:
    """Cache channel information with default 30 minute TTL"""
    return cached(
        channel_cache,
        ttl=ttl,
        key_func=lambda channel_id, *args, **kwargs: f"channel:{channel_id}"
    )


async def get_all_cache_stats() -> Dict[str, Dict[str, Any]]:
    """Get statistics from all cache instances"""
    return {
        "user_cache": user_cache.get_stats().to_dict(),
        "premium_cache": premium_cache.get_stats().to_dict(),
        "channel_cache": channel_cache.get_stats().to_dict(),
        "link_cache": link_cache.get_stats().to_dict()
    }


async def cleanup_all_caches() -> Dict[str, int]:
    """Clean up expired entries from all caches"""
    results = {}
    
    for name, cache_instance in [
        ("user_cache", user_cache),
        ("premium_cache", premium_cache),
        ("channel_cache", channel_cache),
        ("link_cache", link_cache)
    ]:
        try:
            expired_count = await cache_instance.cleanup_expired()
            results[name] = expired_count
        except Exception as e:
            logger.error(f"Error cleaning up {name}: {e}")
            results[name] = -1
    
    return results