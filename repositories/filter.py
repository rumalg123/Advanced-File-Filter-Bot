# repositories/filter.py
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Dict, Any, Optional, List, Tuple

from core.cache.config import CacheTTLConfig, CacheKeyGenerator
from core.database.base import BaseRepository
from core.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Filter:
    """Filter entity"""
    text: str
    reply: str
    btn: str
    file: str
    alert: Optional[str] = None
    group_id: Optional[str] = None
    created_at: datetime = None
    updated_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(UTC)
        if self.updated_at is None:
            self.updated_at = datetime.now(UTC)


class FilterRepository(BaseRepository[Filter]):
    """Repository for filter operations"""

    def __init__(self, db_pool, cache_manager, collection_name: str = "filters", collection_prefix="filters"):
        super().__init__(db_pool, cache_manager, collection_name)
        self.ttl = CacheTTLConfig()
        self.db_pool = db_pool
        self.cache = cache_manager
        self.collection_prefix = collection_prefix
        self._collections = {}

    async def get_collection(self, group_id: str = None):
        """Get collection for specific group"""
        collection_name = f"{self.collection_prefix}_{group_id}" if group_id else "global_filters"

        if collection_name not in self._collections:
            db = self.db_pool.database
            self._collections[collection_name] = db[collection_name]

            # Create text index
            collection = self._collections[collection_name]
            await collection.create_index([('text', 'text')])

        return self._collections[collection_name]

    def _entity_to_dict(self, filter_obj: Filter) -> Dict[str, Any]:
        """Convert Filter entity to dictionary"""
        return {
            'text': filter_obj.text,
            'reply': filter_obj.reply,
            'btn': filter_obj.btn,
            'file': filter_obj.file,
            'alert': filter_obj.alert,
            'created_at': filter_obj.created_at.isoformat(),
            'updated_at': filter_obj.updated_at.isoformat()
        }

    def _dict_to_entity(self, data: Dict[str, Any]) -> Filter:
        """Convert dictionary to Filter entity"""
        if data.get('created_at') and isinstance(data['created_at'], str):
            data['created_at'] = datetime.fromisoformat(data['created_at'])
        if data.get('updated_at') and isinstance(data['updated_at'], str):
            data['updated_at'] = datetime.fromisoformat(data['updated_at'])

        return Filter(
            text=data['text'],
            reply=data['reply'],
            btn=data['btn'],
            file=data['file'],
            alert=data.get('alert'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at')
        )

    def _get_cache_key(self, identifier: Any) -> str:
        """Override to use centralized key generator"""
        if isinstance(identifier, tuple) and len(identifier) == 2:
            group_id, text = identifier
            return CacheKeyGenerator.filter(group_id, text)
        return f"filter:{identifier}"

    async def add_filter(self, group_id: str, text: str, reply: str,
                         btn: str, file: str, alert: str = None) -> bool:
        """Add or update a filter"""
        collection = await self.get_collection(group_id)

        filter_obj = Filter(
            text=text,
            reply=reply,
            btn=btn,
            file=file,
            alert=alert,
            group_id=group_id
        )

        data = self._entity_to_dict(filter_obj)

        try:
            await collection.update_one(
                {'text': text},
                {"$set": data},
                upsert=True
            )

            # Invalidate cache
            cache_key = CacheKeyGenerator.filter(group_id, text)
            await self.cache.delete(cache_key)

            # Invalidate list cache
            list_cache_key = CacheKeyGenerator.filter_list(group_id)
            await self.cache.delete(list_cache_key)

            return True
        except Exception as e:
            logger.error(f'Error adding filter: {e}')
            return False

    async def find_filter(self, group_id: str, text: str) -> Tuple[Any, Any, Any, Any]:
        """Find a filter by text"""
        cache_key = CacheKeyGenerator.filter(group_id, text)

        # Try cache first
        cached = await self.cache.get(cache_key)
        if cached:
            return (
                cached.get('reply'),
                cached.get('btn'),
                cached.get('alert'),
                cached.get('file')
            )

        collection = await self.get_collection(group_id)

        try:
            doc = await collection.find_one({"text": text})
            if not doc:
                return None, None, None, None

            # Cache the result
            await self.cache.set(cache_key, {
                'reply': doc.get('reply'),
                'btn': doc.get('btn'),
                'alert': doc.get('alert'),
                'file': doc.get('file')
            }, expire=self.ttl.FILTER_DATA)

            return (
                doc.get('reply'),
                doc.get('btn'),
                doc.get('alert'),
                doc.get('file')
            )
        except Exception as e:
            logger.error(f"Error finding filter: {e}")
            return None, None, None, None

    async def get_filters(self, group_id: str) -> List[str]:
        """Get all filter texts for a group"""
        cache_key = CacheKeyGenerator.filter_list(group_id)

        # Try cache first
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        collection = await self.get_collection(group_id)
        texts = []

        try:
            cursor = collection.find({})
            async for doc in cursor:
                text_value = doc.get('text')
                if text_value:
                    texts.append(text_value)

            # Cache the result
            await self.cache.set(cache_key, texts, expire=self.ttl.FILTER_LIST)

            return texts
        except Exception as e:
            logger.error(f"Error getting filters: {e}")
            return []

    async def delete_filter(self, group_id: str, text: str) -> int:
        """Delete a filter"""
        collection = await self.get_collection(group_id)

        try:
            result = await collection.delete_one({'text': text})

            if result.deleted_count:
                # Invalidate caches
                cache_key = CacheKeyGenerator.filter(group_id, text)
                await self.cache.delete(cache_key)

                list_cache_key = CacheKeyGenerator.filter_list(group_id)
                await self.cache.delete(list_cache_key)

            return result.deleted_count
        except Exception as e:
            logger.error(f"Error deleting filter: {e}")
            return 0

    async def delete_all_filters(self, group_id: str) -> bool:
        """Delete all filters for a group"""
        try:
            collection = await self.get_collection(group_id)
            await collection.drop()

            # Clear cache
            list_cache_key = CacheKeyGenerator.filter_list(group_id)
            await self.cache.delete(list_cache_key)

            return True
        except Exception as e:
            logger.error(f"Error deleting all filters: {e}")
            return False

    async def count_filters(self, group_id: str) -> int:
        """Count filters for a group"""
        collection = await self.get_collection(group_id)

        try:
            count = await collection.count_documents({})
            return count
        except Exception as e:
            logger.error(f"Error counting filters: {e}")
            return 0