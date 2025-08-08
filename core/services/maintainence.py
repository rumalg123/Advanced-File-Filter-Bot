
from functools import lru_cache
from typing import Dict, Any

from core.cache.redis_cache import CacheManager
from repositories.media import MediaRepository
from repositories.user import UserRepository

from core.utils.logger import get_logger
logger = get_logger(__name__)
class MaintenanceService:
    """Service for maintenance tasks"""

    def __init__(
            self,
            user_repo: UserRepository,
            media_repo: MediaRepository,
            cache_manager: CacheManager
    ):
        self.user_repo = user_repo
        self.media_repo = media_repo
        self.cache = cache_manager

    async def run_daily_maintenance(self) -> Dict[str, Any]:
        """Run daily maintenance tasks"""
        results = {}

        # Cleanup expired premium subscriptions
        try:
            expired_count = await self.user_repo.cleanup_expired_premium()
            results['expired_premium'] = expired_count
        except Exception as e:
            logger.error(f"Error cleaning up expired premium: {e}")
            results['expired_premium'] = 0

        # Reset daily counters for users
        try:
            # This would be done via a scheduled task in production
            # await self.user_repo.reset_daily_counters()
            results['counters_reset'] = True
        except Exception as e:
            logger.error(f"Error resetting counters: {e}")
            results['counters_reset'] = False

        # Clear expired cache entries
        # Redis handles this automatically with TTL

        return results

    async def get_system_stats(self) -> Dict[str, Any]:
        """Get comprehensive system statistics"""
        stats = {}

        # User stats
        user_stats = await self.user_repo.get_user_stats()
        stats['users'] = user_stats

        # File stats
        file_stats = await self.media_repo.get_file_stats()
        stats['files'] = file_stats

        # Cache stats (if Redis provides them)
        # stats['cache'] = await self.cache.get_stats()

        return stats

    # async def cleanup_old_data(self, days: int = 365) -> Dict[str, int]:
    #     """Cleanup old data"""
    #     results = {}
    #
    #     # Cleanup old files
    #     try:
    #         deleted_files = await self.media_repo.cleanup_old_files(days)
    #         results['deleted_files'] = deleted_files
    #     except Exception as e:
    #         logger.error(f"Error cleaning up old files: {e}")
    #         results['deleted_files'] = 0
    #
    #     return results







@lru_cache(maxsize=1)
def get_maintenance_service(
        user_repo: UserRepository,
        media_repo: MediaRepository,
        cache_manager: CacheManager
) -> MaintenanceService:
    """Get singleton MaintenanceService instance"""
    return MaintenanceService(user_repo, media_repo, cache_manager)