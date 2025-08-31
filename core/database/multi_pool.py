"""
Multi-database pool manager for handling multiple MongoDB connections
"""

import asyncio
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple, Any

from motor.motor_asyncio import AsyncIOMotorCollection

from core.database.pool import DatabaseConnectionPool
from core.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class DatabaseInfo:
    """Database configuration information"""
    uri: str
    name: str
    pool: Optional[DatabaseConnectionPool] = None
    is_active: bool = True
    size_gb: float = 0.0
    files_count: int = 0


class MultiDatabaseManager:
    """Manager for multiple database connections with automatic failover"""

    _instance: Optional['MultiDatabaseManager'] = None
    _lock = asyncio.Lock()

    def __new__(cls) -> 'MultiDatabaseManager':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self.databases: List[DatabaseInfo] = []
            self.current_write_db_index: int = 0
            self.size_limit_gb: float = 0.5
            self.auto_switch: bool = True
            self._stats_cache: Dict[str, Any] = {}
            self._stats_cache_time: float = 0

    async def initialize(
        self, 
        uris: List[str], 
        names: List[str],
        size_limit_gb: float = 0.5,
        auto_switch: bool = True
    ) -> None:
        """Initialize multiple database connections"""
        async with self._lock:
            if self.databases:  # Already initialized
                return

            self.size_limit_gb = size_limit_gb
            self.auto_switch = auto_switch

            if len(uris) != len(names):
                raise ValueError("Number of URIs and names must match")

            # Initialize database connections
            for i, (uri, name) in enumerate(zip(uris, names)):
                pool = DatabaseConnectionPool()
                # Create a new instance for each database to avoid singleton issues
                pool._instance = None
                pool = DatabaseConnectionPool()
                
                await pool.initialize(uri, name)
                
                db_info = DatabaseInfo(
                    uri=uri,
                    name=name,
                    pool=pool,
                    is_active=True
                )
                
                self.databases.append(db_info)
                logger.info(f"Initialized database {i+1}: {name} ({'Primary' if i == 0 else 'Secondary'})")

            # Update database statistics
            await self._update_database_stats()
            
            logger.info(f"Multi-database manager initialized with {len(self.databases)} databases")

    async def _update_database_stats(self) -> None:
        """Update database size and file count statistics"""
        current_time = asyncio.get_event_loop().time()
        
        # Cache stats for 5 minutes
        if current_time - self._stats_cache_time < 300:
            return

        for db_info in self.databases:
            if not db_info.pool:
                continue
                
            try:
                # Get database size
                stats = await db_info.pool.database.command("dbStats")
                db_info.size_gb = stats.get('dataSize', 0) / (1024 ** 3)  # Convert to GB
                
                # Get files count
                collection = await db_info.pool.get_collection("media_files")
                db_info.files_count = await collection.count_documents({})
                
                logger.debug(f"Database {db_info.name}: {db_info.size_gb:.3f}GB, {db_info.files_count} files")
                
            except Exception as e:
                logger.warning(f"Failed to update stats for database {db_info.name}: {e}")
                db_info.is_active = False

        self._stats_cache_time = current_time

    async def get_write_database(self) -> DatabaseConnectionPool:
        """Get the current database for write operations"""
        await self._update_database_stats()
        
        if self.auto_switch:
            # Check if current database is near limit
            current_db = self.databases[self.current_write_db_index]
            if current_db.size_gb >= self.size_limit_gb and len(self.databases) > 1:
                # Find next available database
                for i in range(len(self.databases)):
                    next_index = (self.current_write_db_index + 1 + i) % len(self.databases)
                    next_db = self.databases[next_index]
                    
                    if next_db.is_active and next_db.size_gb < self.size_limit_gb:
                        self.current_write_db_index = next_index
                        logger.info(f"Switched to database {next_index + 1} ({next_db.name}) for writes")
                        break
                else:
                    logger.warning("All databases are near capacity!")

        return self.databases[self.current_write_db_index].pool

    async def get_all_databases(self) -> List[DatabaseConnectionPool]:
        """Get all active database pools"""
        return [db.pool for db in self.databases if db.is_active and db.pool]

    async def get_database_by_index(self, index: int) -> Optional[DatabaseConnectionPool]:
        """Get database by index"""
        if 0 <= index < len(self.databases) and self.databases[index].is_active:
            return self.databases[index].pool
        return None

    async def get_collection_from_all(self, collection_name: str) -> List[AsyncIOMotorCollection]:
        """Get collection from all active databases"""
        collections = []
        for db_info in self.databases:
            if db_info.is_active and db_info.pool:
                try:
                    collection = await db_info.pool.get_collection(collection_name)
                    collections.append(collection)
                except Exception as e:
                    logger.error(f"Error getting collection from {db_info.name}: {e}")
                    db_info.is_active = False
        return collections

    async def find_file_in_all_databases(
        self, 
        collection_name: str, 
        query: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], Optional[int]]:
        """
        Find a file in all databases
        Returns: (document, database_index) or (None, None)
        """
        for i, db_info in enumerate(self.databases):
            if not db_info.is_active or not db_info.pool:
                continue
                
            try:
                collection = await db_info.pool.get_collection(collection_name)
                document = await collection.find_one(query)
                if document:
                    return document, i
            except Exception as e:
                logger.error(f"Error searching in database {db_info.name}: {e}")
                db_info.is_active = False
                
        return None, None

    async def count_across_all_databases(
        self, 
        collection_name: str, 
        query: Dict[str, Any]
    ) -> int:
        """Count documents across all databases"""
        total_count = 0
        
        tasks = []
        for db_info in self.databases:
            if db_info.is_active and db_info.pool:
                task = self._count_in_database(db_info, collection_name, query)
                tasks.append(task)
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, int):
                    total_count += result
                elif isinstance(result, Exception):
                    logger.error(f"Error counting documents: {result}")
        
        return total_count

    async def _count_in_database(
        self, 
        db_info: DatabaseInfo, 
        collection_name: str, 
        query: Dict[str, Any]
    ) -> int:
        """Count documents in a specific database"""
        try:
            collection = await db_info.pool.get_collection(collection_name)
            return await collection.count_documents(query)
        except Exception as e:
            logger.error(f"Error counting in database {db_info.name}: {e}")
            db_info.is_active = False
            return 0

    async def search_across_all_databases(
        self, 
        collection_name: str, 
        query: Dict[str, Any], 
        limit: int = 10, 
        skip: int = 0,
        sort: Optional[List[Tuple[str, int]]] = None
    ) -> List[Dict[str, Any]]:
        """Search across all databases and return combined results"""
        all_results = []
        
        tasks = []
        for db_info in self.databases:
            if db_info.is_active and db_info.pool:
                task = self._search_in_database(db_info, collection_name, query, limit, skip, sort)
                tasks.append(task)
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, list):
                    all_results.extend(result)
                elif isinstance(result, Exception):
                    logger.error(f"Error searching databases: {result}")
        
        # Sort and limit combined results
        if sort and all_results:
            # Sort combined results
            for sort_field, sort_direction in reversed(sort):
                all_results.sort(
                    key=lambda x: x.get(sort_field, 0), 
                    reverse=(sort_direction == -1)
                )
        
        # Apply skip and limit to combined results
        return all_results[skip:skip + limit]

    async def _search_in_database(
        self, 
        db_info: DatabaseInfo, 
        collection_name: str, 
        query: Dict[str, Any], 
        limit: int, 
        skip: int,
        sort: Optional[List[Tuple[str, int]]] = None
    ) -> List[Dict[str, Any]]:
        """Search in a specific database"""
        try:
            collection = await db_info.pool.get_collection(collection_name)
            cursor = collection.find(query)
            
            if sort:
                cursor = cursor.sort(sort)
                
            # For multi-database search, we get more results from each DB
            # and let the parent method handle final sorting and limiting
            extended_limit = limit + skip
            cursor = cursor.limit(extended_limit)
            
            return await cursor.to_list(length=extended_limit)
        except Exception as e:
            logger.error(f"Error searching in database {db_info.name}: {e}")
            db_info.is_active = False
            return []

    async def get_database_stats(self) -> List[Dict[str, Any]]:
        """Get statistics for all databases"""
        await self._update_database_stats()
        
        stats = []
        for i, db_info in enumerate(self.databases):
            stats.append({
                'index': i,
                'name': db_info.name,
                'is_active': db_info.is_active,
                'is_current_write': i == self.current_write_db_index,
                'size_gb': round(db_info.size_gb, 3),
                'size_limit_gb': self.size_limit_gb,
                'files_count': db_info.files_count,
                'usage_percentage': round((db_info.size_gb / self.size_limit_gb) * 100, 1) if self.size_limit_gb > 0 else 0
            })
        
        return stats

    async def set_write_database(self, index: int) -> bool:
        """Manually set the write database"""
        if 0 <= index < len(self.databases) and self.databases[index].is_active:
            old_index = self.current_write_db_index
            self.current_write_db_index = index
            logger.info(f"Write database switched from {old_index + 1} to {index + 1}")
            return True
        return False

    async def close(self) -> None:
        """Close all database connections"""
        for db_info in self.databases:
            if db_info.pool:
                try:
                    await db_info.pool.close()
                except Exception as e:
                    logger.error(f"Error closing database {db_info.name}: {e}")
        
        self.databases.clear()
        logger.info("Multi-database manager closed")

    @property
    def is_multi_database(self) -> bool:
        """Check if multiple databases are configured"""
        return len(self.databases) > 1

# Global instance
multi_db_pool = MultiDatabaseManager()