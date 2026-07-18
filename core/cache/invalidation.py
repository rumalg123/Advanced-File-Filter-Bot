from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from core.cache.config import CachePatterns, CacheKeyGenerator
from core.cache.redis_cache import CacheManager
from core.utils.logger import get_logger

if TYPE_CHECKING:
    from repositories.media import MediaFile

logger = get_logger(__name__)


class CacheInvalidator:
    """Helper class for cache invalidation with smart versioning"""

    # Cache version key - use centralized generator
    SEARCH_CACHE_VERSION_KEY = CacheKeyGenerator.search_cache_version()

    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager

    async def _delete_targets(self, targets: list[str]) -> bool:
        """Delete keys/patterns and preserve underlying failure semantics."""
        succeeded = True
        for target in targets:
            if '*' in target:
                deleted = await self.cache.delete_pattern(target)
                succeeded = deleted >= 0 and succeeded
            else:
                succeeded = bool(await self.cache.delete(target)) and succeeded
        return succeeded

    async def get_search_cache_version(self) -> int:
        """Get current search cache version"""
        version = await self.cache.get(self.SEARCH_CACHE_VERSION_KEY)
        if version is None:
            return 1
        try:
            parsed = int(version)
            if parsed < 1:
                raise ValueError("version must be positive")
            return parsed
        except (TypeError, ValueError):
            logger.warning("Discarding malformed search cache version")
            await self.cache.delete(self.SEARCH_CACHE_VERSION_KEY)
            return 1

    async def increment_search_cache_version(self) -> Optional[int]:
        """Increment search cache version to invalidate all search caches lazily"""
        new_version = await self.cache.increment(self.SEARCH_CACHE_VERSION_KEY)
        if new_version is None:
            return None
        if new_version == 1:
            # First increment, set to 2 to ensure version exists
            new_version = await self.cache.increment(self.SEARCH_CACHE_VERSION_KEY)
            # Set a very long expiration (1 year) for the version key since it's a persistent counter
            # This prevents memory leaks while keeping the version persistent
            await self.cache.expire(self.SEARCH_CACHE_VERSION_KEY, 31536000)  # 1 year
        return new_version

    async def invalidate_user_data(self, user_id: int) -> bool:
        """Invalidate just the user data cache (lightweight)"""
        try:
            return await self.cache.delete(CacheKeyGenerator.user(user_id))
        except Exception as e:
            logger.error(f"Failed to invalidate user data for {user_id}: {e}")
            return False

    async def invalidate_premium_status(self, user_id: int) -> bool:
        """Invalidate the independently cached premium access decision."""
        try:
            return await self.cache.delete(CacheKeyGenerator.premium_status(user_id))
        except Exception as e:
            logger.error(f"Failed to invalidate premium status for {user_id}: {e}")
            return False

    async def invalidate_user_stats(self) -> bool:
        """Invalidate aggregate user statistics."""
        try:
            return await self.cache.delete(CacheKeyGenerator.user_stats())
        except Exception as e:
            logger.error(f"Failed to invalidate user statistics: {e}")
            return False

    async def invalidate_user_and_banned(self, user_id: int) -> bool:
        """Invalidate user data and banned users list (for ban/unban operations)"""
        try:
            return await self._delete_targets([
                CacheKeyGenerator.user(user_id),
                CacheKeyGenerator.banned_users(),
            ])
        except Exception as e:
            logger.error(f"Failed to invalidate user and banned cache for {user_id}: {e}")
            return False

    async def invalidate_user_cache(self, user_id: int) -> bool:
        """Invalidate all cache entries for a user (comprehensive)"""
        try:
            return await self._delete_targets(CachePatterns.user_related(user_id))
        except Exception as e:
            logger.error(f"Failed to invalidate user cache for {user_id}: {e}")
            return False

    async def invalidate_all_users_cache(self) -> bool:
        """Invalidate all user caches (for bulk operations like daily reset)"""
        try:
            return await self._delete_targets([
                CachePatterns.ALL_USERS,
                CacheKeyGenerator.banned_users(),
                CacheKeyGenerator.user_stats(),
            ])
        except Exception as e:
            logger.error(f"Failed to invalidate all users cache: {e}")
            return False

    async def invalidate_all_search_results(self) -> bool:
        """
        Invalidate all search result caches using versioning.
        """
        try:
            # Increment version instead of deleting all keys
            # This is O(1) instead of O(n) where n is number of cached search results
            new_version = await self.increment_search_cache_version()
            logger.debug(f"Search cache version incremented to {new_version}")
            return new_version is not None
        except Exception as e:
            logger.error(f"Failed to invalidate all search results: {e}")
            return False

    async def invalidate_channels_cache(self) -> bool:
        """Invalidate channels list cache"""
        try:
            return await self.cache.delete(CacheKeyGenerator.active_channels())
        except Exception as e:
            logger.error(f"Failed to invalidate channels cache: {e}")
            return False

    async def invalidate_connection_cache(self, user_id: str) -> bool:
        """Invalidate all cache entries for a user's connections"""
        try:
            cache_key = CacheKeyGenerator.user_connections(user_id)
            return await self.cache.delete(cache_key)
        except Exception as e:
            logger.error(f"Failed to invalidate connection cache for {user_id}: {e}")
            return False

    async def invalidate_file_cache(self, file: 'MediaFile') -> bool:
        """Invalidate all cache entries for a file"""
        try:
            targets = []
            if file.file_unique_id:
                targets.append(CacheKeyGenerator.media(file.file_unique_id))
            if file.file_id:
                targets.append(CacheKeyGenerator.media(file.file_id))
            if hasattr(file, 'file_ref') and file.file_ref:
                targets.append(CacheKeyGenerator.media(file.file_ref))
            targets.append(CacheKeyGenerator.file_stats())
            return await self._delete_targets(list(dict.fromkeys(targets)))
        except Exception as e:
            logger.error(f"Failed to invalidate file cache: {e}")
            return False

    async def invalidate_file_stats(self) -> bool:
        """Invalidate aggregate media statistics without evicting an entity."""
        try:
            return await self.cache.delete(CacheKeyGenerator.file_stats())
        except Exception as e:
            logger.error(f"Failed to invalidate file statistics: {e}")
            return False

    async def invalidate_settings_cache(self, setting_key: Optional[str] = None) -> bool:
        """
        Invalidate cache entries related to bot settings.
        If setting_key is provided, only invalidate caches related to that setting.
        """
        # Mapping of settings to cache patterns they affect
        setting_cache_map = {
            'ADMINS': [CachePatterns.ALL_USERS, CacheKeyGenerator.banned_users()],
            'AUTH_CHANNEL': [
                CachePatterns.ALL_SUBSCRIPTIONS,
                CachePatterns.ALL_DEEPLINK_SESSIONS,
            ],
            'AUTH_GROUPS': [
                CachePatterns.ALL_SUBSCRIPTIONS,
                CachePatterns.ALL_DEEPLINK_SESSIONS,
            ],
            'CHANNELS': [CacheKeyGenerator.active_channels(), CachePatterns.ALL_CHANNELS],
            'MAX_BTN_SIZE': [CachePatterns.ALL_SEARCH_CACHE],
            'USE_CAPTION_FILTER': [CachePatterns.ALL_SEARCH_CACHE],
            'NON_PREMIUM_DAILY_LIMIT': [CachePatterns.ALL_USERS],
            'PREMIUM_DURATION_DAYS': [CachePatterns.ALL_USERS],
            'MESSAGE_DELETE_SECONDS': [CachePatterns.ALL_SEARCH_CACHE],
            'CACHE_TIME': [CachePatterns.ALL_SEARCH_CACHE],
            'DISABLE_FILTER': [CachePatterns.ALL_FILTERS, CachePatterns.ALL_FILTER_LISTS],
            'DISABLE_PREMIUM': [CachePatterns.ALL_USERS],
            'FILE_STORE_CHANNEL': [CachePatterns.ALL_FILESTORE],
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

            patterns_to_clear.append(CacheKeyGenerator.all_settings())
            return await self._delete_targets(list(dict.fromkeys(patterns_to_clear)))
        except Exception as e:
            logger.error(f"Failed to invalidate settings cache: {e}")
            return False

    async def invalidate_filter_cache(self, group_id: Optional[str] = None) -> bool:
        """Invalidate filter cache entries"""
        try:
            if group_id:
                return await self._delete_targets([
                    CacheKeyGenerator.filter_list(group_id),
                    CachePatterns.filter_entries_pattern(group_id),
                ])
            return await self._delete_targets([
                CachePatterns.ALL_FILTERS,
                CachePatterns.ALL_FILTER_LISTS,
            ])
        except Exception as e:
            logger.error(f"Failed to invalidate filter cache: {e}")
            return False

    async def invalidate_filter_entry(self, group_id: str, text: str) -> bool:
        """Invalidate a specific filter entry cache"""
        try:
            cache_key = CacheKeyGenerator.filter(group_id, text)
            return await self.cache.delete(cache_key)
        except Exception as e:
            logger.error(f"Failed to invalidate filter entry cache: {e}")
            return False

    async def invalidate_batch_link_cache(self, batch_id: str) -> bool:
        """Invalidate batch link cache entry"""
        try:
            cache_key = CacheKeyGenerator.batch_link(batch_id)
            return await self.cache.delete(cache_key)
        except Exception as e:
            logger.error(f"Failed to invalidate batch link cache for {batch_id}: {e}")
            return False

    async def invalidate_bot_setting(self, setting_key: str) -> bool:
        """Invalidate a specific bot setting cache"""
        try:
            cache_key = CacheKeyGenerator.bot_setting(setting_key)
            return await self.cache.delete(cache_key)
        except Exception as e:
            logger.error(f"Failed to invalidate bot setting cache for {setting_key}: {e}")
            return False

    async def invalidate_media_entry(self, identifier: str) -> bool:
        """Invalidate a specific media cache entry"""
        try:
            cache_key = CacheKeyGenerator.media(identifier)
            return await self.cache.delete(cache_key)
        except Exception as e:
            logger.error(f"Failed to invalidate media cache for {identifier}: {e}")
            return False

    async def invalidate_search_sessions(self) -> bool:
        """Invalidate all search session caches"""
        try:
            return await self.cache.delete_pattern(CachePatterns.ALL_SEARCH_RESULTS) >= 0
        except Exception as e:
            logger.error(f"Failed to invalidate search sessions: {e}")
            return False

    # Session management methods
    async def invalidate_session(self, session_key: str) -> bool:
        """Invalidate a specific session cache entry"""
        try:
            return await self.cache.delete(session_key)
        except Exception as e:
            logger.error(f"Failed to invalidate session {session_key}: {e}")
            return False

    async def invalidate_all_sessions(self) -> bool:
        """Invalidate all session caches"""
        try:
            return await self.cache.delete_pattern(CachePatterns.ALL_SESSIONS) >= 0
        except Exception as e:
            logger.error(f"Failed to invalidate all sessions: {e}")
            return False

    # Rate limiting methods
    async def invalidate_rate_limit(self, user_id: int, action: str) -> bool:
        """Invalidate rate limit cache for a user and action"""
        try:
            key = CacheKeyGenerator.rate_limit(user_id, action)
            cooldown_key = CacheKeyGenerator.rate_limit_cooldown(user_id, action)
            return await self._delete_targets([key, cooldown_key])
        except Exception as e:
            logger.error(f"Failed to invalidate rate limit for user {user_id}, action {action}: {e}")
            return False

    # Generic cache key invalidation (for base repository)
    async def invalidate_cache_key(self, cache_key: str) -> bool:
        """Invalidate a specific cache key (generic method for base operations)"""
        try:
            return await self.cache.delete(cache_key)
        except Exception as e:
            logger.error(f"Failed to invalidate cache key {cache_key}: {e}")
            return False

    # Transient operation state methods
    async def invalidate_deleteall_pending(self, user_id: int) -> bool:
        """Invalidate deleteall pending cache for a user"""
        try:
            cache_key = CacheKeyGenerator.deleteall_pending(user_id)
            return await self.cache.delete(cache_key)
        except Exception as e:
            logger.error(f"Failed to invalidate deleteall pending for user {user_id}: {e}")
            return False

    async def invalidate_broadcast_state(self, state_key: str) -> bool:
        """Invalidate broadcast state cache"""
        try:
            return await self.cache.delete(state_key)
        except Exception as e:
            logger.error(f"Failed to invalidate broadcast state {state_key}: {e}")
            return False

    async def invalidate_subscription_session(self, session_key: str) -> bool:
        """Invalidate subscription session cache"""
        try:
            return await self.cache.delete(session_key)
        except Exception as e:
            logger.error(f"Failed to invalidate subscription session {session_key}: {e}")
            return False
