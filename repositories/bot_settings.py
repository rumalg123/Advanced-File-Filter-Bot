from typing import Dict, Any, Optional
from datetime import datetime, UTC
from dataclasses import dataclass, asdict
from pymongo import UpdateOne

from core.cache.config import CacheKeyGenerator
from core.database.base import BaseRepository
from core.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class BotSetting:
    """Bot setting entity"""
    key: str
    value: Any
    value_type: str  # 'str', 'int', 'bool', 'list'
    default_value: Any
    description: str
    updated_at: datetime = None

    def __post_init__(self):
        if self.updated_at is None:
            self.updated_at = datetime.now(UTC)


class BotSettingsRepository(BaseRepository[BotSetting]):
    """Repository for bot settings operations"""

    def __init__(self, db_pool, cache_manager):
        super().__init__(db_pool, cache_manager, "bot_settings")

    def _entity_to_dict(self, setting: BotSetting) -> Dict[str, Any]:
        """Convert BotSetting entity to dictionary"""
        data = asdict(setting)
        data['_id'] = data.pop('key')
        data['updated_at'] = data['updated_at'].isoformat()
        return data

    def _dict_to_entity(self, data: Dict[str, Any]) -> BotSetting:
        """Convert dictionary to BotSetting entity"""
        data['key'] = data.pop('_id')
        if data.get('updated_at') and isinstance(data['updated_at'], str):
            data['updated_at'] = datetime.fromisoformat(data['updated_at'])
        return BotSetting(**data)

    def _get_cache_key(self, key: str) -> str:
        """Generate cache key for setting"""
        return f"bot_setting:{key}"

    def _infer_value_type(self, value: Any) -> str:
        """Infer a simple value_type from the Python value."""
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int) and not isinstance(value, bool):
            return "int"
        if isinstance(value, (list, tuple)):
            return "list"
        return "str"

    async def get_setting(self, key: str) -> Optional[BotSetting]:
        """Get a setting by key"""
        return await self.find_by_id(key)

    async def set_setting(self, key: str, value: Any, value_type: str,
                          default_value: Any = None, description: str = "") -> bool:
        """Set or update a setting"""
        setting = BotSetting(
            key=key,
            value=value,
            value_type=value_type,
            default_value=default_value,
            description=description
        )

        # Use upsert to create or update
        success = await self.update(
            key,
            self._entity_to_dict(setting),
            upsert=True
        )

        # Clear cache
        if success:
            cache_key = CacheKeyGenerator.bot_setting(key)
            await self.cache.delete(cache_key)

        return success

    async def get_all_settings(self) -> Dict[str, Any]:
        """Get all settings as a dictionary"""
        settings = await self.find_many({})
        return {setting.key: setting for setting in settings}

    async def reset_to_default(self, key: str) -> bool:
        """Reset a setting to its default value"""
        setting = await self.get_setting(key)
        if not setting:
            return False

        return await self.set_setting(
            key=key,
            value=setting.default_value,
            value_type=setting.value_type,
            default_value=setting.default_value,
            description=setting.description
        )

    async def bulk_upsert(self, settings: Dict[str, Dict[str, Any]]) -> bool:
        """Bulk upsert settings"""
        operations = []
        for key, data in settings.items():
            setting = BotSetting(
                key=key,
                value=data['value'],
                value_type=data['type'],
                default_value=data['default'],
                description=data.get('description', '')
            )
            operations.append(
                UpdateOne(
                    {'_id': key},
                    {'$set': self._entity_to_dict(setting)},
                    upsert=True
                )
            )

        if operations:
            collection = await self.collection
            await collection.bulk_write(operations)

            # Clear all setting caches
            for key in settings:
                cache_key = CacheKeyGenerator.bot_setting(key)
                await self.cache.delete(cache_key)

        return True

    async def update_setting(
            self,
            key: str,
            value: Any,
            description: Optional[str] = None
    ) -> bool:
        """
        Update the value (and optionally description) of an existing setting.
        If the setting doesn't exist, create it, inferring value_type.
        """
        existing = await self.get_setting(key)
        now = datetime.now(UTC)

        if existing:
            update_doc = {
                "$set": {
                    "value": value,
                    "updated_at": now.isoformat(),
                }
            }
            if description is not None:
                update_doc["$set"]["description"] = description

            collection = await self.collection
            result = await collection.update_one({"_id": key}, update_doc)
            success = bool(result.matched_count)

        else:
            # Create with inferred type and provided description (or empty)
            success = await self.set_setting(
                key=key,
                value=value,
                value_type=self._infer_value_type(value),
                default_value=None,
                description=description or ""
            )

        if success:
            # Invalidate cache for this key
            cache_key = CacheKeyGenerator.bot_setting(key)
            await self.cache.delete(cache_key)

        return success