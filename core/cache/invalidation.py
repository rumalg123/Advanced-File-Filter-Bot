from __future__ import annotations

from typing import TYPE_CHECKING

from core.cache.config import CachePatterns, CacheKeyGenerator
from core.cache.redis_cache import CacheManager

if TYPE_CHECKING:
    from repositories.media import MediaFile

class CacheInvalidator:
    """Helper class for cache invalidation"""

    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager

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
        
        # Invalidate all search-related caches since they may contain this media
        await self.cache.delete_pattern("search:*")
        await self.cache.delete_pattern("search_results_*")

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
        """Invalidate all search result caches"""
        await self.cache.delete_pattern("search:*")
        await self.cache.delete_pattern("search_results_*")

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
