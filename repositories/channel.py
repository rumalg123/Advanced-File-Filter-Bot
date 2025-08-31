from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from typing import Dict, Any, Optional, List

from core.cache.config import CacheKeyGenerator
from core.cache.invalidation import CacheInvalidator
from core.database.base import BaseRepository
from core.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Channel:
    """Channel entity for automatic indexing"""
    channel_id: int
    channel_username: Optional[str] = None
    channel_title: Optional[str] = None
    added_by: int = None
    enabled: bool = True
    indexed_count: int = 0
    last_indexed_at: Optional[datetime] = None
    created_at: datetime = None
    updated_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(UTC)
        if self.updated_at is None:
            self.updated_at = datetime.now(UTC)


class ChannelRepository(BaseRepository[Channel]):
    """Repository for channel operations"""

    def __init__(self, db_pool, cache_manager):
        super().__init__(db_pool, cache_manager, "indexed_channels")
        self.channels_cache_ttl = 600  # 10 minutes
        self.cache_invalidator = CacheInvalidator(cache_manager)

    def _entity_to_dict(self, channel: Channel) -> Dict[str, Any]:
        """Convert Channel entity to dictionary"""
        data = asdict(channel)
        data['_id'] = data.pop('channel_id')
        # Convert datetime to ISO format
        if data.get('last_indexed_at'):
            data['last_indexed_at'] = data['last_indexed_at'].isoformat()
        data['created_at'] = data['created_at'].isoformat()
        data['updated_at'] = data['updated_at'].isoformat()
        return data

    def _dict_to_entity(self, data: Dict[str, Any]) -> Channel:
        """Convert dictionary to Channel entity"""
        data['channel_id'] = data.pop('_id')
        # Parse datetime
        if data.get('last_indexed_at'):
            if isinstance(data['last_indexed_at'], str):
                data['last_indexed_at'] = datetime.fromisoformat(data['last_indexed_at'])
        if data.get('created_at') and isinstance(data['created_at'], str):
            data['created_at'] = datetime.fromisoformat(data['created_at'])
        if data.get('updated_at') and isinstance(data['updated_at'], str):
            data['updated_at'] = datetime.fromisoformat(data['updated_at'])
        return Channel(**data)

    def _get_cache_key(self, channel_id: int) -> str:
        """Generate cache key for channel"""
        return CacheKeyGenerator.channel(channel_id)

    async def add_channel(
            self,
            channel_id: int,
            channel_username: Optional[str] = None,
            channel_title: Optional[str] = None,
            added_by: int = None
    ) -> bool:
        """Add a channel for automatic indexing"""
        # Check if already exists
        existing = await self.find_by_id(channel_id)
        if existing:
            # Update existing channel
            return await self.update(
                channel_id,
                {
                    'enabled': True,
                    'channel_username': channel_username or existing.channel_username,
                    'channel_title': channel_title or existing.channel_title,
                    'updated_at': datetime.now(UTC)
                }
            )

        # Create new channel
        channel = Channel(
            channel_id=channel_id,
            channel_username=channel_username,
            channel_title=channel_title,
            added_by=added_by
        )

        success = await self.create(channel)

        if success:
            # Invalidate channels list cache
            await self.cache_invalidator.invalidate_channels_cache()

        return success

    async def remove_channel(self, channel_id: int) -> bool:
        """Remove a channel from automatic indexing"""
        success = await self.delete(channel_id)
        logger.info(f"channel repo remove channel {success}")


        if success:
            # Invalidate channels list cache
            await self.cache_invalidator.invalidate_channels_cache()


        return success

    async def get_active_channels(self) -> List[Channel]:
        """Get all active channels for indexing"""
        # Try cache first
        cache_key = CacheKeyGenerator.active_channels()
        cached = await self.cache.get(cache_key)
        if cached:
            return [self._dict_to_entity(ch) for ch in cached]

        # Fetch from database
        channels = await self.find_many(
            {'enabled': True},
            sort=[('created_at', 1)]
        )

        # Cache the result
        await self.cache.set(
            cache_key,
            [self._entity_to_dict(ch) for ch in channels],
            expire=self.channels_cache_ttl
        )

        return channels

    async def get_all_channels(self) -> List[Channel]:
        """Get all channels (including disabled)"""
        return await self.find_many({}, sort=[('created_at', -1)])

    async def update_channel_status(self, channel_id: int, enabled: bool) -> bool:
        """Enable or disable a channel"""
        success = await self.update(
            channel_id,
            {
                'enabled': enabled,
                'updated_at': datetime.now(UTC)
            }
        )

        if success:
            await self.cache_invalidator.invalidate_channels_cache()

        return success

    async def update_indexed_count(self, channel_id: int) -> bool:
        """Increment indexed count and update last indexed time"""
        channel = await self.find_by_id(channel_id)
        if not channel:
            return False

        return await self.update(
            channel_id,
            {
                'indexed_count': channel.indexed_count + 1,
                'last_indexed_at': datetime.now(UTC),
                'updated_at': datetime.now(UTC)
            }
        )

    async def get_channel_stats(self) -> Dict[str, Any]:
        """Get channel statistics"""
        channels = await self.get_all_channels()

        active_channels = [ch for ch in channels if ch.enabled]
        total_indexed = sum(ch.indexed_count for ch in channels)

        return {
            'total_channels': len(channels),
            'active_channels': len(active_channels),
            'disabled_channels': len(channels) - len(active_channels),
            'total_files_indexed': total_indexed,
            'channels': channels
        }

