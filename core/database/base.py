
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, TypeVar, Generic

from pymongo.errors import DuplicateKeyError

from core.cache.config import CacheTTLConfig
from core.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


class BaseRepository(ABC, Generic[T]):
    """Base repository with common CRUD operations"""

    def __init__(self, db_pool, cache_manager, collection_name: str):
        self.db_pool = db_pool
        self.cache = cache_manager
        self.collection_name = collection_name
        self._collection = None
        self.ttl = CacheTTLConfig()  # Add this

    @property
    async def collection(self):
        """Lazy load collection"""
        if self._collection is None:
            self._collection = await self.db_pool.get_collection(self.collection_name)
        return self._collection

    @abstractmethod
    def _entity_to_dict(self, entity: T) -> Dict[str, Any]:
        """Convert entity to dictionary for storage"""
        pass

    @abstractmethod
    def _dict_to_entity(self, data: Dict[str, Any]) -> T:
        """Convert dictionary to entity"""
        pass

    @abstractmethod
    def _get_cache_key(self, identifier: Any) -> str:
        """Generate cache key for entity"""
        pass

    async def find_by_id(self, id: Any, use_cache: bool = True) -> Optional[T]:
        """Find entity by ID with caching"""
        cache_key = self._get_cache_key(id)

        # Try cache first
        if use_cache:
            cached = await self.cache.get(cache_key)
            if cached:
                return self._dict_to_entity(cached)

        # Fetch from database
        try:
            collection = await self.collection
            data = await self.db_pool.execute_with_retry(
                collection.find_one, {"_id": id}
            )

            if data:
                # Cache the result
                if use_cache:
                    ttl = self._get_ttl_for_collection()
                    await self.cache.set(cache_key, data, expire=ttl)  # 5 minutes
                return self._dict_to_entity(data)
            return None
        except Exception as e:
            logger.error(f"Error finding entity by id {id}: {e}")
            return None

    def _get_ttl_for_collection(self) -> int:
        """Get appropriate TTL based on collection name"""
        collection_ttl_map = {
            'users': self.ttl.USER_DATA,
            'media_files': self.ttl.MEDIA_FILE,
            'connections': self.ttl.USER_CONNECTIONS,
            'filters': self.ttl.FILTER_DATA,
            'indexed_channels': self.ttl.ACTIVE_CHANNELS,
            'bot_settings': self.ttl.BOT_SETTINGS,
        }
        return collection_ttl_map.get(self.collection_name, 300)  # Default 5 minutes


    async def find_many(
            self,
            filter: Dict[str, Any],
            limit: Optional[int] = None,
            skip: int = 0,
            sort: Optional[List[tuple]] = None
    ) -> List[T]:
        """Find multiple entities"""
        try:
            collection = await self.collection
            cursor = collection.find(filter)

            if sort:
                cursor = cursor.sort(sort)
            if skip:
                cursor = cursor.skip(skip)
            if limit:
                cursor = cursor.limit(limit)

            results = await cursor.to_list(length=limit)
            return [self._dict_to_entity(data) for data in results]
        except Exception as e:
            logger.error(f"Error finding entities: {e}")
            return []

    async def create(self, entity: T) -> bool:
        """Create new entity"""
        try:
            data = self._entity_to_dict(entity)
            collection = await self.collection

            await self.db_pool.execute_with_retry(
                collection.insert_one, data
            )

            # Invalidate cache
            cache_key = self._get_cache_key(data.get('_id'))
            await self.cache.delete(cache_key)

            return True
        except DuplicateKeyError as e:
            # Re-raise DuplicateKeyError to handle it at a higher level
            raise e
        except Exception as e:
            logger.error(f"Error creating entity: {e}")
            return False

    async def update(
            self,
            id: Any,
            update_data: Dict[str, Any],
            upsert: bool = False
    ) -> bool:
        """Update entity"""
        try:
            collection = await self.collection

            result = await self.db_pool.execute_with_retry(
                collection.update_one,
                {"_id": id},
                {"$set": update_data},
                upsert=upsert
            )

            # Invalidate cache
            cache_key = self._get_cache_key(id)
            await self.cache.delete(cache_key)

            return result.modified_count > 0 or (upsert and result.upserted_id)
        except Exception as e:
            logger.error(f"Error updating entity {id}: {e}")
            return False

    async def delete(self, id: Any) -> bool:
        """Delete entity"""
        logger.info("Inside base.py delete")
        try:
            entity = await self.find_by_id(id, use_cache=False)

            collection = await self.collection

            result = await self.db_pool.execute_with_retry(
                collection.delete_one, {"_id": id}
            )

            # Invalidate cache
            if result.deleted_count > 0:
                # Clear all possible cache entries
                cache_key = self._get_cache_key(id)
                await self.cache.delete(cache_key)

                # For MediaRepository, also clear file_ref cache
                if hasattr(entity, 'file_ref') and entity.file_ref:
                    ref_cache_key = self._get_cache_key(entity.file_ref)
                    await self.cache.delete(ref_cache_key)
                if hasattr(entity, 'file_unique_id') and entity.file_unique_id:
                    unique_id = self._get_cache_key(entity.file_unique_id)
                    await self.cache.delete(unique_id)
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting entity {id}: {e}")
            return False

    async def count(self, filter: Dict[str, Any] = None) -> int:
        """Count entities"""
        try:
            collection = await self.collection
            filter = filter or {}

            return await self.db_pool.execute_with_retry(
                collection.count_documents, filter
            )
        except Exception as e:
            logger.error(f"Error counting entities: {e}")
            return 0

    async def bulk_write(self, operations: List[Any]) -> bool:
        """Perform bulk write operations"""
        try:
            if not operations:
                return True

            collection = await self.collection
            result = await self.db_pool.execute_with_retry(
                collection.bulk_write, operations
            )

            logger.info(f"Bulk write completed: {result.bulk_api_result}")
            return True
        except Exception as e:
            logger.error(f"Error in bulk write: {e}")
            return False

    async def create_index(self, keys: List[tuple], **kwargs) -> bool:
        """Create index on collection"""
        try:
            collection = await self.collection
            await collection.create_index(keys, **kwargs)
            return True
        except Exception as e:
            logger.error(f"Error creating index: {e}")
            return False


class AggregationMixin:
    """Mixin for aggregation operations"""

    @property
    async def collection(self):
        """Get collection - must be implemented by inheriting class"""
        if hasattr(self, '_collection') and self._collection:
            return self._collection
        raise NotImplementedError("Collection property must be implemented")

    async def aggregate(self, pipeline: List[Dict[str, Any]], limit: Optional[int] = 1000) -> List[Dict[str, Any]]:
        """Execute aggregation pipeline with memory protection"""
        try:
            collection = await self.collection
            cursor = collection.aggregate(pipeline)
            return await cursor.to_list(length=limit)
        except Exception as e:
            logger.error(f"Error in aggregation: {e}")
            return []

    async def distinct(self, field: str, filter: Dict[str, Any] = None) -> List[Any]:
        """Get distinct values for a field"""
        try:
            collection = await self.collection
            filter = filter or {}
            return await collection.distinct(field, filter)
        except Exception as e:
            logger.error(f"Error getting distinct values: {e}")
            return []