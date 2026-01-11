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

    async def invalidate_user_data(self, user_id: int) -> bool:
        """Invalidate just the user data cache (lightweight)"""
        try:
            await self.cache.delete(CacheKeyGenerator.user(user_id))
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate user data for {user_id}: {e}")
            return False

    async def invalidate_user_and_banned(self, user_id: int) -> bool:
        """Invalidate user data and banned users list (for ban/unban operations)"""
        try:
            await self.cache.delete(CacheKeyGenerator.user(user_id))
            await self.cache.delete(CacheKeyGenerator.banned_users())
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate user and banned cache for {user_id}: {e}")
            return False

    async def invalidate_user_cache(self, user_id: int) -> bool:
        """Invalidate all cache entries for a user (comprehensive)"""
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

    async def invalidate_all_users_cache(self) -> bool:
        """Invalidate all user caches (for bulk operations like daily reset)"""
        try:
            await self.cache.delete_pattern("user:*")
            await self.cache.delete(CacheKeyGenerator.banned_users())
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate all users cache: {e}")
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

    async def invalidate_filter_entry(self, group_id: str, text: str) -> bool:
        """Invalidate a specific filter entry cache"""
        try:
            cache_key = CacheKeyGenerator.filter(group_id, text)
            await self.cache.delete(cache_key)
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate filter entry cache: {e}")
            return False

    async def invalidate_batch_link_cache(self, batch_id: str) -> bool:
        """Invalidate batch link cache entry"""
        try:
            cache_key = CacheKeyGenerator.batch_link(batch_id)
            await self.cache.delete(cache_key)
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate batch link cache for {batch_id}: {e}")
            return False

    async def invalidate_bot_setting(self, setting_key: str) -> bool:
        """Invalidate a specific bot setting cache"""
        try:
            cache_key = CacheKeyGenerator.bot_setting(setting_key)
            await self.cache.delete(cache_key)
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate bot setting cache for {setting_key}: {e}")
            return False

    async def invalidate_media_entry(self, identifier: str) -> bool:
        """Invalidate a specific media cache entry"""
        try:
            cache_key = CacheKeyGenerator.media(identifier)
            await self.cache.delete(cache_key)
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate media cache for {identifier}: {e}")
            return False

    async def invalidate_search_sessions(self) -> bool:
        """Invalidate all search session caches"""
        try:
            await self.cache.delete_pattern("search_results_*")
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate search sessions: {e}")
            return False

    # Session management methods
    async def invalidate_session(self, session_key: str) -> bool:
        """Invalidate a specific session cache entry"""
        try:
            await self.cache.delete(session_key)
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate session {session_key}: {e}")
            return False

    async def invalidate_all_sessions(self) -> bool:
        """Invalidate all session caches"""
        try:
            await self.cache.delete_pattern("session:*")
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate all sessions: {e}")
            return False

    # Rate limiting methods
    async def invalidate_rate_limit(self, user_id: int, action: str) -> bool:
        """Invalidate rate limit cache for a user and action"""
        try:
            key = CacheKeyGenerator.rate_limit(user_id, action)
            cooldown_key = CacheKeyGenerator.rate_limit_cooldown(user_id, action)
            await self.cache.delete(key)
            await self.cache.delete(cooldown_key)
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate rate limit for user {user_id}, action {action}: {e}")
            return False

    # Generic cache key invalidation (for base repository)
    async def invalidate_cache_key(self, cache_key: str) -> bool:
        """Invalidate a specific cache key (generic method for base operations)"""
        try:
            await self.cache.delete(cache_key)
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate cache key {cache_key}: {e}")
            return False

    # Transient operation state methods
    async def invalidate_deleteall_pending(self, user_id: int) -> bool:
        """Invalidate deleteall pending cache for a user"""
        try:
            cache_key = f"deleteall_pending:{user_id}"
            await self.cache.delete(cache_key)
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate deleteall pending for user {user_id}: {e}")
            return False

    async def invalidate_broadcast_state(self, state_key: str) -> bool:
        """Invalidate broadcast state cache"""
        try:
            await self.cache.delete(state_key)
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate broadcast state {state_key}: {e}")
            return False

    async def invalidate_subscription_session(self, session_key: str) -> bool:
        """Invalidate subscription session cache"""
        try:
            await self.cache.delete(session_key)
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate subscription session {session_key}: {e}")
            return False
