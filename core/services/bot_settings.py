from typing import Dict, Any, List, Optional, Tuple
import os
import math
import re

from core.cache.redis_cache import CacheManager
from repositories.bot_settings import BotSettingsRepository
from core.utils.logger import get_logger

logger = get_logger(__name__)


class BotSettingsService:
    """Service for managing bot settings"""

    # Define all configurable settings with their metadata
    SETTINGS_METADATA = {
        'PORT': {
            'min': 1,
            'max': 65535,
            'type': 'int',
            'default': 8000,
            'description': 'Web server port',
            'category': 'server'
        },
        'CACHE_TIME': {
            'min': 1,
            'type': 'int',
            'default': 300,
            'description': 'Search-result cache expiration in seconds (restart required)',
            'category': 'performance'
        },
        'USE_CAPTION_FILTER': {
            'type': 'bool',
            'default': True,
            'description': 'Enable caption filter for search',
            'category': 'features'
        },
        'FEATURE_SAVED_SEARCH_ALERTS': {
            'type': 'bool', 'default': False,
            'description': 'Enable saved searches and new-file alerts', 'category': 'features'
        },
        'FEATURE_FAVORITES': {
            'type': 'bool', 'default': False,
            'description': 'Enable favorites and named collections', 'category': 'features'
        },
        'FEATURE_ADVANCED_SEARCH': {
            'type': 'bool', 'default': False,
            'description': 'Enable structured advanced-search filters', 'category': 'features'
        },
        'FEATURE_RECOMMENDATION_FEEDBACK': {
            'type': 'bool', 'default': False,
            'description': 'Enable recommendation feedback controls', 'category': 'features'
        },
        'FEATURE_FILE_REPORTS': {
            'type': 'bool', 'default': False,
            'description': 'Enable user file reports', 'category': 'features'
        },
        'FEATURE_SEARCH_AUTOCOMPLETE': {
            'type': 'bool', 'default': False,
            'description': 'Enable search autocomplete', 'category': 'features'
        },
        'FEATURE_DUPLICATE_GROUPING': {
            'type': 'bool', 'default': False,
            'description': 'Group likely file variants in results', 'category': 'features'
        },
        'FEATURE_REQUEST_TRACKING': {
            'type': 'bool', 'default': False,
            'description': 'Persist content request status', 'category': 'features'
        },
        'FEATURE_RECENT_FILES': {
            'type': 'bool', 'default': False,
            'description': 'Enable recent successful-delivery history', 'category': 'features'
        },
        'FEATURE_RECOMMENDATION_EXPLANATIONS': {
            'type': 'bool', 'default': False,
            'description': 'Show recommendation reasons', 'category': 'features'
        },
        'FEATURE_INDEXED_MEDIA_SEARCH': {
            'type': 'bool', 'default': False,
            'description': 'Enable indexed word candidates after search-token backfill',
            'category': 'features'
        },
        'FEATURE_CONTENT_DASHBOARD': {
            'type': 'bool', 'default': False,
            'description': 'Enable the admin content dashboard', 'category': 'features'
        },
        'DATABASE_GLOBAL_OWNER_REGISTRY': {
            'type': 'bool', 'default': False, 'category': 'database',
            'description': 'Coordinate file ownership across multiple databases. Activate ownership with all writers stopped before restarting with this enabled. Restart required.'
        },
        'FEATURE_CANONICAL_MEDIA_METADATA': {
            'type': 'bool', 'default': False, 'category': 'features',
            'description': 'Persist separate quality and pixel dimensions on new media. Check compatibility before rolling back to older images. Restart required.'
        },
        'FEATURE_QUOTA_DELIVERY_LEDGER': {
            'type': 'bool', 'default': False, 'category': 'features',
            'description': 'Record quota reservations and one-time settlements. Uncertain deliveries require operator review. Restart required.'
        },
        'PROCESSING_DURABLE_INDEXING': {
            'type': 'bool', 'default': False, 'category': 'features',
            'description': 'Store channel indexing jobs in MongoDB for retry and restart recovery. Restart required.'
        },
        'PROCESSING_DURABLE_SAVED_SEARCH_ALERTS': {
            'type': 'bool', 'default': False, 'category': 'features',
            'description': 'Store saved-search alert jobs in MongoDB for retry and recovery. Also requires Saved Alerts to be enabled. Restart required.'
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
            'type': 'str',
            'default': '',
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
            'min': 1,
            'type': 'int',
            'default': 12,
            'description': 'Maximum buttons per page',
            'category': 'ui'
        },
        'UPSTREAM_REPO': {
            'type': 'str',
            'default': 'https://github.com/rumalg123/Advanced-File-Filter-Bot.git',
            'description': 'Upstream repository URL',
            'category': 'deployment'
        },
        'UPSTREAM_BRANCH': {
            'type': 'str',
            'default': 'main',
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
            'min': 1e-09,
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
            'default': True,
            'description': 'Use original caption for batch files instead of batch template',
            'category': 'customization'
        },
        'WORKERS': {
            'min': 1,
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
            'description': 'Default premium subscription duration in days',
            'category': 'premium',
            'min': 1,
            'max': 36500,
        },
        'NON_PREMIUM_DAILY_LIMIT': {
            'min': 0,
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
            'min': 0,
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
        'REQUEST_ONLY_FOR_PREMIUM': {
            'type': 'bool',
            'default': False,
            'description': 'Can request only for premium users',
            'category': 'premium'
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

    def __init__(self, settings_repo: BotSettingsRepository, cache_manager: CacheManager,
                 *, database_config=None):
        self.settings_repo = settings_repo
        self.cache = cache_manager
        if database_config is None:
            from config.settings import settings
            database_config = settings.database
        self.database_config = database_config

    async def owner_registry_policy(self) -> Dict[str, Any]:
        """Source eligibility and activation recommendation; never activates data."""
        from core.database.topology import validated_database_sources
        from core.database.media_owners import GlobalMediaOwners
        from types import SimpleNamespace

        policy = {'editable': False, 'default': False, 'bound': False, 'note': ''}
        try:
            sources = validated_database_sources(self.database_config)
        except ValueError as error:
            policy['note'] = str(error)
            return policy
        if len(sources) < 2:
            policy['note'] = 'Configure at least two distinct valid database sources to edit this setting.'
            return policy
        try:
            collection = await self.settings_repo.db_pool.get_collection('media_owner_control')
            binding = await collection.find_one({'_id': 'binding-v1'})
            topology = await collection.find_one({'_id': 'topology-v1'})
            owners = GlobalMediaOwners([SimpleNamespace(uri=uri, name=name) for uri, name in sources])
            ready = bool(binding and binding.get('coordinator') == owners.primary
                         and binding.get('source') == owners.primary and topology
                         and topology.get('state') == 'ready'
                         and topology.get('topology') == owners.topology)
        except Exception as e:
            logger.error(f"Failed to check media ownership activation status: {e}")
            policy['note'] = 'Cannot verify ownership activation. Check database connectivity before editing.'
            return policy
        policy.update(editable=True, default=ready, bound=bool(binding))
        policy['note'] = (
            'Recommended: True. Ownership is activated; disabling it requires a separate retirement migration.'
            if ready else
            'Recommended: False until ownership activation is complete. If enabling, stop all writers and activate ownership before restarting.'
        )
        return policy

    async def initialize_settings(self) -> None:
        """Initialize settings from environment or defaults"""
        settings_to_save = {}

        for key, metadata in self.SETTINGS_METADATA.items():
            # Check if setting exists in DB
            existing = await self.settings_repo.get_setting(key)
            if not existing:
                default = metadata['default']
                if key == 'DATABASE_GLOBAL_OWNER_REGISTRY':
                    default = (await self.owner_registry_policy())['default']
                # Get from environment or use default
                env_value = os.environ.get(key)
                if env_value is None:
                    env_aliases = {
                        'UPSTREAM_REPO': 'UPDATE_REPO',
                        'UPSTREAM_BRANCH': 'UPDATE_BRANCH',
                    }
                    alias = env_aliases.get(key)
                    env_value = os.environ.get(alias) if alias else None

                if env_value is not None:
                    value = self._parse_value(env_value, metadata['type'])
                else:
                    value = default

                settings_to_save[key] = {
                    'value': value,
                    'type': metadata['type'],
                    'default': default,
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
                stored_value = db_settings[key].value
                try:
                    stored_value = self._parse_value(stored_value, metadata['type'], strict=True)
                    stored_value = self._validate_value_bounds(
                        key, stored_value, metadata
                    )
                except (ValueError, TypeError) as error:
                    logger.warning(
                        f"Ignoring invalid stored setting {key}: {error}"
                    )
                    stored_value = metadata['default']
                result[key] = {
                    'value': stored_value,
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

        policy = await self.owner_registry_policy()
        owner_setting = result['DATABASE_GLOBAL_OWNER_REGISTRY']
        owner_setting.update(default=policy['default'], editable=policy['editable'],
                             edit_note=policy['note'])
        if 'DATABASE_GLOBAL_OWNER_REGISTRY' not in db_settings:
            owner_setting['value'] = policy['default']
        return result

    async def get_setting(self, key: str) -> Optional[Any]:
        """Get a single setting value"""
        setting = await self.settings_repo.get_setting(key)
        if setting:
            return setting.value

        # Return default if not found
        if key in self.SETTINGS_METADATA:
            if key == 'DATABASE_GLOBAL_OWNER_REGISTRY':
                return (await self.owner_registry_policy())['default']
            return self.SETTINGS_METADATA[key]['default']

        return None

    async def update_setting(self, key: str, value: Any) -> bool:
        """Update a setting value"""
        if key not in self.SETTINGS_METADATA:
            return False

        metadata = self.SETTINGS_METADATA[key]

        # Validate and parse value
        parsed_value = self._parse_value(value, metadata['type'], strict=True)
        parsed_value = self._validate_value_bounds(key, parsed_value, metadata)
        default = metadata['default']
        if key == 'DATABASE_GLOBAL_OWNER_REGISTRY':
            policy = await self.owner_registry_policy()
            if not policy['editable']:
                raise ValueError(policy['note'])
            if not parsed_value and policy['bound']:
                raise ValueError('Activated media ownership cannot be disabled. A separate retirement migration is required.')
            default = policy['default']

        return await self.settings_repo.set_setting(
            key=key,
            value=parsed_value,
            value_type=metadata['type'],
            default_value=default,
            description=metadata['description']
        )

    @staticmethod
    def _validate_value_bounds(
        key: str, value: Any, metadata: Dict[str, Any]
    ) -> Any:
        """Validate optional numeric setting bounds and return the value."""
        minimum = metadata.get('min')
        maximum = metadata.get('max')
        if minimum is not None and value < minimum:
            raise ValueError(f"{key} must be at least {minimum}")
        if maximum is not None and value > maximum:
            raise ValueError(f"{key} must be at most {maximum}")
        return value

    async def reset_to_default(self, key: str) -> bool:
        """Reset a setting to its default value"""
        if key not in self.SETTINGS_METADATA:
            return False

        default = self.SETTINGS_METADATA[key]['default']
        if key == 'DATABASE_GLOBAL_OWNER_REGISTRY':
            default = (await self.owner_registry_policy())['default']
        return await self.update_setting(key, default)

    def _parse_value(self, value: Any, value_type: str, *, strict: bool = False) -> Any:
        """Parse value based on type"""
        if strict:
            if value_type == 'int':
                if isinstance(value, bool) or not isinstance(value, (str, int)):
                    raise ValueError("Expected an integer")
                if isinstance(value, str) and not re.fullmatch(r"[+-]?[0-9]+", value.strip()):
                    raise ValueError("Expected an integer")
            elif value_type == 'float':
                try:
                    parsed = float(value)
                except (ValueError, TypeError, OverflowError) as error:
                    raise ValueError("Expected a finite number") from error
                if isinstance(value, bool) or not math.isfinite(parsed):
                    raise ValueError("Expected a finite number")
                return parsed
            elif value_type == 'bool':
                if isinstance(value, bool):
                    return value
                text = str(value).strip().lower()
                if text in {'true', 'yes', '1', 'enable', 'enabled', 'y', 'on'}:
                    return True
                if text in {'false', 'no', '0', 'disable', 'disabled', 'n', 'off'}:
                    return False
                raise ValueError("Expected true or false")
        if value_type == 'int':
            if not value:
                return 0
            try:
                return int(value)
            except (ValueError, TypeError):
                logger.warning(f"Failed to parse '{value}' as int, defaulting to 0")
                return 0
        elif value_type == 'float':
            if not value:
                return 0.0
            try:
                return float(value)
            except (ValueError, TypeError):
                logger.warning(f"Failed to parse '{value}' as float, defaulting to 0.0")
                return 0.0
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
                    except (ValueError, AttributeError):
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
                    if await self.update_setting(key, data.get('value')):
                        success_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    logger.error(f"Failed to import setting {key}: {e}")
                    failed_count += 1
            else:
                failed_count += 1

        return success_count, failed_count
