from typing import Dict, Any, List, Optional, Tuple
import os

from core.cache.redis_cache import CacheManager
from repositories.bot_settings import BotSettingsRepository
from core.utils.logger import get_logger

logger = get_logger(__name__)


class BotSettingsService:
    """Service for managing bot settings"""

    # Define all configurable settings with their metadata
    SETTINGS_METADATA = {
        'PORT': {
            'type': 'int',
            'default': 8000,
            'description': 'Web server port',
            'category': 'server'
        },
        'CACHE_TIME': {
            'type': 'int',
            'default': 300,
            'description': 'Cache expiration time in seconds',
            'category': 'performance'
        },
        'USE_CAPTION_FILTER': {
            'type': 'bool',
            'default': True,
            'description': 'Enable caption filter for search',
            'category': 'features'
        },
        'ADMINS': {
            'type': 'list',
            'default': [],
            'description': 'Bot admin user IDs (comma separated)',
            'category': 'access'
        },
        'CHANNELS': {
            'type': 'list',
            'default': [],
            'description': 'Channels for auto-indexing (comma separated)',
            'category': 'channels'
        },
        'AUTH_USERS': {
            'type': 'list',
            'default': [],
            'description': 'Authorized user IDs (comma separated)',
            'category': 'access'
        },
        'AUTH_CHANNEL': {
            'type': 'int',
            'default': 0,
            'description': 'Channel ID for force subscription',
            'category': 'subscription'
        },
        'AUTH_GROUPS': {
            'type': 'list',
            'default': [],
            'description': 'Group IDs for force subscription (comma separated)',
            'category': 'subscription'
        },
        'SUPPORT_CHAT_ID': {
            'type': 'int',
            'default': 0,
            'description': 'Support chat ID',
            'category': 'support'
        },
        'DELETE_CHANNEL': {
            'type': 'int',
            'default': 0,
            'description': 'Channel ID for file deletion',
            'category': 'channels'
        },
        'MAX_BTN_SIZE': {
            'type': 'int',
            'default': 10,
            'description': 'Maximum buttons per page',
            'category': 'ui'
        },
        'UPSTREAM_REPO': {
            'type': 'str',
            'default': 'https://github.com/yourusername/yourrepo',
            'description': 'Upstream repository URL',
            'category': 'deployment'
        },
        'UPSTREAM_BRANCH': {
            'type': 'str',
            'default': 'master',
            'description': 'Upstream branch name',
            'category': 'deployment'
        },
        'REDIS_URI': {
            'type': 'str',
            'default': 'redis://localhost:6379',
            'description': 'Redis connection URI',
            'category': 'database'
        },
        'DATABASE_SIZE_LIMIT_GB': {
            'type': 'float',
            'default': 0.5,
            'description': 'Database size limit in GB for auto-switching',
            'category': 'database'
        },
        'DATABASE_AUTO_SWITCH': {
            'type': 'bool',
            'default': True,
            'description': 'Enable automatic database switching when size limit reached',
            'category': 'database'
        },
        'DATABASE_MAX_FAILURES': {
            'type': 'int',
            'default': 5,
            'description': 'Max failures before circuit breaker opens',
            'category': 'database'
        },
        'DATABASE_RECOVERY_TIMEOUT': {
            'type': 'int',
            'default': 300,
            'description': 'Circuit breaker recovery timeout in seconds',
            'category': 'database'
        },
        'DATABASE_HALF_OPEN_CALLS': {
            'type': 'int',
            'default': 3,
            'description': 'Max calls in circuit breaker half-open state',
            'category': 'database'
        },
        'PUBLIC_FILE_STORE': {
            'type': 'bool',
            'default': False,
            'description': 'Allow public file store access',
            'category': 'features'
        },
        'SUPPORT_GROUP': {
            'type': 'str',
            'default': '',
            'description': 'Support group link',
            'category': 'support'
        },
        'SUPPORT_GROUP_USERNAME': {
            'type': 'str',
            'default': '',
            'description': 'Support group username',
            'category': 'support'
        },
        'MAIN_CHANNEL': {
            'type': 'str',
            'default': '',
            'description': 'Main channel link',
            'category': 'channels'
        },
        'LOG_CHANNEL': {
            'type': 'int',
            'default': 0,
            'description': 'Log channel ID',
            'category': 'channels'
        },
        'INDEX_REQ_CHANNEL': {
            'type': 'int',
            'default': 0,
            'description': 'Index request channel ID',
            'category': 'channels'
        },
        'FILE_STORE_CHANNEL': {
            'type': 'list',
            'default': [],
            'description': 'File store channel IDs (space separated)',
            'category': 'channels'
        },
        'CUSTOM_FILE_CAPTION': {
            'type': 'str',
            'default': '',
            'description': 'Custom caption template for files',
            'category': 'customization'
        },
        'BATCH_FILE_CAPTION': {
            'type': 'str',
            'default': '',
            'description': 'Custom caption template for batch files',
            'category': 'customization'
        },
        'KEEP_ORIGINAL_CAPTION': {
            'type': 'bool',
            'default': True,
            'description': 'Keep original file captions',
            'category': 'customization'
        },
        'USE_ORIGINAL_CAPTION_FOR_BATCH': {
            'type': 'bool',
            'default': False,
            'description': 'Use original caption for batch files instead of batch template',
            'category': 'customization'
        },
        'WORKERS': {
            'type': 'int',
            'default': 50,
            'description': 'Number of worker threads',
            'category': 'performance'
        },
        'DISABLE_PREMIUM': {
            'type': 'bool',
            'default': True,
            'description': 'Disable premium features',
            'category': 'features'
        },
        'DISABLE_FILTER': {
            'type': 'bool',
            'default': False,
            'description': 'Disable filter features',
            'category': 'features'
        },
        'PREMIUM_DURATION_DAYS': {
            'type': 'int',
            'default': 30,
            'description': 'Premium subscription duration in days',
            'category': 'premium'
        },
        'NON_PREMIUM_DAILY_LIMIT': {
            'type': 'int',
            'default': 10,
            'description': 'Daily file limit for non-premium users',
            'category': 'premium'
        },
        'PREMIUM_PRICE': {
            'type': 'str',
            'default': '$1',
            'description': 'Premium subscription price with currency (e.g., $1, LKR 450, INR 450)',
            'category': 'premium'
        },
        'MESSAGE_DELETE_SECONDS': {
            'type': 'int',
            'default': 300,
            'description': 'Auto-delete messages after seconds',
            'category': 'ui'
        },
        'DATABASE_URI': {
            'type': 'str',
            'default': '',
            'description': 'MongoDB connection URI',
            'category': 'database'
        },
        'DATABASE_NAME': {
            'type': 'str',
            'default': 'PIRO',
            'description': 'Database name',
            'category': 'database'
        },
        'PICS': {
            'type': 'list',
            'default': [],
            'description': 'Random pics for start command (comma separated URLs)',
            'category': 'customization'
        },
        'REQ_CHANNEL': {
            'type': 'int',
            'default': 0,
            'description': 'Channel ID for content requests (0 = use LOG_CHANNEL)',
            'category': 'channels'
        },
        'SUPPORT_GROUP_URL': {
            'type': 'str',
            'default': '',
            'description': 'Support group URL (e.g., https://t.me/yourgroup)',
            'category': 'support'
        },
        'SUPPORT_GROUP_NAME': {
            'type': 'str',
            'default': 'Support Group',
            'description': 'Support group display name',
            'category': 'support'
        },
        'SUPPORT_GROUP_ID': {
            'type': 'int',
            'default': 0,
            'description': 'Support group ID for #request feature',
            'category': 'support'
        },
        'PAYMENT_LINK': {
            'type': 'str',
            'default': 'https://buymeacoffee.com/matthewmurdock001',
            'description': 'Payment link',
            'category': 'payment'
        },
        'REQUEST_PER_DAY': {
            'type': 'int',
            'default': 3,
            'description': 'Maximum requests per day before warnings',
            'category': 'limits'
        },
        'REQUEST_WARNING_LIMIT': {
            'type': 'int',
            'default': 5,
            'description': 'Maximum warnings before auto-ban',
            'category': 'limits'
        },
        'AUTO_DELETE_MESSAGE': {
            'type': 'str',
            'default': '⏱ This {content_type} will be auto-deleted after {minutes} minutes',
            'description': 'Custom auto-delete message template (supports HTML)',
            'category': 'customization'
        },
        'START_MESSAGE': {
            'type': 'str',
            'default': '<b>👋 Welcome {mention}!</b>\n\nI\'m an advanced media search bot with powerful features.\n\n🔍 <b>Features:</b>\n- Fast indexed search\n- Group filter management\n- File indexing from channels\n- Inline search support\n\nUse /help to learn more about my features.',
            'description': 'Custom start message template (supports HTML)',
            'category': 'customization'
        },
    }

    def __init__(self, settings_repo: BotSettingsRepository, cache_manager: CacheManager):
        self.settings_repo = settings_repo
        self.cache = cache_manager

    async def initialize_settings(self) -> None:
        """Initialize settings from environment or defaults"""
        settings_to_save = {}

        for key, metadata in self.SETTINGS_METADATA.items():
            # Check if setting exists in DB
            existing = await self.settings_repo.get_setting(key)
            if not existing:
                # Get from environment or use default
                env_value = os.environ.get(key)

                if env_value is not None:
                    value = self._parse_value(env_value, metadata['type'])
                else:
                    value = metadata['default']

                settings_to_save[key] = {
                    'value': value,
                    'type': metadata['type'],
                    'default': metadata['default'],
                    'description': metadata['description']
                }

        # Bulk save new settings
        if settings_to_save:
            await self.settings_repo.bulk_upsert(settings_to_save)
            logger.info(f"Initialized {len(settings_to_save)} settings from environment")

    async def get_all_settings(self) -> Dict[str, Any]:
        """Get all settings with values"""
        db_settings = await self.settings_repo.get_all_settings()

        result = {}
        for key, metadata in self.SETTINGS_METADATA.items():
            if key in db_settings:
                result[key] = {
                    'value': db_settings[key].value,
                    'type': metadata['type'],
                    'default': metadata['default'],
                    'description': metadata['description'],
                    'category': metadata['category']
                }
            else:
                # Use default if not in DB
                result[key] = {
                    'value': metadata['default'],
                    'type': metadata['type'],
                    'default': metadata['default'],
                    'description': metadata['description'],
                    'category': metadata['category']
                }

        return result

    async def get_setting(self, key: str) -> Optional[Any]:
        """Get a single setting value"""
        setting = await self.settings_repo.get_setting(key)
        if setting:
            return setting.value

        # Return default if not found
        if key in self.SETTINGS_METADATA:
            return self.SETTINGS_METADATA[key]['default']

        return None

    async def update_setting(self, key: str, value: Any) -> bool:
        """Update a setting value"""
        if key not in self.SETTINGS_METADATA:
            return False

        metadata = self.SETTINGS_METADATA[key]

        # Validate and parse value
        parsed_value = self._parse_value(value, metadata['type'])

        return await self.settings_repo.set_setting(
            key=key,
            value=parsed_value,
            value_type=metadata['type'],
            default_value=metadata['default'],
            description=metadata['description']
        )

    async def reset_to_default(self, key: str) -> bool:
        """Reset a setting to its default value"""
        if key not in self.SETTINGS_METADATA:
            return False

        metadata = self.SETTINGS_METADATA[key]

        return await self.settings_repo.set_setting(
            key=key,
            value=metadata['default'],
            value_type=metadata['type'],
            default_value=metadata['default'],
            description=metadata['description']
        )

    def _parse_value(self, value: Any, value_type: str) -> Any:
        """Parse value based on type"""
        if value_type == 'int':
            return int(value) if value else 0
        elif value_type == 'bool':
            if isinstance(value, bool):
                return value
            return str(value).lower() in ['true', 'yes', '1', 'enable', 'y']
        elif value_type == 'list':
            if isinstance(value, list):
                return value
            if isinstance(value, str):
                # Handle both comma and space separated
                if ',' in value:
                    items = [item.strip() for item in value.split(',') if item.strip()]
                else:
                    items = [item.strip() for item in value.split() if item.strip()]

                # Try to convert to int if possible
                result = []
                for item in items:
                    try:
                        # Check if it's a negative number or positive
                        if item.lstrip('-').isdigit():
                            result.append(int(item))
                        else:
                            result.append(item)
                    except:
                        result.append(item)
                return result
            return []
        else:  # str
            return str(value) if value is not None else ''

    def get_settings_by_category(self) -> Dict[str, List[str]]:
        """Get settings grouped by category"""
        categories = {}
        for key, metadata in self.SETTINGS_METADATA.items():
            category = metadata.get('category', 'general')
            if category not in categories:
                categories[category] = []
            categories[category].append(key)

        return categories

    async def export_settings(self) -> Dict[str, Any]:
        """Export all settings for backup"""
        return await self.get_all_settings()

    async def import_settings(self, settings: Dict[str, Any]) -> Tuple[int, int]:
        """Import settings from backup"""
        success_count = 0
        failed_count = 0

        for key, data in settings.items():
            if key in self.SETTINGS_METADATA:
                try:
                    await self.update_setting(key, data.get('value'))
                    success_count += 1
                except Exception as e:
                    logger.error(f"Failed to import setting {key}: {e}")
                    failed_count += 1
            else:
                failed_count += 1

        return success_count, failed_count