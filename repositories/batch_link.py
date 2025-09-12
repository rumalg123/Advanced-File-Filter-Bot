from typing import Dict, Any, Optional, List
from datetime import datetime, UTC
from dataclasses import dataclass, asdict
from enum import Enum

from pymongo import IndexModel, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from core.cache.config import CacheTTLConfig, CacheKeyGenerator
from core.database.base import BaseRepository
from core.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class BatchLink:
    """Batch link entity for premium-only batch links"""
    id: str  # Unique identifier for the batch link
    source_chat_id: int  # Source chat/channel ID
    from_msg_id: int  # Starting message ID
    to_msg_id: int  # Ending message ID
    protected: bool = False  # Whether content should be sent with protect_content=True
    premium_only: bool = False  # Whether link requires premium membership
    created_by: int = 0  # User ID who created the link
    created_at: datetime = None
    expires_at: Optional[datetime] = None  # Optional expiration

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(UTC)


class BatchLinkRepository(BaseRepository[BatchLink]):
    """Repository for batch link operations"""

    def __init__(self, db_pool, cache_manager):
        super().__init__(db_pool, cache_manager, "batch_links")
        self.ttl = CacheTTLConfig()

    def _entity_to_dict(self, batch_link: BatchLink) -> Dict[str, Any]:
        """Convert BatchLink entity to dictionary"""
        data = asdict(batch_link)
        data['_id'] = data.pop('id')
        data['created_at'] = data['created_at'].isoformat()
        if data.get('expires_at'):
            data['expires_at'] = data['expires_at'].isoformat()
        return data

    def _dict_to_entity(self, data: Dict[str, Any]) -> BatchLink:
        """Convert dictionary to BatchLink entity"""
        data['id'] = data.pop('_id')
        if data.get('created_at'):
            if isinstance(data['created_at'], str):
                data['created_at'] = datetime.fromisoformat(data['created_at'])
        if data.get('expires_at'):
            if isinstance(data['expires_at'], str):
                data['expires_at'] = datetime.fromisoformat(data['expires_at'])
        return BatchLink(**data)

    def _get_cache_key(self, batch_id: str) -> str:
        """Get cache key for batch link"""
        return CacheKeyGenerator.batch_link(batch_id)

    async def create_batch_link(self, batch_link: BatchLink) -> bool:
        """Create a new batch link with validation"""
        try:
            # Validate batch link data
            if not self._validate_batch_link(batch_link):
                return False
                
            collection = await self.collection
            data = self._entity_to_dict(batch_link)
            
            await self.db_pool.execute_with_retry(
                collection.insert_one, data
            )
            
            # Cache the batch link
            cache_key = self._get_cache_key(batch_link.id)
            await self.cache.set(cache_key, batch_link, expire=self.ttl.BATCH_LINK)
            
            logger.info(f"Created batch link: {batch_link.id}")
            return True
            
        except DuplicateKeyError:
            logger.warning(f"Duplicate batch link ID: {batch_link.id}")
            return False
        except Exception as e:
            logger.error(f"Error creating batch link: {e}")
            return False
    
    def _validate_batch_link(self, batch_link: BatchLink) -> bool:
        """Validate batch link data integrity"""
        if not batch_link.id or not isinstance(batch_link.id, str):
            logger.error("Invalid batch link ID")
            return False
            
        if not batch_link.source_chat_id or not isinstance(batch_link.source_chat_id, int):
            logger.error("Invalid source chat ID")
            return False
            
        if batch_link.from_msg_id <= 0 or batch_link.to_msg_id <= 0:
            logger.error("Invalid message IDs")
            return False
            
        if batch_link.from_msg_id >= batch_link.to_msg_id:
            logger.error("Invalid message range")
            return False
            
        # Check reasonable batch size
        message_count = batch_link.to_msg_id - batch_link.from_msg_id + 1
        if message_count > 10000:
            logger.error(f"Batch too large: {message_count} messages")
            return False
            
        return True
    
    async def create_indexes(self) -> bool:
        """Create optimized indexes for batch links"""
        try:
            collection = await self.collection
            
            indexes = [
                # Query by creator and creation date
                IndexModel([("created_by", ASCENDING), ("created_at", DESCENDING)]),
                
                # Query by premium status for filtering
                IndexModel([("premium_only", ASCENDING)]),
                
                # Query by source for deduplication
                IndexModel([
                    ("source_chat_id", ASCENDING),
                    ("from_msg_id", ASCENDING),
                    ("to_msg_id", ASCENDING),
                    ("protected", ASCENDING),
                    ("premium_only", ASCENDING)
                ], sparse=True),
                
                # TTL index for expired links (if expires_at is set)
                IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0, sparse=True),
                
                # Query by creation date for cleanup
                IndexModel([("created_at", ASCENDING)])
            ]
            
            await self.db_pool.execute_with_retry(
                collection.create_indexes, indexes
            )
            
            logger.info("Created batch link indexes successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error creating batch link indexes: {e}")
            return False

    async def get_batch_link(self, batch_id: str) -> Optional[BatchLink]:
        """Get batch link by ID"""
        # Try cache first
        cache_key = self._get_cache_key(batch_id)
        cached = await self.cache.get(cache_key)
        if cached:
            return cached if isinstance(cached, BatchLink) else self._dict_to_entity(cached)

        # Try database
        try:
            collection = await self.collection
            data = await self.db_pool.execute_with_retry(
                collection.find_one, {"_id": batch_id}
            )
            
            if data:
                batch_link = self._dict_to_entity(data)
                await self.cache.set(cache_key, batch_link, expire=self.ttl.BATCH_LINK)
                return batch_link
                
        except Exception as e:
            logger.error(f"Error getting batch link {batch_id}: {e}")
            
        return None

    async def delete_batch_link(self, batch_id: str) -> bool:
        """Delete a batch link"""
        try:
            collection = await self.collection
            result = await self.db_pool.execute_with_retry(
                collection.delete_one, {"_id": batch_id}
            )
            
            if result.deleted_count > 0:
                cache_key = self._get_cache_key(batch_id)
                await self.cache.delete(cache_key)
                logger.info(f"Deleted batch link: {batch_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error deleting batch link {batch_id}: {e}")
            
        return False

    async def cleanup_expired_links(self) -> int:
        """Clean up expired batch links"""
        try:
            collection = await self.collection
            now = datetime.now(UTC)
            
            result = await self.db_pool.execute_with_retry(
                collection.delete_many, 
                {"expires_at": {"$lt": now.isoformat()}}
            )
            
            deleted_count = result.deleted_count
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} expired batch links")
                
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error cleaning up expired batch links: {e}")
            return 0

    async def get_user_batch_links(self, user_id: int, limit: int = 10) -> List[BatchLink]:
        """Get batch links created by a user"""
        try:
            collection = await self.collection
            cursor = collection.find({"created_by": user_id}).sort("created_at", -1).limit(limit)
            
            batch_links = []
            async for doc in cursor:
                batch_links.append(self._dict_to_entity(doc))
                
            return batch_links
            
        except Exception as e:
            logger.error(f"Error getting user batch links for {user_id}: {e}")
            return []