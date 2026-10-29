"""Per-user action rate limiting with bounded Redis-outage degradation."""
import asyncio
import math
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from core.cache.config import CacheTTLConfig, CacheKeyGenerator
from core.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    max_requests: int
    time_window: int  # seconds
    cooldown_time: int = 60  # seconds


@dataclass
class _LocalWindow:
    count: int
    window_end: float
    blocked_until: float = 0.0


class RateLimiter:
    """Redis-backed limiter; bounded per-process fallback during outages.

    PH-023: An unavailable unsplit Redis no longer allows unlimited requests.
    Local fallback is per process and is NOT a substitute for a distributed
    limit across replicas. Protected operational-state Redis still fails
    closed. At capacity, new local identities are denied rather than
    evicting still-active limiter entries.
    """

    LOCAL_MAX_ENTRIES = 4096

    def __init__(self, cache_manager):
        self.cache = cache_manager
        self.ttl = CacheTTLConfig()
        from core.cache.invalidation import CacheInvalidator
        self.cache_invalidator = CacheInvalidator(cache_manager)
        self.configs: Dict[str, RateLimitConfig] = {
            'search': RateLimitConfig(max_requests=30, time_window=self.ttl.RATE_LIMIT_WINDOW),
            'file_request': RateLimitConfig(max_requests=10, time_window=60),
            'broadcast': RateLimitConfig(
                max_requests=1, time_window=3600,
                cooldown_time=self.ttl.RATE_LIMIT_COOLDOWN
            ),
            'inline_query': RateLimitConfig(max_requests=50, time_window=60),
        }
        self._local: OrderedDict[tuple[int, str], _LocalWindow] = OrderedDict()
        self._local_lock = asyncio.Lock()
        self._local_fallback_events = 0
        self._local_capacity_denials = 0

    async def _degraded_check(
        self, user_id: int, action: str, config: RateLimitConfig
    ) -> Tuple[bool, Optional[int]]:
        if getattr(self.cache, "protected_state_enabled", False):
            # PH-003: security-sensitive shared state fails closed.
            return False, config.cooldown_time
        now = time.monotonic()
        identity = (user_id, action)
        async with self._local_lock:
            self._local_fallback_events += 1
            entry = self._local.get(identity)
            if entry is None:
                if len(self._local) >= self.LOCAL_MAX_ENTRIES:
                    # Expired windows only; never evict an active counter to
                    # permit an attacker to reset their own window.
                    expired = [
                        key for key, item in self._local.items()
                        if now >= max(item.window_end, item.blocked_until)
                    ]
                    for key in expired:
                        del self._local[key]
                if len(self._local) >= self.LOCAL_MAX_ENTRIES:
                    self._local_capacity_denials += 1
                    return False, config.cooldown_time
                entry = _LocalWindow(count=0, window_end=now + config.time_window)
                self._local[identity] = entry
            if now < entry.blocked_until:
                return False, max(1, math.ceil(entry.blocked_until - now))
            if now >= entry.window_end:
                entry.count = 0
                entry.window_end = now + config.time_window
                entry.blocked_until = 0.0
            entry.count += 1
            if entry.count > config.max_requests:
                entry.blocked_until = max(
                    entry.window_end, now + config.cooldown_time
                )
                return False, max(1, math.ceil(entry.blocked_until - now))
            return True, None

    async def check_rate_limit(
            self,
            user_id: int,
            action: str
    ) -> Tuple[bool, Optional[int]]:
        """Use atomic Redis counters; safely degrade if the backend fails."""
        config = self.configs.get(action)
        if not config:
            return True, None

        key = CacheKeyGenerator.rate_limit(user_id, action)
        cooldown_key = CacheKeyGenerator.rate_limit_cooldown(user_id, action)
        try:
            cooldown_ttl = await self.cache.ttl(cooldown_key)
            if cooldown_ttl is not None and cooldown_ttl > 0:
                return False, cooldown_ttl

            increment_with_expiry = getattr(self.cache, 'increment_with_expiry', None)
            if increment_with_expiry:
                new_count = await increment_with_expiry(key, 1, config.time_window)
            else:
                new_count = await self.cache.increment(key)

            if type(new_count) is not int or new_count < 1:
                raise RuntimeError("Rate limit Redis counter unavailable")

            if not increment_with_expiry:
                current_ttl = await self.cache.ttl(key)
                if current_ttl is None:
                    raise RuntimeError("Rate limit TTL backend unavailable")
                if current_ttl < 0:
                    if not await self.cache.expire(key, config.time_window):
                        raise RuntimeError("Failed to attach rate limit expiry")

            if new_count > config.max_requests:
                window_ttl = await self.cache.ttl(key)
                if window_ttl is None or window_ttl <= 0:
                    window_ttl = config.time_window
                cooldown_seconds = max(window_ttl, config.cooldown_time)
                if not await self.cache.set(
                    cooldown_key, cooldown_seconds, expire=cooldown_seconds
                ):
                    logger.warning("Rate limit cooldown state not persisted for action %s", action)
                return False, cooldown_seconds
            return True, None
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Rate limit Redis unavailable for action %s; applying bounded local fallback",
                action
            )
            return await self._degraded_check(user_id, action, config)

    async def reset_rate_limit(self, user_id: int, action: str) -> None:
        """Reset remote and any local fallback entry for an explicit admin reset."""
        async with self._local_lock:
            self._local.pop((user_id, action), None)
        await self.cache_invalidator.invalidate_rate_limit(user_id, action)

    def local_fallback_metrics(self) -> dict:
        """Safe aggregate counters for monitoring, without per-user IDs."""
        return {
            "entries": len(self._local),
            "fallback_events": self._local_fallback_events,
            "capacity_denials": self._local_capacity_denials,
            "max_entries": self.LOCAL_MAX_ENTRIES,
        }
