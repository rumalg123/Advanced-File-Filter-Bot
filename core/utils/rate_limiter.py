import asyncio
import time
from dataclasses import dataclass
from functools import wraps
from typing import Dict, Optional, Tuple

from core.cache.config import CacheTTLConfig, CacheKeyGenerator
from core.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting"""
    max_requests: int
    time_window: int  # seconds
    cooldown_time: int = 60  # seconds


class RateLimiter:
    """Token bucket rate limiter with Redis backend"""

    def __init__(self, cache_manager):
        self.cache = cache_manager
        self.ttl = CacheTTLConfig()
        self.configs: Dict[str, RateLimitConfig] = {
            'search': RateLimitConfig(max_requests=30, time_window=self.ttl.RATE_LIMIT_WINDOW),
            'file_request': RateLimitConfig(max_requests=10, time_window=60),
            'broadcast': RateLimitConfig(max_requests=1, time_window=3600),
            'inline_query': RateLimitConfig(max_requests=50, time_window=60),
            'premium_check': RateLimitConfig(max_requests=100, time_window=60),
        }

    async def check_rate_limit(
            self,
            user_id: int,
            action: str
    ) -> Tuple[bool, Optional[int]]:
        """
        Check if user has exceeded rate limit
        Returns: (is_allowed, seconds_until_reset)
        """
        config = self.configs.get(action)
        if not config:
            return True, None

        key = CacheKeyGenerator.rate_limit(user_id, action)
        cooldown_key = CacheKeyGenerator.rate_limit_cooldown(user_id, action)

        # Check if user is in cooldown
        cooldown = await self.cache.get(cooldown_key)
        if cooldown:
            return False, int(cooldown)

        # Get current count
        current_count = await self.cache.get(key) or 0

        if current_count >= config.max_requests:
            # Apply cooldown
            await self.cache.set(
                cooldown_key,
                config.cooldown_time,
                expire=config.cooldown_time
            )
            return False, config.cooldown_time

        # Increment counter and ensure expiration is always set
        new_count = await self.cache.increment(key)
        
        # Always set expiration to prevent keys without TTL
        await self.cache.expire(key, config.time_window)

        return True, None

    async def reset_rate_limit(self, user_id: int, action: str) -> None:
        """Reset rate limit for a user and action"""
        key = CacheKeyGenerator.rate_limit(user_id, action)
        cooldown_key = CacheKeyGenerator.rate_limit_cooldown(user_id, action)
        await self.cache.delete(key)
        await self.cache.delete(cooldown_key)

    def rate_limit_decorator(self, action: str):
        """Decorator for rate limiting functions"""

        def decorator(func):
            @wraps(func)
            async def wrapper(self, client, message, *args, **kwargs):
                user_id = message.from_user.id if message.from_user else None
                if not user_id:
                    return await func(self, client, message, *args, **kwargs)

                # Check rate limit
                is_allowed, cooldown = await self.rate_limiter.check_rate_limit(
                    user_id, action
                )

                if not is_allowed:
                    await message.reply_text(
                        f"⚠️ Rate limit exceeded! Please wait {cooldown} seconds before trying again."
                    )
                    return

                return await func(self, client, message, *args, **kwargs)

            return wrapper

        return decorator


class DistributedRateLimiter:
    """Distributed rate limiter using Redis for multi-instance deployments"""

    def __init__(self, cache_manager):
        self.cache = cache_manager

    async def acquire_token(
            self,
            key: str,
            refill_rate: float,
            capacity: int
    ) -> bool:
        """
        Token bucket algorithm implementation
        """
        now = time.time()

        # Get current bucket state
        bucket_key = f"token_bucket:{key}"
        bucket_data = await self.cache.get(bucket_key)

        if bucket_data:
            tokens, last_refill = bucket_data['tokens'], bucket_data['last_refill']
        else:
            tokens, last_refill = capacity, now

        # Calculate tokens to add
        time_passed = now - last_refill
        tokens_to_add = time_passed * refill_rate
        tokens = min(capacity, tokens + tokens_to_add)

        if tokens >= 1:
            # Consume a token
            tokens -= 1
            await self.cache.set(
                bucket_key,
                {'tokens': tokens, 'last_refill': now},
                expire=CacheTTLConfig.RATE_LIMIT_COOLDOWN
            )
            return True

        return False


class CircuitBreaker:
    """Circuit breaker pattern for external service calls"""

    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failures: Dict[str, int] = {}
        self.last_failure_time: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def call(self, key: str, func, *args, **kwargs):
        """Execute function with circuit breaker protection"""
        async with self._lock:
            # Check if circuit is open
            if key in self.last_failure_time:
                if time.time() - self.last_failure_time[key] < self.timeout:
                    if self.failures.get(key, 0) >= self.failure_threshold:
                        raise Exception(f"Circuit breaker open for {key}")

        try:
            result = await func(*args, **kwargs)
            # Reset failures on success
            async with self._lock:
                self.failures[key] = 0
            return result
        except Exception as e:
            async with self._lock:
                self.failures[key] = self.failures.get(key, 0) + 1
                self.last_failure_time[key] = time.time()
            raise