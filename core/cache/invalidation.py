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

    async def invalidate_user_cache(self, user_id: int) -> bool:
        """Invalidate all cache entries for a user"""
        try:
            patterns = CachePatterns.user_related(user_id)
            for pattern in patterns:
                if '*' in pattern:
                    await self.cache.delete_pattern(pattern)
                else:
                    await self.cache.delete(pattern)
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate user cache for {user_id}: {e}")
            return False

    async def invalidate_all_search_results(self) -> bool:
        """
        Invalidate all search result caches using versioning.
        Uses throttling to prevent cache stampedes on bulk operations.
        """
        try:
            current_time = time.time()

            # Throttle full invalidation to prevent cache stampedes
            if current_time - CacheInvalidator._last_full_invalidation < self.FULL_INVALIDATION_COOLDOWN:
                logger.debug("Skipping search cache invalidation (throttled)")
                return True

            CacheInvalidator._last_full_invalidation = current_time

            # Increment version instead of deleting all keys
            # This is O(1) instead of O(n) where n is number of cached search results
            new_version = await self.increment_search_cache_version()
            logger.debug(f"Search cache version incremented to {new_version}")
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate all search results: {e}")
            return False

    async def invalidate_channels_cache(self) -> bool:
        """Invalidate channels list cache"""
        try:
            await self.cache.delete("active_channels_list")
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate channels cache: {e}")
            return False

    async def invalidate_connection_cache(self, user_id: str) -> bool:
        """Invalidate all cache entries for a user's connections"""
        try:
            cache_key = CacheKeyGenerator.user_connections(user_id)
            await self.cache.delete(cache_key)
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate connection cache for {user_id}: {e}")
            return False

    async def invalidate_file_cache(self, file: 'MediaFile') -> bool:
        """Invalidate all cache entries for a file"""
        try:
            # Clear main cache entries
            if file.file_unique_id:
                cache_key = CacheKeyGenerator.media(file.file_unique_id)
                await self.cache.delete(cache_key)
            if file.file_id:
                cache_key = CacheKeyGenerator.media(file.file_id)
                await self.cache.delete(cache_key)
            if hasattr(file, 'file_ref') and file.file_ref:
                cache_key = CacheKeyGenerator.media(file.file_ref)
                await self.cache.delete(cache_key)
            # Invalidate file stats since file count changed
            await self.cache.delete(CacheKeyGenerator.file_stats())
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate file cache: {e}")
            return False

    async def invalidate_settings_cache(self, setting_key: Optional[str] = None) -> bool:
        """
        Invalidate cache entries related to bot settings.
        If setting_key is provided, only invalidate caches related to that setting.
        """
        # Mapping of settings to cache patterns they affect
        setting_cache_map = {
            'ADMINS': ['user:*', 'banned_users'],
            'AUTH_CHANNEL': ['subscription:*'],
            'AUTH_GROUPS': ['subscription:*'],
            'CHANNELS': ['active_channels_list', 'channel:*'],
            'MAX_BTN_SIZE': ['search:*'],
            'USE_CAPTION_FILTER': ['search:*'],
            'NON_PREMIUM_DAILY_LIMIT': ['user:*'],
            'PREMIUM_DURATION_DAYS': ['user:*'],
            'MESSAGE_DELETE_SECONDS': ['search:*'],
            'DISABLE_FILTER': ['filter:*', 'filters_list:*'],
            'DISABLE_PREMIUM': ['user:*'],
            'FILE_STORE_CHANNEL': ['filestore:*'],
        }

        try:
            patterns_to_clear = []

            if setting_key:
                patterns_to_clear = setting_cache_map.get(setting_key, [])
            else:
                # Clear all patterns if no specific key
                for patterns in setting_cache_map.values():
                    patterns_to_clear.extend(patterns)
                patterns_to_clear = list(set(patterns_to_clear))  # Remove duplicates

            for pattern in patterns_to_clear:
                if '*' in pattern:
                    await self.cache.delete_pattern(pattern)
                else:
                    await self.cache.delete(pattern)

            # Always clear the settings cache itself
            await self.cache.delete(CacheKeyGenerator.all_settings())

            return True
        except Exception as e:
            logger.error(f"Failed to invalidate settings cache: {e}")
            return False

    async def invalidate_filter_cache(self, group_id: Optional[str] = None) -> bool:
        """Invalidate filter cache entries"""
        try:
            if group_id:
                await self.cache.delete(CacheKeyGenerator.filter_list(group_id))
            else:
                await self.cache.delete_pattern("filter:*")
                await self.cache.delete_pattern("filters_list:*")
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate filter cache: {e}")
            return False
