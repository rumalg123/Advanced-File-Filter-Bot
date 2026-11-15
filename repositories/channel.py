from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from typing import Dict, Any, Optional, List
import asyncio

from pymongo import UpdateOne, UpdateMany

from core.cache.config import CacheTTLConfig, CacheKeyGenerator
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
        self.ttl = CacheTTLConfig()
        self.cache_invalidator = CacheInvalidator(cache_manager)
        self._configuration_lock = asyncio.Lock()

    @staticmethod
    def normalize_channel_ids(value) -> List[int]:
        from core.utils.subscription_config import parse_subscription_targets
        targets = parse_subscription_targets(value)
        if any(not isinstance(target, int) for target in targets):
            raise ValueError('Use numeric channel IDs for Indexing Channels; /add_channel also accepts @usernames.')
        return targets

    async def seed_channels(self, value) -> None:
        """Import missing bootstrap IDs without reviving a disabled source."""
        ids = self.normalize_channel_ids(value)
        async with self._configuration_lock:
            collection = await self.collection()
            for channel in ids:
                channel_id = channel
                data = self._entity_to_dict(Channel(channel_id=channel_id))
                try:
                    await self.db_pool.execute_with_retry(
                        collection.update_one, {'_id': channel_id}, {'$setOnInsert': data}, upsert=True
                    )
                except Exception as e:
                    logger.error(f"Error adding channel {channel} from config: {e}")
                    raise
                await self.cache.delete(self._get_cache_key(channel_id))
            await self.cache_invalidator.invalidate_channels_cache()

    async def get_active_channel_ids(self) -> List[int]:
        """The persisted registry is authoritative for every configuration UI."""
        async with self._configuration_lock:
            channels = await self.find_many({'enabled': True}, sort=[('_id', 1)], raise_on_error=True)
        return [channel.channel_id for channel in channels]

    async def replace_active_channels(self, value) -> bool:
        """Apply an explicit settings edit, preserving history for disabled IDs."""
        ids = self.normalize_channel_ids(value)
        async with self._configuration_lock:
            try:
                collection = await self.collection()
                now = datetime.now(UTC).isoformat()
                operations = [UpdateMany({'enabled': True, '_id': {'$nin': ids}},
                                         {'$set': {'enabled': False, 'updated_at': now}})]
                for channel_id in ids:
                    data = self._entity_to_dict(Channel(channel_id=channel_id))
                    data.pop('_id')
                    data.pop('enabled')
                    data.pop('updated_at')
                    operations.append(UpdateOne({'_id': channel_id}, {
                        '$set': {'enabled': True, 'updated_at': now}, '$setOnInsert': data
                    }, upsert=True))
                await self.db_pool.execute_with_retry(collection.bulk_write, operations)
                await self.cache.delete_pattern('channel:*')
                await self.cache_invalidator.invalidate_channels_cache()
                return True
            except Exception as error:
                logger.error('Failed to apply indexing channels: %s', error, exc_info=True)
                return False

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
        async with self._configuration_lock:
            return await self._add_channel(channel_id, channel_username, channel_title, added_by)

    async def _add_channel(self, channel_id, channel_username, channel_title, added_by):
        # Check if already exists
        existing = await self.find_by_id(channel_id)
        if existing:
            # Update existing channel
            success = await self.update(
                channel_id,
                {
                    'enabled': True,
                    'channel_username': channel_username or existing.channel_username,
                    'channel_title': channel_title or existing.channel_title,
                    'updated_at': datetime.now(UTC)
                }
            )
            if success:
                await self.cache_invalidator.invalidate_channels_cache()
            return success

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
        # Retain a disabled record so a stale environment/bootstrap list cannot
        # silently re-add the source on the next restart.
        return await self.update_channel_status(channel_id, False)

    async def get_active_channels(self) -> List[Channel]:
        """Get all active channels for indexing"""
        # Try cache first
        cache_key = CacheKeyGenerator.active_channels()
        cached = await self.cache.get(cache_key)
        if cached is not None:
            try:
                return [self._dict_to_entity(ch) for ch in cached]
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"Invalid active-channel cache entry: {e}")
                await self.cache_invalidator.invalidate_channels_cache()

        # Fetch from database
        channels = await self.find_many(
            {'enabled': True},
            sort=[('created_at', 1)]
        )

        # Cache the result
        await self.cache.set(
            cache_key,
            [self._entity_to_dict(ch) for ch in channels],
            expire=self.ttl.ACTIVE_CHANNELS
        )

        return channels

    async def get_all_channels(self) -> List[Channel]:
        """Get all channels (including disabled)"""
        return await self.find_many({}, sort=[('created_at', -1)])

    async def update_channel_status(self, channel_id: int, enabled: bool) -> bool:
        """Enable or disable a channel"""
        async with self._configuration_lock:
            return await self._update_channel_status(channel_id, enabled)

    async def _update_channel_status(self, channel_id: int, enabled: bool) -> bool:
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
            logger.warning(f"Cannot update indexed count: channel {channel_id} not found")
            return False

        success = await self.update(
            channel_id,
            {
                'indexed_count': channel.indexed_count + 1,
                'last_indexed_at': datetime.now(UTC),
                'updated_at': datetime.now(UTC)
            }
        )
        if success:
            await self.cache_invalidator.invalidate_channels_cache()
        return success

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

