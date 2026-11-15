from typing import Dict, Any, List, Optional, Tuple
import os
import math
import re

from core.cache.redis_cache import CacheManager
from repositories.bot_settings import BotSettingsRepository
from core.utils.logger import get_logger
from core.utils.subscription_config import parse_subscription_targets

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
            'description': "Port used by the bot web server and health endpoint. Match the container port configuration when changing it. Restart required.",
            'category': 'server'
        },
        'CACHE_TIME': {
            'min': 1,
            'type': 'int',
            'default': 300,
            'description': "Lifetime of cached media-search results, in seconds. Lower values refresh results sooner but increase database reads. Restart required.",
            'category': 'performance'
        },
        'USE_CAPTION_FILTER': {
            'type': 'bool',
            'default': True,
            'description': "Include indexed file captions as well as filenames when matching media searches. This controls search matching, not group keyword filters.",
            'category': 'features'
        },
        'FEATURE_SAVED_SEARCH_ALERTS': {
            'type': 'bool', 'default': False,
            'description': "Let users save search queries and receive notifications when newly indexed files match them.", 'category': 'features'
        },
        'FEATURE_FAVORITES': {
            'type': 'bool', 'default': False,
            'description': "Let users save files to their own favorites and organize them into named collections.", 'category': 'features'
        },
        'FEATURE_ADVANCED_SEARCH': {
            'type': 'bool', 'default': False,
            'description': "Enable structured key:value search filters, including type, year and size. Users can see the supported syntax with /search_help.", 'category': 'features'
        },
        'FEATURE_RECOMMENDATION_FEEDBACK': {
            'type': 'bool', 'default': False,
            'description': "Show feedback controls on recommendations so users can influence future suggestions.", 'category': 'features'
        },
        'FEATURE_FILE_REPORTS': {
            'type': 'bool', 'default': False,
            'description': "Let users report problems with files and let admins review and resolve those reports.", 'category': 'features'
        },
        'FEATURE_SEARCH_AUTOCOMPLETE': {
            'type': 'bool', 'default': False,
            'description': "Suggest related or completed queries from search history while users search. Suggestions are checked against current matching media.", 'category': 'features'
        },
        'FEATURE_DUPLICATE_GROUPING': {
            'type': 'bool', 'default': False,
            'description': "Group likely file variants under headings in search results. This changes presentation; it does not merge or delete stored files.", 'category': 'features'
        },
        'FEATURE_REQUEST_TRACKING': {
            'type': 'bool', 'default': False,
            'description': "Save content-request status so users can view their requests and admins can track outcomes. Pending duplicate requests are suppressed.", 'category': 'features'
        },
        'FEATURE_RECENT_FILES': {
            'type': 'bool', 'default': False,
            'description': "Keep each user's successful file-delivery history so they can reopen recently received files.", 'category': 'features'
        },
        'FEATURE_RECOMMENDATION_EXPLANATIONS': {
            'type': 'bool', 'default': False,
            'description': "Show users why a file or query was recommended alongside recommendation results.", 'category': 'features'
        },
        'FEATURE_INDEXED_MEDIA_SEARCH': {
            'type': 'bool', 'default': False,
            'description': "Use indexed word candidates to narrow media searches while retaining compatible matching for unbackfilled files. Plan token backfill, indexes and MongoDB storage headroom before production use.",
            'category': 'features'
        },
        'FEATURE_CONTENT_DASHBOARD': {
            'type': 'bool', 'default': False,
            'description': "Enable the admin content dashboard showing catalog totals, activity and unmet search demand. Reported file bytes are Telegram content size, not MongoDB storage usage.", 'category': 'features'
        },
        'DATABASE_GLOBAL_OWNER_REGISTRY': {
            'type': 'bool', 'default': False, 'category': 'database',
            'description': "Coordinate permanent ownership of files across multiple MongoDB sources. Requires at least two distinct valid sources and stopped-writer activation before restarting with it enabled. Activated ownership cannot simply be switched off."
        },
        'FEATURE_CANONICAL_MEDIA_METADATA': {
            'type': 'bool', 'default': False, 'category': 'features',
            'description': "Store normalized media quality and video dimensions during indexing. Enabling this does not bulk-migrate the existing catalog. Check code compatibility before rollback. Restart required."
        },
        'FEATURE_QUOTA_DELIVERY_LEDGER': {
            'type': 'bool', 'default': False, 'category': 'features',
            'description': "Persist delivery-quota reservations and settlements in MongoDB for restart recovery and one-time settlement. Uncertain deliveries require operator review. Restart required."
        },
        'PROCESSING_DURABLE_INDEXING': {
            'type': 'bool', 'default': False, 'category': 'features',
            'description': "Persist automatic channel-indexing jobs in MongoDB so unfinished work can retry after failure or restart. Adds job records and background workers. Restart required."
        },
        'PROCESSING_DURABLE_SAVED_SEARCH_ALERTS': {
            'type': 'bool', 'default': False, 'category': 'features',
            'description': "Persist saved-search matching jobs in MongoDB for retry and restart recovery. Saved Search Alerts must also be enabled. Restart required."
        },
        'ADMINS': {
            'type': 'list',
            'default': [],
            'description': "Comma-separated Telegram user IDs with bot-admin privileges. The first ID is the primary admin who can manage /bsetting. Configured admins retain their access bypasses.",
            'category': 'access'
        },
        'CHANNELS': {
            'type': 'list',
            'default': [],
            'description': "Active channel IDs for automatic indexing of new posts. Shared with /add_channel, /remove_channel and /toggle_channel. Editing this list replaces the active set; disabled entries retain their history across restart.",
            'category': 'channels'
        },
        'AUTH_USERS': {
            'type': 'list',
            'default': [],
            'description': "Comma-separated Telegram user IDs exempt from required channel/group membership checks. These users are not made bot admins; normal ban and premium rules still apply.",
            'category': 'access'
        },
        'AUTH_CHANNEL': {
            'type': 'list',
            'default': [],
            'description': "Channels users must join before using gated bot features. Accepts comma-separated channel IDs or @usernames. Bot admin status and invite-link permission are checked before saving.",
            'category': 'subscription'
        },
        'AUTH_GROUPS': {
            'type': 'list',
            'default': [],
            'description': "Groups users must join before using gated bot features. Accepts comma-separated group IDs or @usernames. Bot admin status and invite-link permission are checked before saving.",
            'category': 'subscription'
        },
        'FORCE_SUB_INVITE_EXPIRE_MINUTES': {
            'type': 'int', 'default': 15, 'min': 1, 'max': 525600,
            'description': "Lifetime, in minutes, of generated force-subscription invite links. Newly generated links use this value after restart; existing links keep their original expiry.",
            'category': 'subscription'
        },
        'FORCE_SUB_INVITE_MEMBER_LIMIT': {
            'type': 'int', 'default': 1, 'min': 1, 'max': 99999,
            'description': "Maximum simultaneous members admitted through each generated force-subscription invite link. This is not a lifetime join counter. Restart required.",
            'category': 'subscription'
        },
        'SUPPORT_CHAT_ID': {
            'type': 'int',
            'default': 0,
            'description': "Legacy support-chat ID retained for compatibility; current bot handlers do not use it. Use Request Group ID for #request messages and Support Button URL for the visible support link.",
            'category': 'support'
        },
        'DELETE_CHANNEL': {
            'type': 'int',
            'default': 0,
            'description': "Channel where posting or forwarding supported media queues deletion of the matching media record from the bot database. This removes catalog entries, not the original Telegram source messages. Set 0 to disable this channel.",
            'category': 'channels'
        },
        'MAX_BTN_SIZE': {
            'min': 1,
            'type': 'int',
            'default': 12,
            'description': "Maximum file results displayed on each search-results page. Navigation, support buttons and variant headings can add extra buttons beyond this count.",
            'category': 'ui'
        },
        'UPSTREAM_REPO': {
            'type': 'str',
            'default': 'https://github.com/rumalg123/Advanced-File-Filter-Bot.git',
            'description': "Git repository URL fetched by /restart when updating the bot code. Use the repository containing the branch selected in Update Branch.",
            'category': 'deployment'
        },
        'UPSTREAM_BRANCH': {
            'type': 'str',
            'default': 'main',
            'description': "Git branch fetched by /restart before applying code updates and restarting the bot. Set this to the branch you intend to deploy.",
            'category': 'deployment'
        },
        'REDIS_URI': {
            'type': 'str',
            'default': 'redis://localhost:6379',
            'description': "Connection URI for the main/cache Redis instance. Protected in this menu: change it through deployment environment configuration. Protected state Redis has separate environment settings.",
            'category': 'database'
        },
        'DATABASE_SIZE_LIMIT_GB': {
            'min': 1e-09,
            'type': 'float',
            'default': 0.5,
            'description': "Per-source size threshold used for automatic media-database switching, measured in GiB from MongoDB data plus index bytes. This is a routing threshold, not a provider storage-quota setting.",
            'category': 'database'
        },
        'DATABASE_AUTO_SWITCH': {
            'type': 'bool',
            'default': True,
            'description': "Automatically choose another configured media database for new writes when the current source reaches its size threshold. Requires multiple sources; it does not migrate existing records or distribute primary user data.",
            'category': 'database'
        },
        'DATABASE_MAX_FAILURES': {
            'type': 'int',
            'default': 5,
            'description': "Number of source failures before its database circuit breaker opens and temporarily avoids that source.",
            'category': 'database'
        },
        'DATABASE_RECOVERY_TIMEOUT': {
            'type': 'int',
            'default': 300,
            'description': "Seconds a database circuit breaker waits after opening before allowing recovery probes.",
            'category': 'database'
        },
        'DATABASE_HALF_OPEN_CALLS': {
            'type': 'int',
            'default': 3,
            'description': "Maximum trial calls allowed while a database circuit breaker is half-open to check recovery.",
            'category': 'database'
        },
        'PUBLIC_FILE_STORE': {
            'type': 'bool',
            'default': False,
            'description': "Allow normal users to create single-file and batch links. Channel-batch creators must belong to the source and the bot must be able to read it; the source need not be in File Channels or Indexing Channels. Turning this off keeps creation admin-only and does not disable opening valid existing links. Restart required.",
            'category': 'features'
        },
        'SUPPORT_GROUP': {
            'type': 'str',
            'default': '',
            'description': "Legacy support-group link retained for compatibility; current buttons do not use it. Set Support Button URL to change the visible support link.",
            'category': 'support'
        },
        'SUPPORT_GROUP_USERNAME': {
            'type': 'str',
            'default': '',
            'description': "Legacy support username retained for compatibility; current handlers do not use it. Set Support Button URL for the support destination and Support Button Label for its text.",
            'category': 'support'
        },
        'MAIN_CHANNEL': {
            'type': 'str',
            'default': '',
            'description': "Legacy main-channel link retained for compatibility; current menus do not use it. Use Force-Sub Channels to require channel membership.",
            'category': 'channels'
        },
        'LOG_CHANNEL': {
            'type': 'int',
            'default': 0,
            'description': "Channel ID receiving bot events, indexing summaries and admin notifications. Content requests can fall back here when their review channel is unset. The bot must be allowed to post here.",
            'category': 'channels'
        },
        'INDEX_REQ_CHANNEL': {
            'type': 'int',
            'default': 0,
            'description': "Channel ID receiving requests to index a source, with Accept/Reject controls for admins. This is an approval inbox, not the list of channels automatically indexed. Failed sends can fall back to Bot Log Channel.",
            'category': 'channels'
        },
        'FILE_STORE_CHANNEL': {
            'type': 'list',
            'default': [],
            'description': "Additional batch-source channel IDs, space-separated. Allows normal users to open old unsigned batch URLs from these sources without enabling automatic indexing. Active indexing sources also support old batch URLs. Public creators use source membership independently of these lists.",
            'category': 'channels'
        },
        'CUSTOM_FILE_CAPTION': {
            'type': 'str',
            'default': '',
            'description': "HTML caption template for ordinary file deliveries. Supports {filename} and {size}. When nonempty it takes precedence over the original file caption.",
            'category': 'customization'
        },
        'BATCH_FILE_CAPTION': {
            'type': 'str',
            'default': '',
            'description': "HTML caption template for batch deliveries. Supports {filename} and {size}. Original Batch Captions takes precedence when an original caption is available.",
            'category': 'customization'
        },
        'KEEP_ORIGINAL_CAPTION': {
            'type': 'bool',
            'default': True,
            'description': "Use the stored original caption when no higher-priority caption template applies. Batch deliveries also follow Original Batch Captions and Batch Caption Template.",
            'category': 'customization'
        },
        'USE_ORIGINAL_CAPTION_FOR_BATCH': {
            'type': 'bool',
            'default': True,
            'description': "Prefer each batch file's original caption when available. Otherwise use Batch Caption Template, with Keep Original Captions as the fallback.",
            'category': 'customization'
        },
        'WORKERS': {
            'min': 1,
            'type': 'int',
            'default': 50,
            'description': "Number of Telegram update-handler workers. Controls how many incoming updates can be handled concurrently; it is not the MongoDB connection-pool size. Restart required.",
            'category': 'performance'
        },
        'DISABLE_PREMIUM': {
            'type': 'bool',
            'default': True,
            'description': "True gives ordinary file retrieval unlimited access without premium daily quotas. False enforces premium status and the Daily File Limit. Premium-only batch links remain unavailable to ordinary users while premium is disabled; admin bypasses remain.",
            'category': 'features'
        },
        'DISABLE_FILTER': {
            'type': 'bool',
            'default': False,
            'description': "Disable stored keyword-filter and group-connection services. Media-file search remains available. Restart required.",
            'category': 'features'
        },
        'PREMIUM_DURATION_DAYS': {
            'type': 'int',
            'default': 30,
            'description': "Default duration, in days, for future premium grants without an explicit duration. Changing it does not alter existing expiry dates. Per-grant overrides still apply. Restart required.",
            'category': 'premium',
            'min': 1,
            'max': 36500,
        },
        'NON_PREMIUM_DAILY_LIMIT': {
            'min': 0,
            'type': 'int',
            'default': 10,
            'description': "Maximum delivered media files per day for normal non-premium users when premium rules are enabled. Resets at 00:00 UTC; configured admin/owner and valid premium bypasses remain.",
            'category': 'premium'
        },
        'PREMIUM_PRICE': {
            'type': 'str',
            'default': '$1',
            'description': "Price text displayed in premium plans, including currency. This is presentation text; it does not charge users or automatically grant premium.",
            'category': 'premium'
        },
        'MESSAGE_DELETE_SECONDS': {
            'min': 0,
            'type': 'int',
            'default': 300,
            'description': "Delay, in seconds, before supported bot replies and delivered files are automatically removed from the chat. Set 0 to disable scheduled auto-delete; this does not delete the source files or catalog records.",
            'category': 'ui'
        },
        'DATABASE_URI': {
            'type': 'str',
            'default': '',
            'description': "Connection URI for the primary MongoDB source holding users, settings and shared bot state. Protected here; change through deployment environment configuration.",
            'category': 'database'
        },
        'DATABASE_NAME': {
            'type': 'str',
            'default': 'PIRO',
            'description': "Database name on the primary MongoDB source. Protected here; change through deployment environment configuration.",
            'category': 'database'
        },
        'PICS': {
            'type': 'list',
            'default': [],
            'description': "Comma-separated photo URLs used for random /start welcome photos. Leave empty to send the welcome as text.",
            'category': 'customization'
        },
        'REQ_CHANNEL': {
            'type': 'int',
            'default': 0,
            'description': "Channel ID where missing-content requests are sent for admin review. Set 0 to use Bot Log Channel. This is separate from Index Requests Channel, which handles requests to index sources.",
            'category': 'channels'
        },
        'SUPPORT_GROUP_URL': {
            'type': 'str',
            'default': '',
            'description': "URL opened by the support button on welcome and search-result messages. Use the Telegram group/channel link you want users to visit.",
            'category': 'support'
        },
        'SUPPORT_GROUP_NAME': {
            'type': 'str',
            'default': 'Support Group',
            'description': "Text displayed on the support button. Support Button URL controls its destination.",
            'category': 'support'
        },
        'SUPPORT_GROUP_ID': {
            'type': 'int',
            'default': 0,
            'description': "Group ID where users send #request followed by a title. Set 0 to disable this group request handler. Requests needing admin review are sent to Content Requests Channel.",
            'category': 'support'
        },
        'PAYMENT_LINK': {
            'type': 'str',
            'default': 'https://buymeacoffee.com/matthewmurdock001',
            'description': "URL users open from the premium payment button. It is a payment destination link; changing it does not grant or remove subscriptions.",
            'category': 'payment'
        },
        'REQUEST_ONLY_FOR_PREMIUM': {
            'type': 'bool',
            'default': False,
            'description': "Require valid premium membership for content requests when premium rules are enabled. Configured admin bypasses remain; disabling premium rules removes this premium-only restriction.",
            'category': 'premium'
        },
        'REQUEST_PER_DAY': {
            'type': 'int',
            'default': 3,
            'description': "Number of content requests a normal user can submit per UTC day before further attempts add warnings. Replayed or pending tracked requests follow their existing duplicate guards.",
            'category': 'limits'
        },
        'REQUEST_WARNING_LIMIT': {
            'type': 'int',
            'default': 5,
            'description': "Accumulated request-abuse warnings that trigger an automatic ban. Extra attempts after the Daily Request Limit add warnings; this is separate from the Daily File Limit.",
            'category': 'limits'
        },
        'AUTO_DELETE_MESSAGE': {
            'type': 'str',
            'default': '⏱ This {content_type} will be auto-deleted after {minutes} minutes',
            'description': "HTML notice template shown with supported auto-deleted content. Supports {content_type} and {minutes}; Auto-Delete Delay (sec) controls the timer.",
            'category': 'customization'
        },
        'START_MESSAGE': {
            'type': 'str',
            'default': '<b>👋 Welcome {mention}!</b>\n\nI\'m an advanced media search bot with powerful features.\n\n🔍 <b>Features:</b>\n- Fast indexed search\n- Group filter management\n- File indexing from channels\n- Inline search support\n\nUse /help to learn more about my features.',
            'description': "HTML welcome text used by /start. Supports {mention}, {user_id}, {first_name}, {bot_name} and {bot_username}. Welcome Photo URLs controls whether it accompanies a photo.",
            'category': 'customization'
        },
    }

    def __init__(self, settings_repo: BotSettingsRepository, cache_manager: CacheManager,
                 *, database_config=None, telegram_client=None, channel_repo=None):
        self.settings_repo = settings_repo
        self.cache = cache_manager
        self.telegram_client = telegram_client
        self.channel_repo = channel_repo
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
                    value = (parse_subscription_targets(env_value) if key in {'AUTH_CHANNEL', 'AUTH_GROUPS'}
                             else self._parse_value(env_value, metadata['type']))
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
        if self.channel_repo is not None:
            bootstrap = await self.settings_repo.get_setting('CHANNELS')
            await self.channel_repo.seed_channels(bootstrap.value if bootstrap else [])

    async def get_all_settings(self) -> Dict[str, Any]:
        """Get all settings with values"""
        db_settings = await self.settings_repo.get_all_settings()

        result = {}
        for key, metadata in self.SETTINGS_METADATA.items():
            if key in db_settings:
                stored_value = db_settings[key].value
                try:
                    stored_value = (parse_subscription_targets(stored_value) if key in {'AUTH_CHANNEL', 'AUTH_GROUPS'}
                                    else self._parse_value(stored_value, metadata['type'], strict=True))
                    stored_value = self._validate_value_bounds(
                        key, stored_value, metadata
                    )
                except (ValueError, TypeError) as error:
                    if key in {'AUTH_CHANNEL', 'AUTH_GROUPS'}:
                        raise ValueError(f"Invalid stored force-subscription setting {key}; correct it before startup.") from error
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

        if self.channel_repo is not None:
            result['CHANNELS']['value'] = await self.channel_repo.get_active_channel_ids()
        policy = await self.owner_registry_policy()
        owner_setting = result['DATABASE_GLOBAL_OWNER_REGISTRY']
        owner_setting.update(default=policy['default'], editable=policy['editable'],
                             edit_note=policy['note'])
        if 'DATABASE_GLOBAL_OWNER_REGISTRY' not in db_settings:
            owner_setting['value'] = policy['default']
        return result

    async def get_setting(self, key: str) -> Optional[Any]:
        """Get a single setting value"""
        if key == 'CHANNELS' and self.channel_repo is not None:
            return await self.channel_repo.get_active_channel_ids()
        setting = await self.settings_repo.get_setting(key)
        if setting:
            return (parse_subscription_targets(setting.value) if key in {'AUTH_CHANNEL', 'AUTH_GROUPS'}
                    else setting.value)

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
        parsed_value = (parse_subscription_targets(value) if key in {'AUTH_CHANNEL', 'AUTH_GROUPS'}
                        else self._parse_value(value, metadata['type'], strict=True))
        if key == 'CHANNELS':
            from repositories.channel import ChannelRepository
            parsed_value = ChannelRepository.normalize_channel_ids(value)
        parsed_value = self._validate_value_bounds(key, parsed_value, metadata)
        if key == 'CHANNELS' and self.channel_repo is not None:
            return await self.channel_repo.replace_active_channels(parsed_value)
        default = metadata['default']
        if key in {'AUTH_CHANNEL', 'AUTH_GROUPS'} and parsed_value:
            if self.telegram_client is None:
                raise ValueError('Cannot verify force-subscription permissions. Reopen settings in the running bot and retry.')
            from core.utils.subscription import SubscriptionManager
            parsed_value = await SubscriptionManager.validate_targets(
                self.telegram_client, parsed_value,
                expected_type='channel' if key == 'AUTH_CHANNEL' else 'group'
            )
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
