"""Explicit routing between disposable Redis cache and protected operational state.

Enabled ONLY when REDIS_STATE_URI points to a separate Redis *instance*.
A Redis database number on the same instance is not eviction isolation.
Existing deployments without REDIS_STATE_URI continue using CacheManager
unchanged. No live key migrations are performed automatically.
"""
import asyncio
from typing import Any, Optional
from urllib.parse import urlsplit

from core.cache.redis_cache import CacheManager
from core.utils.logger import get_logger

logger = get_logger(__name__)

# Route every operation for these keys to the non-evicting state instance.
# Keep cache:search:version in the same backend as operational keys, but
# store actual search result pages on the disposable cache backend.
STATE_PREFIXES = (
    "rate_limit:",
    "session:",
    "search_results_",
    "checksub_session:",
    "deeplink_",
    "deleteall_pending:",
    "broadcast:state",
    "last_counter_reset_date",
    "recent_settings_edit:",
    "cache:search:version",
)


def _server_identity(uri: str) -> tuple[str, int]:
    parsed = urlsplit(uri)
    if parsed.scheme not in ("redis", "rediss") or not parsed.hostname:
        raise ValueError("Expected a redis:// or rediss:// connection URL")
    return parsed.hostname.lower(), parsed.port or 6379


class RoutedCacheManager:
    """CacheManager-compatible facade, routing only key-owned methods.

    A failure of the state Redis is never silently redirected to the cache
    Redis, since doing so would reintroduce eviction of protected state.
    """

    protected_state_enabled = True

    def __init__(self, cache: CacheManager, state: CacheManager):
        if _server_identity(cache.redis_url) == _server_identity(state.redis_url):
            raise ValueError(
                "REDIS_STATE_URI must use another Redis instance, not another DB "
                "number on the same Redis server"
            )
        self.cache_backend = cache
        self.state_backend = state

    @property
    def redis(self):
        # Legacy monitoring reads the disposable cache instance. The
        # state instance is exposed separately for dedicated monitoring.
        return self.cache_backend.redis

    @property
    def state_redis(self):
        return self.state_backend.redis

    def __getattr__(self, name: str) -> Any:
        # Non-key utility methods/attributes retain their existing contract.
        return getattr(self.cache_backend, name)

    def backend_for_key(self, key: str) -> CacheManager:
        if str(key).startswith(STATE_PREFIXES):
            return self.state_backend
        return self.cache_backend

    async def initialize(self) -> None:
        await self.cache_backend.initialize()
        try:
            await self.state_backend.initialize()
        except BaseException:
            # Never start a partly configured split deployment.
            await self.cache_backend.close()
            raise
        logger.info("Protected Redis state backend initialized (dedicated instance)")

    async def close(self) -> None:
        try:
            await self.state_backend.close()
        finally:
            await self.cache_backend.close()

    async def get(self, key: str):
        return await self.backend_for_key(key).get(key)

    async def set(self, key: str, value: Any, expire=None) -> bool:
        return await self.backend_for_key(key).set(key, value, expire=expire)

    async def delete(self, key: str) -> bool:
        return await self.backend_for_key(key).delete(key)

    async def exists(self, key: str) -> bool:
        return await self.backend_for_key(key).exists(key)

    async def mget(self, keys: list[str]) -> list[Any]:
        # Preserve original key positions even when both backends are used.
        output = [None] * len(keys)
        grouped = ((self.cache_backend, []), (self.state_backend, []))
        for i, key in enumerate(keys):
            for backend, group in grouped:
                if self.backend_for_key(key) is backend:
                    group.append((i, key))
                    break
        for backend, group in grouped:
            if group:
                values = await backend.mget([key for _, key in group])
                for (index, _), value in zip(group, values):
                    output[index] = value
        return output

    async def ensure_search_generation(self, key: str, random_initial: int):
        return await self.backend_for_key(key).ensure_search_generation(
            key, random_initial
        )

    async def advance_search_generation(self, key: str, random_initial: int):
        return await self.backend_for_key(key).advance_search_generation(
            key, random_initial
        )

    async def ensure_counter_initialized(self, key: str, initial: int):
        return await self.backend_for_key(key).ensure_counter_initialized(key, initial)

    async def increment(self, key: str, amount: int = 1) -> Optional[int]:
        return await self.backend_for_key(key).increment(key, amount)

    async def increment_with_expiry(self, key: str, amount: int, seconds: int):
        return await self.backend_for_key(key).increment_with_expiry(key, amount, seconds)

    async def delete_if_value(self, key: str, expected_value: Any) -> bool:
        return await self.backend_for_key(key).delete_if_value(key, expected_value)

    async def expire(self, key: str, seconds: int) -> bool:
        return await self.backend_for_key(key).expire(key, seconds)

    async def ttl(self, key: str) -> int:
        return await self.backend_for_key(key).ttl(key)

    async def delete_pattern(self, pattern: str) -> int:
        # Prefix-matched patterns can be safely scoped; patterns beginning
        # with wildcards might cover both backends and require both scans.
        if str(pattern).startswith(STATE_PREFIXES):
            return await self.state_backend.delete_pattern(pattern)
        if str(pattern).startswith(("search:", "media:", "user:", "filter:",
                                     "filters_list:", "channel:", "connections:")):
            return await self.cache_backend.delete_pattern(pattern)
        outcomes = await asyncio.gather(
            self.cache_backend.delete_pattern(pattern),
            self.state_backend.delete_pattern(pattern),
            return_exceptions=True,
        )
        if any(isinstance(x, BaseException) or not isinstance(x, int) or x < 0
               for x in outcomes):
            return -1
        return sum(outcomes)

    async def zadd(self, key: str, score: float, member: str) -> bool:
        return await self.backend_for_key(key).zadd(key, score, member)

    async def zincrby(self, key: str, amount: float, member: str):
        return await self.backend_for_key(key).zincrby(key, amount, member)

    async def zrevrange(self, key: str, start=0, end=-1, with_scores=False):
        return await self.backend_for_key(key).zrevrange(
            key, start, end, with_scores=with_scores
        )

    async def get_cache_stats(self) -> dict:
        cache_stats, state_stats = await asyncio.gather(
            self.cache_backend.get_cache_stats(),
            self.state_backend.get_cache_stats(),
        )
        return {
            **cache_stats,
            "protected_state": {
                "is_connected": self.state_backend.redis is not None,
                "redis_info": state_stats.get("redis_info", {}),
                "connection_info": state_stats.get("connection_info", {}),
            },
        }
