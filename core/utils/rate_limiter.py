from dataclasses import dataclass
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
        from core.cache.invalidation import CacheInvalidator
        self.cache_invalidator = CacheInvalidator(cache_manager)
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
        Check if user has exceeded rate limit using atomic operations.
        Returns: (is_allowed, seconds_until_reset)
        """
        config = self.configs.get(action)
        if not config:
            return True, None

        key = CacheKeyGenerator.rate_limit(user_id, action)
        cooldown_key = CacheKeyGenerator.rate_limit_cooldown(user_id, action)

        # Check if user is in cooldown - use TTL to get remaining time
        cooldown_ttl = await self.cache.ttl(cooldown_key)
        if cooldown_ttl and cooldown_ttl > 0:
            return False, cooldown_ttl

        # ATOMIC: Increment first, then check value
        # This prevents race conditions where multiple requests pass the check
        new_count = await self.cache.increment(key)

        # Handle Redis unavailability - allow request but log warning
        if new_count is None:
            logger.warning(f"Rate limit check failed for user {user_id}, action {action} - Redis unavailable")
            return True, None

        # Set expiration on first request (when count becomes 1)
        # Use expire() which is safe even if key already exists
        if new_count == 1:
            # Set expiration - if this fails, log warning but continue
            expire_result = await self.cache.expire(key, config.time_window)
            if not expire_result:
                logger.warning(f"Failed to set expiration for rate limit key {key}, but continuing")
        elif new_count > 1:
            # Ensure expiration is set even if it wasn't set on first request
            # This handles race conditions where multiple requests increment before expire is set
            current_ttl = await self.cache.ttl(key)
            if current_ttl == -1:  # Key exists but has no expiration
                await self.cache.expire(key, config.time_window)

        # Check if limit exceeded AFTER incrementing
        if new_count > config.max_requests:
            # Apply cooldown
            await self.cache.set(
                cooldown_key,
                config.cooldown_time,
                expire=config.cooldown_time
            )
            return False, config.cooldown_time

        return True, None

    async def reset_rate_limit(self, user_id: int, action: str) -> None:
        """Reset rate limit for a user and action"""
        await self.cache_invalidator.invalidate_rate_limit(user_id, action)

