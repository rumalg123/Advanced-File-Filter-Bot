import sys
import asyncio
from pathlib import Path

import aiohttp_cors

from core.cache.config import CacheKeyGenerator, CacheTTLConfig
from core.utils.performance import performance_monitor, PerformanceMonitor
from handlers.manager import HandlerManager

UVLOOP_AVAILABLE = False
if sys.platform != 'win32':
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        UVLOOP_AVAILABLE = True
        print("✅ uvloop installed - using optimized event loop")
    except ImportError:
        UVLOOP_AVAILABLE = False
        print("⚠️ uvloop not installed - using default event loop")
        print("   Install with: pip install uvloop")
else:
    UVLOOP_AVAILABLE = False

import logging
import os
from datetime import datetime, UTC
from typing import Optional, AsyncGenerator, Union, List

import pytz
from aiohttp import web
#from dotenv import load_dotenv
from pyrogram import Client, __version__
from pyrogram.enums import ParseMode
from pyrogram.raw.all import layer
from pyrogram.types import Message

from core.cache.redis_cache import CacheManager
from core.database.pool import DatabaseConnectionPool
from core.database.multi_pool import MultiDatabaseManager
from core.database.indexes import IndexOptimizer
from core.session.manager import UnifiedSessionManager
from core.services.bot_settings import BotSettingsService
from core.services.broadcast import BroadcastService
from core.services.connection import ConnectionService
from core.services.file_access import FileAccessService
from core.services.filestore import FileStoreService
from core.services.filter import FilterService
from core.services.indexing import IndexingService, IndexRequestService
from core.services.maintainence import MaintenanceService
from core.utils.rate_limiter import RateLimiter
from core.utils.subscription import SubscriptionManager
from handlers.request import RequestHandler
from repositories.bot_settings import BotSettingsRepository
from repositories.batch_link import BatchLinkRepository
from repositories.channel import ChannelRepository
from repositories.connection import ConnectionRepository
from repositories.filter import FilterRepository
from repositories.media import MediaRepository
from repositories.user import UserRepository
from core.cache.invalidation import CacheInvalidator
from core.utils.logger import get_logger
import core.utils.messages as default_messages
from config import settings

logger = get_logger(__name__)

performance_monitor = PerformanceMonitor()


class BotConfig:
    """Configuration adapter for centralized Pydantic settings"""
    
    def __init__(self):
        # Use centralized settings
        self._settings = settings
        
        # Bot settings
        self.SESSION = self._settings.telegram.session
        self.API_ID = self._settings.telegram.api_id
        self.API_HASH = self._settings.telegram.api_hash
        self.BOT_TOKEN = self._settings.telegram.bot_token
        
        # Database settings
        self.DATABASE_URI = self._settings.database.uri
        self.DATABASE_NAME = self._settings.database.name
        self.COLLECTION_NAME = self._settings.database.collection_name
        
        # Multi-database settings
        self.DATABASE_URIS = self._parse_database_uris()
        self.DATABASE_NAMES = self._parse_database_names()
        self.DATABASE_SIZE_LIMIT_GB = self._settings.database.size_limit_gb
        self.DATABASE_AUTO_SWITCH = self._settings.database.auto_switch

        # Circuit breaker settings
        self.DATABASE_MAX_FAILURES = self._settings.database.max_failures
        self.DATABASE_RECOVERY_TIMEOUT = self._settings.database.recovery_timeout
        self.DATABASE_HALF_OPEN_CALLS = self._settings.database.half_open_calls
        
        # Redis settings
        self.REDIS_URI = self._settings.redis.uri
        
        # Server settings
        self.PORT = self._settings.server.port
        self.WORKERS = self._settings.server.workers
        
        # Feature flags
        self.USE_CAPTION_FILTER = self._settings.features.use_caption_filter
        self.DISABLE_PREMIUM = self._settings.features.disable_premium
        self.DISABLE_FILTER = self._settings.features.disable_filter
        self.PUBLIC_FILE_STORE = self._settings.features.public_file_store
        self.KEEP_ORIGINAL_CAPTION = self._settings.features.keep_original_caption
        self.USE_ORIGINAL_CAPTION_FOR_BATCH = self._settings.features.use_original_caption_for_batch
        
        # Limits
        self.PREMIUM_DURATION_DAYS = self._settings.features.premium_duration_days
        self.NON_PREMIUM_DAILY_LIMIT = self._settings.features.non_premium_daily_limit
        self.PREMIUM_PRICE = self._settings.features.premium_price
        self.MESSAGE_DELETE_SECONDS = self._settings.features.message_delete_seconds
        self.MAX_BTN_SIZE = self._settings.features.max_btn_size
        self.REQUEST_PER_DAY = self._settings.features.request_per_day
        self.REQUEST_WARNING_LIMIT = self._settings.features.request_warning_limit
        
        # Channel and admin settings
        self.LOG_CHANNEL = self._settings.channels.log_channel
        self.INDEX_REQ_CHANNEL = self._settings.channels.index_req_channel
        self.FILE_STORE_CHANNEL = self._settings.channels.file_store_channel
        self.DELETE_CHANNEL = self._settings.channels.delete_channel
        self.REQ_CHANNEL = self._settings.channels.req_channel
        self.SUPPORT_GROUP_ID = self._settings.channels.support_group_id
        self.AUTH_CHANNEL = self._parse_auth_channel()
        
        # Lists from settings
        self.ADMINS = self._settings.channels.get_admin_list()
        self.CHANNELS = self._settings.channels.get_channel_list()
        if 0 in self.CHANNELS:
            self.CHANNELS.remove(0)
        self.PICS = self._settings.channels.get_pics_list()
        self.AUTH_GROUPS = self._settings.channels.get_auth_groups_list()
        self.AUTH_USERS = self._settings.channels.get_auth_users_list()
        self.AUTH_USERS.extend(self.ADMINS)  # Add admins to auth users
        
        # Messages
        self.CUSTOM_FILE_CAPTION = self._settings.messages.custom_file_caption
        self.BATCH_FILE_CAPTION = self._settings.messages.batch_file_caption
        self.AUTO_DELETE_MESSAGE = self._settings.messages.auto_delete_message
        self.START_MESSAGE = self._settings.messages.start_message
        self.SUPPORT_GROUP_URL = self._settings.messages.support_group_url
        self.SUPPORT_GROUP_NAME = self._settings.messages.support_group_name
        self.PAYMENT_LINK = self._settings.messages.payment_link
    
    def _parse_auth_channel(self) -> Optional[int]:
        """Parse auth channel from settings"""
        if self._settings.channels.auth_channel:
            auth_channel = self._settings.channels.auth_channel
            if auth_channel.lstrip('-').isdigit():
                return int(auth_channel)
        return None
    
    def _parse_database_uris(self) -> List[str]:
        """Parse multiple database URIs from settings"""
        uris = []
        
        # Always include primary DATABASE_URI first
        if self.DATABASE_URI:
            uris.append(self.DATABASE_URI)
        
        # Add additional URIs from settings
        additional_uris = self._settings.database.get_additional_uris()
        for uri in additional_uris:
            if uri and uri not in uris:  # Avoid duplicates
                uris.append(uri)
        
        return uris
    
    def _parse_database_names(self) -> List[str]:
        """Parse multiple database names from settings"""
        names = []
        
        # Always include primary DATABASE_NAME first
        names.append(self.DATABASE_NAME)
        
        # Add additional names from settings
        additional_names = self._settings.database.get_additional_names()
        names.extend(additional_names)
        
        # If no additional names specified, use same name for all databases
        while len(names) < len(self.DATABASE_URIS):
            names.append(self.DATABASE_NAME)
        
        return names[:len(self.DATABASE_URIS)]  # Trim to match URI count
    
    @property
    def is_multi_database_enabled(self) -> bool:
        """Check if multi-database mode is enabled"""
        return len(self.DATABASE_URIS) > 1
    
    def validate(self) -> bool:
        """Validate required configuration using Pydantic validation"""
        try:
            # Pydantic will validate during instantiation, so if we get here,
            # basic validation has already passed
            errors = self._settings.validate_all()
            if errors:
                for error in errors:
                    logger.error(f"Config validation error: {error}")
                return False
            
            if not self.ADMINS:
                logger.warning("No ADMINS configured - admin commands will be disabled")
            
            return True
        except Exception as e:
            logger.error(f"Configuration validation failed: {e}")
            return False


class MediaSearchBot(Client):
    """Enhanced bot client with dependency injection"""

    def __init__(
            self,
            config: BotConfig,
            db_pool: DatabaseConnectionPool,
            cache_manager: CacheManager,
            rate_limiter: RateLimiter
    ):
        self.background_tasks = None
        self.subscription_manager = None
        self.config = config
        self.db_pool = db_pool
        self.cache = cache_manager
        self.rate_limiter = rate_limiter
        self.cache_invalidator = CacheInvalidator(cache_manager)
        
        # Multi-database manager (will be initialized if multi-DB is enabled)
        self.multi_db_manager: Optional[MultiDatabaseManager] = None

        # Initialize repositories
        self.user_repo: Optional[UserRepository] = None
        self.media_repo: Optional[MediaRepository] = None
        self.channel_repo: Optional[ChannelRepository] = None
        self.connection_repo: Optional[ConnectionRepository] = None
        self.filter_repo: Optional[FilterRepository] = None
        self.batch_link_repo: Optional[BatchLinkRepository] = None
        self.subscription_manager: Optional[SubscriptionManager]
        self.bot_settings_repo: Optional[BotSettingsRepository] = None

        # Initialize services
        self.file_service: Optional[FileAccessService] = None
        self.broadcast_service: Optional[BroadcastService] = None
        self.maintenance_service: Optional[MaintenanceService] = None
        self.indexing_service: Optional[IndexingService] = None
        self.index_request_service: Optional[IndexRequestService] = None
        self.connection_service: Optional[ConnectionService] = None
        self.filter_service: Optional[FilterService] = None
        self.filestore_service: Optional[FileStoreService] = None
        self.bot_settings_service: Optional[BotSettingsService] = None

        # Handler references
        self.command_handler = None
        self.indexing_handler = None
        self.channel_handler = None
        self.connection_handler = None
        self.filestore_handler = None
        self.delete_handler = None
        self.request_handler = None
        # Bot info
        self.bot_id: Optional[int] = None
        self.bot_username: Optional[str] = None
        self.bot_name: Optional[str] = None

        super().__init__(
            name=config.SESSION,
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            bot_token=config.BOT_TOKEN,
            workers=config.WORKERS,
            sleep_threshold=5,
            parse_mode=ParseMode.HTML,
        )
        self.handler_manager = HandlerManager(self)
        logger.info("HandlerManager initialized")

    async def _initialize_broadcast_recovery(self):
        """Initialize broadcast state recovery after restart"""
        try:
            # Get the admin command handler to check broadcast state
            command_handler = self.handler_manager.handler_instances.get('command')
            if command_handler and hasattr(command_handler, 'admin_handler'):
                admin_handler = command_handler.admin_handler
                broadcast_state_key = "broadcast:state"
                
                # Check if there's a persistent broadcast state
                state = await self.cache.get(broadcast_state_key)
                if state == "active":
                    logger.warning(
                        "Found active broadcast state from previous session. "
                        "The broadcast may have been interrupted by restart. "
                        "Use /stop_broadcast to clear the state."
                    )
                    # Send notification to primary admin if configured
                    if self.config.ADMINS:
                        primary_admin = self.config.ADMINS[0]
                        try:
                            await self.send_message(
                                primary_admin,
                                "⚠️ <b>Broadcast State Recovery</b>\n\n"
                                "A broadcast was found to be active from the previous session. "
                                "It may have been interrupted by a restart.\n\n"
                                "Use /stop_broadcast to clear the broadcast state if needed.",
                                parse_mode='HTML'
                            )
                        except Exception as e:
                            logger.error(f"Failed to notify admin about broadcast state: {e}")
                            
                logger.info("Broadcast state recovery initialized")
        except Exception as e:
            logger.error(f"Error during broadcast state recovery: {e}")

    async def _initialize_handlers(self):
        """Initialize handlers after all services are ready"""
        from handlers.commands import CommandHandler
        from handlers.indexing import IndexingHandler
        from handlers.channel import ChannelHandler
        from handlers.filestore import FileStoreHandler
        from handlers.search import SearchHandler
        from handlers.delete import DeleteHandler
        from handlers.commands_handlers.database import DatabaseCommandHandler

        try:
            # Store all handler instances in manager for centralized tracking
            handlers_config = [
                ('delete', DeleteHandler(self)),
                ('command', CommandHandler(self)),
                ('filestore', FileStoreHandler(self)),
                ('indexing', IndexingHandler(self, self.indexing_service, self.index_request_service)),
                ('channel', ChannelHandler(self, self.channel_repo)),
                ('request', RequestHandler(self)),
                ('search', SearchHandler(self)),
                ('database', DatabaseCommandHandler(self))
            ]

            # Register all handlers through manager
            for name, handler in handlers_config:
                self.handler_manager.handler_instances[name] = handler
                logger.info(f"Registered handler: {name}")

            # Add filter handlers if enabled
            if not self.config.DISABLE_FILTER:
                from handlers.connection import ConnectionHandler
                from handlers.filter import FilterHandler

                filter_handlers = [
                    ('connection', ConnectionHandler(self, self.connection_service)),
                    ('filter', FilterHandler(self))
                ]

                for name, handler in filter_handlers:
                    self.handler_manager.handler_instances[name] = handler
                    logger.info(f"Registered filter handler: {name}")

            logger.info(f"Total handlers initialized: {len(self.handler_manager.handler_instances)}")
            
            # Initialize broadcast state recovery after handlers are ready
            await self._initialize_broadcast_recovery()

        except Exception as e:
            logger.error(f"Error initializing handlers: {e}")
            raise

    async def _set_bot_commands(self):
        """Set bot commands for the menu"""
        from pyrogram.types import BotCommand, BotCommandScopeDefault, BotCommandScopeAllPrivateChats, \
            BotCommandScopeAllGroupChats, BotCommandScopeChat

        try:
            # Basic commands for all users
            basic_commands = [
                BotCommand("start", "✨ Start the bot"),
                BotCommand("help", "📚 Show help message"),
                BotCommand("about", "ℹ️ About the bot"),
                BotCommand("stats", "📊 Bot statistics"),
                BotCommand("plans", "💎 View premium plans"),
                BotCommand("request_stats","📝 View your request limits and warnings"),
            ]

            # Connection commands (if filters enabled)
            connection_commands = []
            if not self.config.DISABLE_FILTER:
                connection_commands = [
                    BotCommand("connect", "🔗 Connect to a group"),
                    BotCommand("disconnect", "❌ Disconnect from group"),
                    BotCommand("connections", "📋 View all connections"),
                ]

            # Filter commands for groups (if filters enabled)
            filter_commands = []
            if not self.config.DISABLE_FILTER:
                filter_commands = [
                    BotCommand("add", "➕ Add a filter"),
                    BotCommand("filter", "➕ Add a filter (alias)"),
                    BotCommand("filters", "📋 View all filters"),
                    BotCommand("viewfilters", "📋 View all filters (alias)"),
                    BotCommand("del", "🗑 Delete a filter"),
                    BotCommand("delf", "🗑 Delete a filter (alias)"),
                    BotCommand("delall", "🗑 Delete all filters"),
                    BotCommand("delallf", "🗑 Delete all filters (alias)"),
                ]

            # File store commands (if public file store or for admins)
            filestore_commands = []
            if self.config.PUBLIC_FILE_STORE:
                filestore_commands = [
                    BotCommand("link", "🔗 Get shareable link"),
                    BotCommand("plink", "🔒 Get protected link"),
                    BotCommand("batch", "📦 Create batch link"),
                    BotCommand("pbatch", "🔒 Create protected batch"),
                    BotCommand("batch_premium", "💎 Create premium batch link"),
                    BotCommand("pbatch_premium", "💎🔒 Create premium protected batch"),
                    BotCommand("bprem", "💎 Premium batch (alias)"),
                    BotCommand("pbprem", "💎🔒 Premium protected batch (alias)"),
                ]

            # Admin-only commands
            admin_basic_commands = [
                BotCommand("users", "👥 Get users count"),
                BotCommand("broadcast", "📢 Broadcast message"),
                BotCommand("stop_broadcast", "🛑 Stop ongoing broadcast"),
                BotCommand("reset_broadcast_limit", "🔄 Reset broadcast rate limit"),
                BotCommand("ban", "🚫 Ban a user"),
                BotCommand("unban", "✅ Unban a user"),
                BotCommand("addpremium", "⭐ Add premium status"),
                BotCommand("removepremium", "❌ Remove premium status"),
            ]

            # Channel management commands
            channel_commands = [
                BotCommand("add_channel", "➕ Add channel for indexing"),
                BotCommand("remove_channel", "❌ Remove channel"),
                BotCommand("list_channels", "📋 List all channels"),
                BotCommand("toggle_channel", "🔄 Enable/disable channel"),
                BotCommand("setskip", "⏩ Set indexing skip"),
            ]

            # File management commands
            file_management_commands = [
                BotCommand("delete", "🗑 Delete file from database"),
                BotCommand("deleteall", "🗑 Delete files by keyword"),
            ]

            # System commands
            system_commands = [
                BotCommand("log", "📄 Get bot logs"),
                BotCommand("performance", "⚡ View performance"),
                BotCommand("restart", "🔄 Restart the bot"),
            ]

            # Cache commands
            cache_commands = [
                BotCommand("cache_stats", "📊 Cache statistics"),
                BotCommand("cache_analyze", "🔍 Analyze cache"),
                BotCommand("cache_cleanup", "🧹 Clean cache"),
            ]

            # Database management commands (multi-database system)
            database_commands = [
                BotCommand("dbstats", "🗃️ Database statistics"),
                BotCommand("dbinfo", "ℹ️ Database information"),
                BotCommand("dbswitch", "🔄 Switch write database"),
            ]

            # Primary admin only commands
            primary_admin_commands = [
                BotCommand("bsetting", "⚙️ Bot settings menu"),
                BotCommand("verify", "✅ Verify file access"),
                BotCommand("cancel", "❌ Cancel current operation"),
                BotCommand("shell", "💻 Execute shell command"),
            ]

            # Filestore admin commands (if not public)
            filestore_admin_commands = []
            if not self.config.PUBLIC_FILE_STORE:
                filestore_admin_commands = [
                    BotCommand("link", "🔗 Get shareable link"),
                    BotCommand("plink", "🔒 Get protected link"),
                    BotCommand("batch", "📦 Create batch link"),
                    BotCommand("pbatch", "🔒 Create protected batch"),
                    BotCommand("batch_premium", "💎 Create premium batch link"),
                    BotCommand("pbatch_premium", "💎🔒 Create premium protected batch"),
                    BotCommand("bprem", "💎 Premium batch (alias)"),
                    BotCommand("pbprem", "💎🔒 Premium protected batch (alias)"),
                ]

            # === SET COMMANDS FOR DIFFERENT SCOPES ===

            # 1. Default commands for all users in private chats
            all_private_commands = basic_commands.copy()
            all_private_commands.extend(connection_commands)
            all_private_commands.extend(filestore_commands)

            await self.set_bot_commands(all_private_commands, scope=BotCommandScopeAllPrivateChats())

            # 2. Commands for all group chats
            all_group_commands = basic_commands.copy()
            if not self.config.DISABLE_FILTER:
                all_group_commands.extend(filter_commands)
                all_group_commands.extend(connection_commands)

            await self.set_bot_commands(all_group_commands, scope=BotCommandScopeAllGroupChats())

            # 3. Set admin commands for each admin
            for admin_id in self.config.ADMINS:
                try:
                    admin_commands = basic_commands.copy()
                    admin_commands.extend(connection_commands)
                    admin_commands.extend(admin_basic_commands)
                    admin_commands.extend(channel_commands)
                    admin_commands.extend(file_management_commands)
                    admin_commands.extend(system_commands)
                    admin_commands.extend(cache_commands)
                    admin_commands.extend(database_commands)
                    admin_commands.extend(filestore_admin_commands)

                    # Add filter commands for admins even in private
                    if not self.config.DISABLE_FILTER:
                        admin_commands.extend(filter_commands)

                    # Primary admin gets additional commands
                    if admin_id == self.config.ADMINS[0]:
                        admin_commands.extend(primary_admin_commands)

                    await self.set_bot_commands(
                        admin_commands,
                        scope=BotCommandScopeChat(chat_id=admin_id)
                    )

                except Exception as e:
                    logger.warning(f"Failed to set commands for admin {admin_id}: {e}")

            # 4. Set default commands (shown when bot is added to new chats)
            default_commands = basic_commands.copy()
            await self.set_bot_commands(default_commands, scope=BotCommandScopeDefault())

            logger.info("✅ Bot commands set successfully for all scopes")

        except Exception as e:
            logger.error(f"Failed to set bot commands: {e}")

    async def invalidate_user_cache(self, user_id: int):
        """Invalidate all cache for a user"""
        await self.cache_invalidator.invalidate_user_cache(user_id)
    async def start(self):
        """Start the bot with all dependencies"""
        try:
            # Initialize database connections
            if self.config.is_multi_database_enabled:
                logger.info(f"Multi-database mode enabled with {len(self.config.DATABASE_URIS)} databases")
                
                # Initialize multi-database manager
                self.multi_db_manager = MultiDatabaseManager()
                await self.multi_db_manager.initialize(
                    self.config.DATABASE_URIS,
                    self.config.DATABASE_NAMES,
                    size_limit_gb=self.config.DATABASE_SIZE_LIMIT_GB,
                    auto_switch=self.config.DATABASE_AUTO_SWITCH
                )
                logger.info("Multi-database manager initialized")
                
                # Still initialize single db_pool for backward compatibility
                await self.db_pool.initialize(
                    self.config.DATABASE_URI,
                    self.config.DATABASE_NAME
                )
            else:
                # Single database mode
                await self.db_pool.initialize(
                    self.config.DATABASE_URI,
                    self.config.DATABASE_NAME
                )
                logger.info("Single database connection pool initialized")

            # Initialize Redis cache
            await self.cache.initialize()
            logger.info("Redis cache initialized")

            # Initialize repositories
            self.user_repo = UserRepository(
                self.db_pool,
                self.cache,
                premium_duration_days=self.config.PREMIUM_DURATION_DAYS,
                daily_limit=self.config.NON_PREMIUM_DAILY_LIMIT
            )
            self.media_repo = MediaRepository(
                self.db_pool, 
                self.cache, 
                multi_db_manager=self.multi_db_manager
            )
            self.channel_repo = ChannelRepository(self.db_pool, self.cache)
            self.connection_repo = ConnectionRepository(self.db_pool, self.cache)
            self.filter_repo = FilterRepository(self.db_pool, self.cache, collection_name=self.config.COLLECTION_NAME)
            self.batch_link_repo = BatchLinkRepository(self.db_pool, self.cache)
            self.bot_settings_repo = BotSettingsRepository(self.db_pool, self.cache)

            # Create basic indexes (existing)
            await self.media_repo.create_indexes()
            await self.channel_repo.create_index([('enabled', 1)])  # Add index for channels
            await self.user_repo.create_index([('status', 1)])
            
            # Create optimized compound indexes
            index_optimizer = IndexOptimizer(self.db_pool)
            try:
                index_results = await index_optimizer.create_all_indexes()
                successful_indexes = sum(1 for success in index_results.values() if success)
                total_indexes = len(index_results)
                logger.info(f"Database indexes optimized: {successful_indexes}/{total_indexes} created successfully")
            except Exception as e:
                logger.warning(f"Failed to create some optimized indexes: {e}")
                # Continue startup even if index creation fails
            await self.user_repo.create_index([('premium_expire', 1)])  # For expired premium checks
            await self.connection_repo.create_index([('user_id', 1)])
            await self.filter_repo.create_index([('group_id', 1), ('text', 1)])
            await self.batch_link_repo.create_indexes()  # Create all batch link indexes
            await self.bot_settings_repo.create_index([('key', 1)])
            logger.info("Database indexes created")

            self.bot_settings_service = BotSettingsService(
                self.bot_settings_repo,
                self.cache
            )

            # Initialize settings from environment
            await self.bot_settings_service.initialize_settings()
            logger.info("Bot settings initialized")

            # CRITICAL: Load settings from database and update config
            db_settings = await self.bot_settings_service.get_all_settings()
            for key, setting_data in db_settings.items():
                if hasattr(self.config, key):
                    # Store original value for critical settings
                    if key in ['DATABASE_URI', 'DATABASE_NAME', 'REDIS_URI']:
                        setattr(self.config, f'_original_{key}', getattr(self.config, key))
                    setattr(self.config, key, setting_data['value'])
            logger.info("Loaded settings from database")

            # Initialize services (not using singletons)
            self.file_service = FileAccessService(
                self.user_repo,
                self.media_repo,
                self.cache,
                self.rate_limiter,
                self.config
            )
            self.broadcast_service = BroadcastService(
                self.user_repo,
                self.cache,
                self.rate_limiter
            )
            self.maintenance_service = MaintenanceService(
                self.user_repo,
                self.media_repo,
                self.cache
            )

            self.indexing_service = IndexingService(
                self.media_repo,
                self.cache
            )

            self.index_request_service = IndexRequestService(
                self.indexing_service,
                self.cache,
                self.config.INDEX_REQ_CHANNEL,
                self.config.LOG_CHANNEL
            )

            if not self.config.DISABLE_FILTER:
                self.connection_service = ConnectionService(
                    self.connection_repo,
                    self.cache,
                    self.config.ADMINS
                )

                self.filter_service = FilterService(
                    self.filter_repo,
                    self.cache,
                    self.connection_service,
                    self.config
                )
            else:
                self.connection_service = None
                self.filter_service = None
                logger.info("Filter and connection services disabled via DISABLE_FILTER config")

            self.filestore_service = FileStoreService(
                self.media_repo,
                self.cache,
                self.config,
                self.batch_link_repo
            )

            logger.info("Services initialized")
            logger.info("Services initialized with database settings")


            # Load banned users/chats
            banned_users = await self.user_repo.get_banned_users()
            # Store in cache for quick access
            await self.cache.set(
                CacheKeyGenerator.banned_users(),
                banned_users,
                expire=CacheTTLConfig.BANNED_USERS_LIST
            )
            self.subscription_manager = SubscriptionManager(
                auth_channel=self.config.AUTH_CHANNEL,
                auth_groups=self.config.AUTH_GROUPS  # Now uses database values!
            )
            self.background_tasks = []
            # Start Pyrogram client
            await super().start()

            # Get bot info
            me = await self.get_me()
            self.bot_id = me.id
            self.bot_username = me.username
            self.bot_name = me.first_name

            logger.info(
                f"{self.bot_name} with Pyrogram v{__version__} (Layer {layer}) "
                f"started on @{self.bot_username}"
            )

            await self._set_bot_commands()
            # Initialize handlers after bot is started
            await self._initialize_handlers()
            
            # Start session manager cleanup task
            if hasattr(self, 'session_manager'):
                await self.session_manager.start_cleanup_task()
                logger.info("Session manager cleanup task started")

            # noinspection PyTypeChecker
            self.handler_manager.create_background_task( # noqa
                self._run_maintenance_tasks(),
                name="maintenance_tasks"
            )

            # Send startup message
            await self._send_startup_message()

            # Start web server
            await self._start_web_server()

        except Exception as e:
            logger.error(f"Error starting bot: {e}")
            raise

    async def stop(self, *args):
        """Stop the bot and cleanup resources"""
        logger.info("=" * 60)
        logger.info("Starting bot shutdown sequence...")

        # Stop session manager cleanup task
        if hasattr(self, 'session_manager'):
            await self.session_manager.stop_cleanup_task()
            logger.info("Session manager stopped")

        # Get handler manager stats before cleanup
        if self.handler_manager:
            stats = self.handler_manager.get_stats()
            logger.info(f"Handler Manager Stats: {stats}")

            # Cleanup handler manager (this handles all handlers and tasks)
            await self.handler_manager.cleanup()

        # Stop Pyrogram client
        await super().stop()

        # Close database connections
        await self.db_pool.close()

        # Close Redis connection
        await self.cache.close()

        logger.info("Bot stopped successfully")
        logger.info("=" * 60)

    def _get_git_info(self):
        """Get current git information"""
        import subprocess
        try:
            # Get current commit hash
            hash_result = subprocess.run(['git', 'rev-parse', 'HEAD'], 
                                       capture_output=True, text=True, check=True)
            commit_hash = hash_result.stdout.strip()[:7]  # Short hash
            
            # Get commit date and message
            commit_info = subprocess.run(['git', 'log', '-1', '--format=%cd|%s', '--date=format:%Y-%m-%d %H:%M'], 
                                       capture_output=True, text=True, check=True)
            commit_date, commit_message = commit_info.stdout.strip().split('|', 1)
            
            # Check for uncommitted changes
            status_result = subprocess.run(['git', 'status', '--porcelain'], 
                                         capture_output=True, text=True, check=True)
            has_changes = bool(status_result.stdout.strip())
            
            return {
                'hash': commit_hash,
                'date': commit_date,
                'message': commit_message,
                'has_changes': has_changes,
                'full_hash': hash_result.stdout.strip()
            }
        except Exception as e:
            logger.error(f"Failed to get git info: {e}")
            return None

    async def _send_startup_message(self):
        """Send startup message to log channel"""
        import json
        try:
            restart_msg_file = Path("restart_msg.txt")
            if restart_msg_file.exists():
                # Read the saved restart data
                with open(restart_msg_file, "r") as f:
                    content = f.read().strip()
                    
                    # Try to parse as JSON (new format)
                    try:
                        restart_data = json.loads(content)
                        chat_id = restart_data['chat_id']
                        msg_id = restart_data['message_id']
                        git_before = restart_data.get('git_before')
                    except (json.JSONDecodeError, KeyError):
                        # Fallback to old format
                        chat_id, msg_id = content.split(",")
                        chat_id = int(chat_id)
                        msg_id = int(msg_id)
                        git_before = None

                # Get current git info
                git_current = self._get_git_info()
                
                # Build success message with git info
                if git_current:
                    success_msg = (
                        f"✅ <b>Bot restarted successfully!</b>\n\n"
                        f"📝 <b>Current Version:</b>\n"
                        f"🔗 <code>{git_current['hash']}</code> - {git_current['date']}\n"
                        f"💬 {git_current['message']}"
                    )
                    
                    if git_current['has_changes']:
                        success_msg += f"\n⚠️ <b>Local changes detected</b>"
                        
                    # Show update info if we have before/after data
                    if git_before and git_before.get('full_hash') != git_current['full_hash']:
                        success_msg += f"\n\n🆕 <b>Updated from:</b> <code>{git_before['hash']}</code>"
                else:
                    success_msg = "✅ <b>Bot restarted successfully!</b>"

                # Try to edit the restart message
                try:
                    await self.edit_message_text(
                        chat_id=chat_id,
                        message_id=msg_id,
                        text=success_msg
                    )
                except Exception as e:
                    logger.error(f"Failed to edit restart message: {e}")

                # Delete the file
                restart_msg_file.unlink()
        except Exception as e:
            logger.error(f"Error handling restart message: {e}")
        if not self.config.LOG_CHANNEL:
            return

        # Use UTC for consistency, then display in IST for humans
        now_utc = datetime.now(UTC)
        tz = pytz.timezone('Asia/Kolkata')
        now = now_utc.astimezone(tz)

        startup_text = (
            "<b>🤖 Bot Restarted!</b>\n\n"
            f"📅 Date: <code>{now.strftime('%Y-%m-%d')}</code>\n"
            f"⏰ Time: <code>{now.strftime('%H:%M:%S %p')}</code>\n"
            f"🌐 Timezone: <code>Asia/Kolkata</code>\n"
            f"🛠 Version: <code>2.0.9 [Optimized]</code>\n"
            f"⚡ Status: <code>Online</code>"
        )
        if self.subscription_manager:
            check_results = await self.subscription_manager.check_auth_channels_accessibility(self)
            if not check_results['accessible']:
                startup_text += "\n\n⚠️ <b>Auth Channel Issues:</b>\n"
                for error in check_results['errors']:
                    startup_text += f"• {error['type']} ({error['id']}): {error['error']}\n"

                for admin_id in self.config.ADMINS[:3]:  # Notify first 3 admins
                    try:
                        error_msg = "⚠️ <b>Bot Configuration Issue</b>\n\n"
                        error_msg += "The bot cannot access some force subscription channels:\n\n"
                        for error in check_results['errors']:
                            error_msg += f"• <b>{error['type']}</b> <code>{error['id']}</code>\n"
                            error_msg += f"  Error: {error['error']}\n\n"
                        error_msg += "Please add the bot to these channels/groups and make it an admin."

                        await self.send_message(admin_id, error_msg)
                    except Exception as e:
                        logger.error(f"Failed to notify admin {admin_id}: {e}")

        try:
            await self.send_message(
                chat_id=self.config.LOG_CHANNEL,
                text=startup_text
            )
        except Exception as e:
            logger.error(f"Failed to send startup message: {e}")

    async def _start_web_server(self):
        """Start web server for health checks"""
        app = web.Application()

        # Health check endpoint
        async def health_check(request):
            stats = await self.maintenance_service.get_system_stats()
            return web.json_response({
                'status': 'healthy',
                'bot_username': self.bot_username,
                'stats': stats
            })

        # Performance metrics endpoint
        async def performance_metrics(request):
            try:
                metrics = await performance_monitor.get_metrics()
                return web.json_response({
                    'status': 'success',
                    'metrics': metrics,
                    'bot_username': self.bot_username
                })
            except Exception as e:
                logger.error(f"Error getting performance metrics: {e}")
                return web.json_response({
                    'status': 'error',
                    'error': str(e)
                }, status=500)

        app.router.add_get('/', health_check)
        app.router.add_get('/health', health_check)
        app.router.add_get('/metrics', performance_metrics)
        app.router.add_get('/performance', performance_metrics)

        cors = aiohttp_cors.setup(app, defaults={
            "*": aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*",
                allow_methods="*"
            )
        })
        for route in list(app.router.routes()):
            cors.add(route)
        runner = web.AppRunner(app)
        await runner.setup()

        site = web.TCPSite(runner, '0.0.0.0', self.config.PORT)
        await site.start()

    async def iter_messages(
            self,
            chat_id: Union[int, str],
            last_msg_id: int,
            first_msg_id: int = 0,
            batch_size: int = 200
    ) -> AsyncGenerator[Message, None]:
        """Iterate messages from ``first_msg_id`` to ``last_msg_id``.

        This helper mimics Telethon's ``iter_messages`` for compatibility.
        Messages are yielded in ascending order.
        """
        current = max(first_msg_id + 1, 1)

        while current <= last_msg_id:
            end = min(current + batch_size - 1, last_msg_id)
            ids = list(range(current, end + 1))
            messages = await self.get_messages(chat_id, ids)

            if not isinstance(messages, list):
                messages = [messages]

            for message in sorted(messages, key=lambda m: m.id):
                yield message

            current = end + 1

    async def _run_maintenance_tasks(self):
        """Run periodic maintenance tasks"""
        while not self.handler_manager.is_shutting_down():
            try:
                # Check if manager is shutting down
                if self.handler_manager.is_shutting_down():
                    logger.info("Maintenance task detected shutdown, exiting")
                    break

                # Run daily maintenance
                await self.maintenance_service.run_daily_maintenance()

                # Clear old cache entries periodically
                await self._cleanup_old_cache()

                # Sleep for 24 hours with periodic shutdown checks
                for _ in range(240):  # Check every 6 minutes (240 * 6min = 24 hours)
                    if self.handler_manager.is_shutting_down():
                        break
                    await asyncio.sleep(CacheTTLConfig.MAINTENANCE_CHECK_INTERVAL)

            except asyncio.CancelledError:
                logger.info("Maintenance task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in maintenance task: {e}")
                await asyncio.sleep(CacheTTLConfig.MAINTENANCE_RETRY_DELAY)

    async def _cleanup_old_cache(self):
        """Clean up old cache entries"""
        try:
            # Clear old search results
            deleted = await self.cache.delete_pattern("search_results_*")
            logger.info(f"Cleaned up {deleted} old search result caches")

            # Session cleanup is now handled by unified session manager

        except Exception as e:
            logger.error(f"Error cleaning cache: {e}")


async def initialize_bot() -> MediaSearchBot:
    """Initialize bot with all dependencies"""
    # Load configuration (now uses centralized settings)
    config = BotConfig()

    # Validate configuration
    if not config.validate():
        raise ValueError("Invalid configuration")

    # Initialize components using centralized settings
    db_pool = DatabaseConnectionPool()
    cache_manager = CacheManager(settings.redis.uri)
    session_manager = UnifiedSessionManager(cache_manager)
    rate_limiter = RateLimiter(cache_manager)

    # Create bot instance
    bot = MediaSearchBot(config, db_pool, cache_manager, rate_limiter)
    bot.session_manager = session_manager

    return bot


def run():
    """Main entry point WITH uvloop optimization"""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Suppress noisy loggers
    logging.getLogger("pyrogram").setLevel(logging.WARNING)
    logging.getLogger("imdbpy").setLevel(logging.WARNING)
    if sys.platform == 'linux' or sys.platform == 'linux2':
        # Try to use uvloop if not already set
        if not UVLOOP_AVAILABLE:
            try:
                import uvloop
                asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
                logger.info("Using uvloop for better performance")
            except ImportError:
                logger.warning("uvloop not available, using default event loop")
                logger.info("Install uvloop for better performance: pip install uvloop")

        import resource
        # Increase file descriptor limit
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (100000, 100000))
        except (ValueError, OSError) as e:
            logger.debug(f"Could not set resource limit: {e}")
            pass
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    # Run bot
    bot = loop.run_until_complete(initialize_bot())
    if sys.platform != 'win32':
        import signal

        def signal_handler(sig, frame):
            logger.info(f"Received signal {sig}, shutting down gracefully...")
            asyncio.create_task(shutdown(bot))

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    async def shutdown(bot):
        """Graceful shutdown handler"""
        logger.info("Starting graceful shutdown...")

        # Cancel all running tasks
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()

        # Wait for all tasks to complete
        await asyncio.gather(*tasks, return_exceptions=True)

        # Close bot connections
        await bot.stop()

        logger.info("Graceful shutdown complete")

    bot.run()


if __name__ == "__main__":
    run()
