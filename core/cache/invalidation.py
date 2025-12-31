from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from core.cache.config import CachePatterns, CacheKeyGenerator
from core.cache.redis_cache import CacheManager
from core.utils.logger import get_logger

if TYPE_CHECKING:
    from repositories.media import MediaFile

logger = get_logger(__name__)


class CacheInvalidator:
    """Helper class for cache invalidation with smart versioning"""

    # Cache version key - incrementing this invalidates all versioned caches
    SEARCH_CACHE_VERSION_KEY = "cache:search:version"

    # Throttle full invalidation to prevent cache stampedes
    _last_full_invalidation: float = 0
    FULL_INVALIDATION_COOLDOWN = 5.0  # seconds

    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager

    async def get_search_cache_version(self) -> int:
        """Get current search cache version"""
        version = await self.cache.get(self.SEARCH_CACHE_VERSION_KEY)
        return int(version) if version else 1

    async def increment_search_cache_version(self) -> int:
        """Increment search cache version to invalidate all search caches lazily"""
        new_version = await self.cache.increment(self.SEARCH_CACHE_VERSION_KEY)
        if new_version == 1:
            # First increment, set to 2 to ensure version exists
            new_version = await self.cache.increment(self.SEARCH_CACHE_VERSION_KEY)
        return new_version

    async def invalidate_user_cache(self, user_id: int):
        """Invalidate all cache entries for a user"""
        patterns = CachePatterns.user_related(user_id)
        for pattern in patterns:
            if '*' in pattern:
                # Handle wildcard patterns
                # Note: This would require SCAN command implementation
                await self.cache.delete_pattern(pattern)
            else:
                await self.cache.delete(pattern)

    async def invalidate_media_cache(self, file_id: str, file_ref: str = None, file_unique_id: str = None):
        """Invalidate media-related cache"""
        keys = CachePatterns.media_related(file_id, file_ref, file_unique_id)
        for key in keys:
            await self.cache.delete(key)

        # Use versioning instead of direct deletion for search caches
        await self.increment_search_cache_version()

    async def invalidate_group_cache(self, group_id: str):
        """Invalidate group-related cache"""
        patterns = CachePatterns.group_related(group_id)
        for pattern in patterns:
            if '*' in pattern:
                # Handle wildcard patterns
                await self.cache.delete_pattern(pattern)
            else:
                await self.cache.delete(pattern)

    async def invalidate_all_search_results(self):
        """
        Invalidate all search result caches using versioning.
        Uses throttling to prevent cache stampedes on bulk operations.
        """
        current_time = time.time()

        # Throttle full invalidation to prevent cache stampedes
        if current_time - CacheInvalidator._last_full_invalidation < self.FULL_INVALIDATION_COOLDOWN:
            logger.debug("Skipping search cache invalidation (throttled)")
            return

        CacheInvalidator._last_full_invalidation = current_time

        # Increment version instead of deleting all keys
        # This is O(1) instead of O(n) where n is number of cached search results
        new_version = await self.increment_search_cache_version()
        logger.debug(f"Search cache version incremented to {new_version}")

    async def invalidate_channels_cache(self):
        """Invalidate channels list cache"""
        await self.cache.delete("active_channels_list")

    async def invalidate_connection_cache(self, user_id: str):
        """Invalidate all cache entries for a user's connections"""
        # Clear the main connection cache
        cache_key = CacheKeyGenerator.user_connections(user_id)
        await self.cache.delete(cache_key)

    async def invalidate_file_cache(self, file: 'MediaFile'):
        """Invalidate all cache entries for a file"""
        # Clear main cache entries
        if file.file_unique_id:
            cache_key = CacheKeyGenerator.media(file.file_unique_id)
            await self.cache.delete(cache_key)
        if file.file_id:
            cache_key = CacheKeyGenerator.media(file.file_id)
            await self.cache.delete(cache_key)
