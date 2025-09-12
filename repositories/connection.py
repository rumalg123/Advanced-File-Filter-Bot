from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from typing import Dict, Any, Optional, List

from core.cache.config import CacheTTLConfig, CacheKeyGenerator
from core.cache.invalidation import CacheInvalidator
from core.database.base import BaseRepository, AggregationMixin
from core.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Connection:
    """Connection entity for user-group connections"""
    user_id: str
    group_id: str
    is_active: bool = False
    created_at: datetime = None
    updated_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(UTC)
        if self.updated_at is None:
            self.updated_at = datetime.now(UTC)


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


class ConnectionRepository(BaseRepository[UserConnection], AggregationMixin):
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

        # Get existing connections
        user_conn = await self.find_by_id(user_id)

        if user_conn:
            # Check if already connected
            group_ids = [g["group_id"] for g in user_conn.group_details]
            if group_id in group_ids:
                return False

            # Add new group
            user_conn.group_details.append({"group_id": group_id})
            user_conn.active_group = group_id
            user_conn.updated_at = datetime.now(UTC)

            # Update
            return await self.update(
                user_id,
                {
                    "group_details": user_conn.group_details,
                    "active_group": group_id,
                    "updated_at": user_conn.updated_at
                }
            )
        else:
            # Create new connection
            user_conn = UserConnection(
                user_id=user_id,
                group_details=[{"group_id": group_id}],
                active_group=group_id
            )
            success = await self.create(user_conn)
            return success

    async def get_active_connection(self, user_id: str) -> Optional[str]:
        """Get active connection with proper caching"""
        cache_key = CacheKeyGenerator.user_connections(user_id)
        cached = await self.cache.get(cache_key)
        if cached:
            return cached.get('active_group')

        user_conn = await self.find_by_id(user_id)
        if user_conn:
            await self.cache.set(
                cache_key,
                {'active_group': user_conn.active_group},
                expire=self.ttl.USER_CONNECTIONS
            )
            return user_conn.active_group
        return None

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

        user_conn = await self.find_by_id(user_id)
        if not user_conn:
            return False

        # Check if user has this group
        group_ids = [g["group_id"] for g in user_conn.group_details]
        if group_id not in group_ids:
            return False

        # Update active group
        success = await self.update(
            user_id,
            {
                "active_group": group_id,
                "updated_at": datetime.now(UTC)
            }
        )

        if success:
            # Invalidate cache
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

        user_conn = await self.find_by_id(user_id)
        if not user_conn:
            return False

        # Remove group from list
        original_count = len(user_conn.group_details)
        user_conn.group_details = [
            g for g in user_conn.group_details if g["group_id"] != group_id
        ]

        if len(user_conn.group_details) == original_count:
            return False  # Group not found

        # Update active group if needed
        if user_conn.active_group == group_id:
            if user_conn.group_details:
                # Set to last group
                user_conn.active_group = user_conn.group_details[-1]["group_id"]
                logger.info(f"Active group changed from {group_id} to {user_conn.active_group} for user {user_id}")
            else:
                user_conn.active_group = None
                logger.info(f"No active groups left for user {user_id}")

        # Update database
        success = await self.update(
            user_id,
            {
                "group_details": user_conn.group_details,
                "active_group": user_conn.active_group,
                "updated_at": datetime.now(UTC)
            }
        )

        if success:
            # Invalidate caches
            await self.cache_invalidator.invalidate_connection_cache(user_id)
            filter_cache_key = CacheKeyGenerator.filter_list(group_id)
            await self.cache.delete(filter_cache_key)

            logger.info(f"Deleted connection {group_id} for user {user_id}")

        return success

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


