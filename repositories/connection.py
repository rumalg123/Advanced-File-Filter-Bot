from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from typing import Dict, Any, Optional, List

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from core.cache.config import CacheTTLConfig, CacheKeyGenerator
from core.cache.invalidation import CacheInvalidator
from core.database.base import BaseRepository
from core.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class UserConnection:
    """User connection document structure"""
    user_id: str
    group_details: List[Dict[str, str]]
    active_group: Optional[str]
    created_at: datetime = None
    updated_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(UTC)
        if self.updated_at is None:
            self.updated_at = datetime.now(UTC)


class ConnectionRepository(BaseRepository[UserConnection]):
    """Repository for connection operations"""

    def __init__(self, db_pool, cache_manager):
        super().__init__(db_pool, cache_manager, "connections")
        self.ttl = CacheTTLConfig()  # 5 minutes
        self.cache_invalidator = CacheInvalidator(cache_manager)

    def _entity_to_dict(self, conn: UserConnection) -> Dict[str, Any]:
        """Convert UserConnection entity to dictionary"""
        data = asdict(conn)
        data['_id'] = data.pop('user_id')
        data['created_at'] = data['created_at'].isoformat()
        data['updated_at'] = data['updated_at'].isoformat()
        return data

    def _dict_to_entity(self, data: Dict[str, Any]) -> UserConnection:
        """Convert dictionary to UserConnection entity"""
        data['user_id'] = str(data.pop('_id'))
        if data.get('created_at') and isinstance(data['created_at'], str):
            data['created_at'] = datetime.fromisoformat(data['created_at'])
        if data.get('updated_at') and isinstance(data['updated_at'], str):
            data['updated_at'] = datetime.fromisoformat(data['updated_at'])
        return UserConnection(**data)

    def _get_cache_key(self, user_id: str) -> str:
        """Use centralized key generator"""
        return CacheKeyGenerator.user_connections(user_id)

    async def add_connection(self, user_id: str, group_id: str) -> bool:
        """Add a new connection for user"""
        user_id = str(user_id)
        group_id = str(group_id)

        collection = await self.get_collection()
        now = datetime.now(UTC).isoformat()
        predicate = {"_id": user_id, "group_details.group_id": {"$ne": group_id}}
        update = {
            "$addToSet": {"group_details": {"group_id": group_id}},
            "$set": {"active_group": group_id, "updated_at": now},
            "$setOnInsert": {"created_at": now},
        }
        try:
            result = await collection.update_one(predicate, update, upsert=True)
        except DuplicateKeyError:
            # An existing group or concurrent first insert owns this user's _id.
            result = await collection.update_one(predicate, update, upsert=False)
        success = bool(result.matched_count or result.upserted_id is not None)
        if success:
            await self.cache_invalidator.invalidate_connection_cache(user_id)
        return success

    async def get_active_connection(self, user_id: str) -> Optional[str]:
        """Get the active group from the stable, full connection entity cache."""
        user_id = str(user_id)
        user_conn = await self.find_by_id(user_id)
        return user_conn.active_group if user_conn else None

    async def get_all_connections(self, user_id: str) -> Optional[List[str]]:
        """Get all connections for user"""
        user_id = str(user_id)
        user_conn = await self.find_by_id(user_id)

        if not user_conn:
            return None

        return [g["group_id"] for g in user_conn.group_details]

    async def is_active(self, user_id: str, group_id: str) -> bool:
        """Check if a group is active for user"""
        user_id = str(user_id)
        group_id = str(group_id)

        active_group = await self.get_active_connection(user_id)
        return active_group == group_id

    async def make_active(self, user_id: str, group_id: str) -> bool:
        """Make a group active for user"""
        user_id = str(user_id)
        group_id = str(group_id)

        collection = await self.get_collection()
        result = await collection.update_one(
            {"_id": user_id, "group_details.group_id": group_id},
            {"$set": {"active_group": group_id, "updated_at": datetime.now(UTC).isoformat()}},
        )
        success = bool(result.matched_count)
        if success:
            await self.cache_invalidator.invalidate_connection_cache(user_id)
        return success

    async def make_inactive(self, user_id: str) -> bool:
        """Make all connections inactive for user"""
        user_id = str(user_id)

        success = await self.update(
            user_id,
            {
                "active_group": None,
                "updated_at": datetime.now(UTC)
            }
        )

        if success:
            # Invalidate cache
            await self.cache_invalidator.invalidate_connection_cache(user_id)

        return success

    async def delete_connection(self, user_id: str, group_id: str) -> bool:
        """Delete a connection for user"""
        user_id = str(user_id)
        group_id = str(group_id)

        collection = await self.get_collection()
        previous = await collection.find_one_and_update(
            {"_id": user_id, "group_details.group_id": group_id},
            [
                {"$set": {"group_details": {"$filter": {
                    "input": "$group_details", "as": "group",
                    "cond": {"$ne": ["$$group.group_id", group_id]},
                }}}},
                {"$set": {
                    "active_group": {"$cond": [
                        {"$eq": ["$active_group", group_id]},
                        {"$ifNull": [{"$arrayElemAt": ["$group_details.group_id", -1]}, None]},
                        "$active_group",
                    ]},
                    "updated_at": datetime.now(UTC).isoformat(),
                }},
            ],
            return_document=ReturnDocument.BEFORE,
        )
        if previous is None:
            return False

        # The pre-update document is only used to describe the committed change.
        user_conn = self._dict_to_entity(previous)
        user_conn.group_details = [g for g in user_conn.group_details if g["group_id"] != group_id]
        if user_conn.active_group == group_id:
            if user_conn.group_details:
                user_conn.active_group = user_conn.group_details[-1]["group_id"]
                logger.info(f"Active group changed from {group_id} to {user_conn.active_group} for user {user_id}")
            else:
                logger.info(f"No active groups left for user {user_id}")
        await self.cache_invalidator.invalidate_connection_cache(user_id)
        await self.cache_invalidator.invalidate_filter_cache(group_id)
        logger.info(f"Deleted connection {group_id} for user {user_id}")
        return True

    async def delete_all_connections(self, user_id: str) -> bool:
        """Delete all connections for user"""
        user_id = str(user_id)

        success = await self.delete(user_id)

        if success:
            # Invalidate caches
            await self.cache_invalidator.invalidate_connection_cache(user_id)

        return success


    async def deactivate_all_connections(self, user_id: str) -> bool:
        """Deactivate all connections for a user"""
        user_id = str(user_id)

        success = await self.update(
            user_id,
            {
                "active_group": None,
                "updated_at": datetime.now(UTC)
            }
        )

        if success:
            # Invalidate cache
            await self.cache_invalidator.invalidate_connection_cache(user_id)

        return success


