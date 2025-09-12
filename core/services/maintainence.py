
from datetime import date
from functools import lru_cache
from typing import Dict, Any, Optional

from core.cache.config import CacheTTLConfig, CacheKeyGenerator
from core.cache.redis_cache import CacheManager
from core.utils.logger import get_logger
from repositories.media import MediaRepository
from repositories.user import UserRepository

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

        # Reset daily counters for users (only once per day)
        try:
            current_date = date.today()
            
            # Get the last reset date from database (persistent across Docker rebuilds)
            last_reset_date = await self._get_last_counter_reset_date()
            
            # Only reset if we haven't done it today
            if last_reset_date != current_date:
                reset_count = await self.user_repo.reset_daily_counters()
                # Store current date in database for persistence
                await self._store_counter_reset_date(current_date)
                # Also store in cache for quick access (expires after 25 hours to be safe)
                cache_key = CacheKeyGenerator.last_counter_reset_date()
                await self.cache.set(cache_key, current_date.isoformat(), CacheTTLConfig.MAINTENANCE_RESET_DAILY_COUNTERS)
                logger.info(f"Daily counters reset for {reset_count} users (new day: {current_date})")
                results['counters_reset'] = True
                results['reset_count'] = reset_count
            else:
                logger.debug(f"Daily counters already reset today ({current_date})")
                results['counters_reset'] = False
                results['reset_count'] = 0
        except Exception as e:
            logger.error(f"Error resetting counters: {e}")
            results['counters_reset'] = False
            results['reset_count'] = 0

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

        # Database storage stats
        storage_stats = await self.get_database_storage_stats()
        stats['storage'] = storage_stats

        # Cache stats (if Redis provides them)
        # stats['cache'] = await self.cache.get_stats()

        return stats

    async def get_database_storage_stats(self) -> Dict[str, Any]:
        """Get MongoDB database storage statistics"""
        try:
            # Access database through media repository's db_pool
            db = self.media_repo.db_pool.database
            
            # Get database stats using MongoDB's stats command
            db_stats = await db.command("dbStats")
            
            # Get collection stats for main collections
            collections_stats = {}
            main_collections = ['media_files', 'users', 'indexed_channels', 'connections', 'filters']
            
            for collection_name in main_collections:
                try:
                    collection = db[collection_name]
                    # Get collection stats
                    coll_stats = await db.command("collStats", collection_name)
                    collections_stats[collection_name] = {
                        'count': coll_stats.get('count', 0),
                        'size': coll_stats.get('size', 0),  # Data size in bytes
                        'storage_size': coll_stats.get('storageSize', 0),  # Storage size including padding
                        'total_index_size': coll_stats.get('totalIndexSize', 0)
                    }
                except Exception as e:
                    logger.warning(f"Could not get stats for collection {collection_name}: {e}")
                    collections_stats[collection_name] = {
                        'count': 0, 'size': 0, 'storage_size': 0, 'total_index_size': 0
                    }
            
            return {
                'database_size': db_stats.get('dataSize', 0),  # Total data size
                'storage_size': db_stats.get('storageSize', 0),  # Total storage size
                'index_size': db_stats.get('indexSize', 0),  # Total index size
                'total_size': db_stats.get('fsUsedSize', db_stats.get('storageSize', 0)),  # File system usage
                'collections': collections_stats,
                'avg_obj_size': db_stats.get('avgObjSize', 0),
                'objects_count': db_stats.get('objects', 0)
            }
            
        except Exception as e:
            logger.error(f"Error getting database storage stats: {e}")
            return {
                'database_size': 0,
                'storage_size': 0,
                'index_size': 0,
                'total_size': 0,
                'collections': {},
                'avg_obj_size': 0,
                'objects_count': 0
            }

    async def _get_last_counter_reset_date(self) -> Optional[date]:
        """Get the last counter reset date from database (persistent storage)"""
        try:
            # First try cache for performance
            cache_key = CacheKeyGenerator.last_counter_reset_date()
            cached_date_str = await self.cache.get(cache_key)
            if cached_date_str:
                try:
                    return date.fromisoformat(cached_date_str)
                except ValueError:
                    pass
            
            # Fall back to database lookup using bot_settings collection
            from repositories.bot_settings import BotSettingsRepository
            settings_repo = BotSettingsRepository(self.user_repo.db_pool, self.cache)
            
            setting = await settings_repo.get_setting('last_counter_reset_date')
            if setting and setting.value:
                try:
                    db_date = date.fromisoformat(setting.value)
                    # Update cache for future quick access
                    await self.cache.set(cache_key, setting.value, CacheTTLConfig.MAINTENANCE_RESET_DAILY_COUNTERS)
                    return db_date
                except ValueError:
                    logger.warning(f"Invalid date format in database: {setting.value}")
                    
            return None
        except Exception as e:
            logger.error(f"Error getting last counter reset date: {e}")
            return None
    
    async def _store_counter_reset_date(self, reset_date: date):
        """Store the counter reset date in database for persistence"""
        try:
            from repositories.bot_settings import BotSettingsRepository
            settings_repo = BotSettingsRepository(self.user_repo.db_pool, self.cache)
            
            await settings_repo.update_setting(
                'last_counter_reset_date',
                reset_date.isoformat(),
                f'Last daily counter reset date: {reset_date}'
            )
        except Exception as e:
            logger.error(f"Error storing counter reset date: {e}")

@lru_cache(maxsize=1)
def get_maintenance_service(
        user_repo: UserRepository,
        media_repo: MediaRepository,
        cache_manager: CacheManager
) -> MaintenanceService:
    """Get singleton MaintenanceService instance"""
    return MaintenanceService(user_repo, media_repo, cache_manager)