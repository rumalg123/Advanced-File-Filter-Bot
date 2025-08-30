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

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional, AsyncGenerator, Union

import pytz
from aiohttp import web
#from dotenv import load_dotenv
from pyrogram import Client, __version__
from pyrogram.raw.all import layer
from pyrogram.types import Message

from core.cache.redis_cache import CacheManager
from core.database.pool import DatabaseConnectionPool
from core.database.indexes import IndexOptimizer
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
from repositories.channel import ChannelRepository
from repositories.connection import ConnectionRepository
from repositories.filter import FilterRepository
from repositories.media import MediaRepository
from repositories.user import UserRepository
from core.cache.invalidation import CacheInvalidator
from core.utils.logger import get_logger
import core.utils.messages as default_messages

logger = get_logger(__name__)

#load_dotenv()
performance_monitor = PerformanceMonitor()


# bot.py - Replace BotConfig class (lines 33-147) with:

class BotConfig:
    """Centralized configuration management"""

    def __init__(self):
        # Bot settings
        self.SESSION = os.environ.get('SESSION', 'Media_search')
        self.API_ID = int(os.environ.get('API_ID', '0'))
        self.API_HASH = os.environ.get('API_HASH', '')
        self.BOT_TOKEN = os.environ.get('BOT_TOKEN', '')

        # Database settings
        self.DATABASE_URI = os.environ.get('DATABASE_URI', '')
        self.DATABASE_NAME = os.environ.get('DATABASE_NAME', 'PIRO')
        self.COLLECTION_NAME = os.environ.get('COLLECTION_NAME', 'FILES')

        # Redis settings
        self.REDIS_URI = os.environ.get('REDIS_URI', '')

        # Server settings
        self.PORT = int(os.environ.get('PORT', '8000'))
        self.WORKERS = int(os.environ.get('WORKERS', '50'))

        # Feature flags
        self.USE_CAPTION_FILTER = self._str_to_bool(
            os.environ.get('USE_CAPTION_FILTER', 'True')
        )
        self.DISABLE_PREMIUM = self._str_to_bool(
            os.environ.get('DISABLE_PREMIUM', 'True')
        )
        self.DISABLE_FILTER = self._str_to_bool(
            os.environ.get('DISABLE_FILTER', 'False')
        )

        # Limits
        self.PREMIUM_DURATION_DAYS = int(
            os.environ.get('PREMIUM_DURATION_DAYS', '30')
        )
        self.NON_PREMIUM_DAILY_LIMIT = int(
            os.environ.get('NON_PREMIUM_DAILY_LIMIT', '10')
        )
        self.MESSAGE_DELETE_SECONDS = int(
            os.environ.get('MESSAGE_DELETE_SECONDS', '300')
        )
        self.MAX_BTN_SIZE = int(
            os.environ.get('MAX_BTN_SIZE', '12')
        )

        # Channel and admin settings
        self.LOG_CHANNEL = int(os.environ.get('LOG_CHANNEL', '0'))
        self.INDEX_REQ_CHANNEL = int(os.environ.get('INDEX_REQ_CHANNEL', '0')) or self.LOG_CHANNEL
        self.ADMINS = self._parse_list(os.environ.get('ADMINS', ''))
        self.CHANNELS = self._parse_list(os.environ.get('CHANNELS', '0'))
        if 0 in self.CHANNELS:
            self.CHANNELS.remove(0)

        self.FILE_STORE_CHANNEL = self._parse_list(
            os.environ.get('FILE_STORE_CHANNEL', '')
        )
        self.PUBLIC_FILE_STORE = self._str_to_bool(
            os.environ.get('PUBLIC_FILE_STORE', 'False')
        )
        self.KEEP_ORIGINAL_CAPTION = self._str_to_bool(
            os.environ.get('KEEP_ORIGINAL_CAPTION', 'True')
        )
        self.USE_ORIGINAL_CAPTION_FOR_BATCH = self._str_to_bool(
            os.environ.get('USE_ORIGINAL_CAPTION_FOR_BATCH', 'True')
        )
        self.CUSTOM_FILE_CAPTION = os.environ.get('CUSTOM_FILE_CAPTION', '')
        self.BATCH_FILE_CAPTION = os.environ.get('BATCH_FILE_CAPTION', '')

        auth_channel = os.environ.get('AUTH_CHANNEL')
        self.AUTH_CHANNEL = int(auth_channel) if auth_channel and auth_channel.lstrip('-').isdigit() else None

        self.PICS = self._parse_list(os.environ.get('PICS', ''))

        auth_groups = os.environ.get('AUTH_GROUPS', '')
        self.AUTH_GROUPS = []
        if auth_groups:
            for group in auth_groups.split(','):
                group = group.strip()
                if group and group.lstrip('-').isdigit():
                    self.AUTH_GROUPS.append(int(group))

        auth_users = os.environ.get('AUTH_USERS', '')
        self.AUTH_USERS = []
        if auth_users:
            for user in auth_users.split(','):
                user = user.strip()
                if user and user.isdigit():
                    self.AUTH_USERS.append(int(user))

        self.AUTH_USERS.extend(self.ADMINS)
        self.DELETE_CHANNEL = int(os.environ.get('DELETE_CHANNEL', '0')) if os.environ.get('DELETE_CHANNEL') else None
        self.REQ_CHANNEL = int(os.environ.get('REQ_CHANNEL', '0')) or self.LOG_CHANNEL
        self.SUPPORT_GROUP_URL = os.environ.get('SUPPORT_GROUP_URL', '')
        self.SUPPORT_GROUP_NAME = os.environ.get('SUPPORT_GROUP_NAME', 'Support Group')
        self.SUPPORT_GROUP_ID = int(os.environ.get('SUPPORT_GROUP_ID', '0')) if os.environ.get(
            'SUPPORT_GROUP_ID') else None
        self.PAYMENT_LINK = os.environ.get('PAYMENT_LINK', 'https://buymeacoffee.com/matthewmurdock001')
        self.REQUEST_PER_DAY = int(os.environ.get('REQUEST_PER_DAY', '3'))
        self.REQUEST_WARNING_LIMIT = int(os.environ.get('REQUEST_WARNING_LIMIT', '5'))
        if self.REQUEST_PER_DAY >= self.REQUEST_WARNING_LIMIT:
            logger.warning(
                "REQUEST_PER_DAY must be less than REQUEST_WARNING_LIMIT. Setting REQUEST_WARNING_LIMIT = REQUEST_PER_DAY + 2")
            self.REQUEST_WARNING_LIMIT = self.REQUEST_PER_DAY + 2
        self.AUTO_DELETE_MESSAGE=os.environ.get('AUTO_DELETE_MESSAGE', default_messages.AUTO_DEL_MSG)
        self.START_MESSAGE=os.environ.get('START_MESSAGE', default_messages.START_MSG)

    @staticmethod
    def _str_to_bool(value: str) -> bool:
        """Convert string to boolean"""
        return value.lower() in ['true', 'yes', '1', 'enable', 'y']

    @staticmethod
    def _parse_list(value: str) -> list:
        """Parse comma-separated list"""
        if not value:
            return []
        items = []
        for item in value.split(','):
            item = item.strip()
            try:
                items.append(int(item))
            except ValueError:
                items.append(item)
        return items

    def validate(self) -> bool:
        """Validate required configuration"""
        required = [
            'BOT_TOKEN',
            'API_ID',
            'API_HASH',
            'DATABASE_URI',
            'DATABASE_NAME'
        ]

        for field in required:
            value = getattr(self, field)
            if not value or (isinstance(value, int) and value == 0):
                logger.error(f"Missing required configuration: {field}")
                return False

        if not self.ADMINS:
            logger.warning("No ADMINS configured - admin commands will be disabled")

        return True


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

        # Initialize repositories
        self.user_repo: Optional[UserRepository] = None
        self.media_repo: Optional[MediaRepository] = None
        self.channel_repo: Optional[ChannelRepository] = None
        self.connection_repo: Optional[ConnectionRepository] = None
        self.filter_repo: Optional[FilterRepository] = None
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
        )
        self.handler_manager = HandlerManager(self)
        logger.info("HandlerManager initialized")

    async def _initialize_handlers(self):
        """Initialize handlers after all services are ready"""
        from handlers.commands import CommandHandler
        from handlers.indexing import IndexingHandler
        from handlers.channel import ChannelHandler
        from handlers.filestore import FileStoreHandler
        from handlers.search import SearchHandler
        from handlers.delete import DeleteHandler

        try:
            # Store all handler instances in manager for centralized tracking
            handlers_config = [
                ('delete', DeleteHandler(self)),
                ('command', CommandHandler(self)),
                ('filestore', FileStoreHandler(self)),
                ('indexing', IndexingHandler(self, self.indexing_service, self.index_request_service)),
                ('channel', ChannelHandler(self, self.channel_repo)),
                ('request', RequestHandler(self)),
                ('search', SearchHandler(self))
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
                    BotCommand("filters", "📋 View all filters"),
                    BotCommand("del", "🗑 Delete a filter"),
                    BotCommand("delall", "🗑 Delete all filters"),
                ]

            # File store commands (if public file store or for admins)
            filestore_commands = []
            if self.config.PUBLIC_FILE_STORE:
                filestore_commands = [
                    BotCommand("link", "🔗 Get shareable link"),
                    BotCommand("plink", "🔒 Get protected link"),
                    BotCommand("batch", "📦 Create batch link"),
                    BotCommand("pbatch", "🔒 Create protected batch"),
                ]

            # Admin-only commands
            admin_basic_commands = [
                BotCommand("users", "👥 Get users count"),
                BotCommand("broadcast", "📢 Broadcast message"),
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

            # Primary admin only commands
            primary_admin_commands = [
                BotCommand("bsetting", "⚙️ Bot settings menu"),
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
            # Initialize database connection pool
            await self.db_pool.initialize(
                self.config.DATABASE_URI,
                self.config.DATABASE_NAME
            )
            logger.info("Database connection pool initialized")

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
            self.media_repo = MediaRepository(self.db_pool, self.cache)
            self.channel_repo = ChannelRepository(self.db_pool, self.cache)
            self.connection_repo = ConnectionRepository(self.db_pool, self.cache)
            self.filter_repo = FilterRepository(self.db_pool, self.cache, collection_name=self.config.COLLECTION_NAME)
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
                self.config
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

            # noinspection PyTypeChecker
            self.handler_manager.create_background_task( # noqa
                self._run_maintenance_tasks(),
                name="maintenance_tasks"
            )

            # Send startup message
            await self._send_startup_message()

            # Start web server
            await self._start_web_server()


            # Start background tasks
            self.background_tasks.append(
                asyncio.create_task(self._run_maintenance_tasks())
            )

        except Exception as e:
            logger.error(f"Error starting bot: {e}")
            raise

    async def stop(self, *args):
        """Stop the bot and cleanup resources"""
        logger.info("=" * 60)
        logger.info("Starting bot shutdown sequence...")

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

    async def _send_startup_message(self):
        """Send startup message to log channel"""
        try:
            restart_msg_file = Path("restart_msg.txt")
            if restart_msg_file.exists():
                # Read the saved message info
                with open(restart_msg_file, "r") as f:
                    content = f.read().strip()
                    chat_id, msg_id = content.split(",")
                    chat_id = int(chat_id)
                    msg_id = int(msg_id)

                # Try to edit the restart message
                try:
                    await self.edit_message_text(
                        chat_id=chat_id,
                        message_id=msg_id,
                        text="✅ **Bot restarted successfully!**"
                    )
                except Exception as e:
                    logger.error(f"Failed to edit restart message: {e}")

                # Delete the file
                restart_msg_file.unlink()
        except Exception as e:
            logger.error(f"Error handling restart message: {e}")
        if not self.config.LOG_CHANNEL:
            return

        tz = pytz.timezone('Asia/Kolkata')
        now = datetime.now(tz)

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
                        error_msg = "⚠️ **Bot Configuration Issue**\n\n"
                        error_msg += "The bot cannot access some force subscription channels:\n\n"
                        for error in check_results['errors']:
                            error_msg += f"• **{error['type']}** `{error['id']}`\n"
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
                    await asyncio.sleep(360)  # 6 minutes

            except asyncio.CancelledError:
                logger.info("Maintenance task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in maintenance task: {e}")
                await asyncio.sleep(3600)  # Retry in 1 hour

    async def _cleanup_old_cache(self):
        """Clean up old cache entries"""
        try:
            # Clear old search results
            deleted = await self.cache.delete_pattern("search_results_*")
            logger.info(f"Cleaned up {deleted} old search result caches")

            # Clear old session data
            deleted = await self.cache.delete_pattern("edit_session:*")
            logger.info(f"Cleaned up {deleted} old edit sessions")

        except Exception as e:
            logger.error(f"Error cleaning cache: {e}")


async def initialize_bot() -> MediaSearchBot:
    """Initialize bot with all dependencies"""
    # Load configuration
    config = BotConfig()

    # Validate configuration
    if not config.validate():
        raise ValueError("Invalid configuration")

    # Initialize components
    db_pool = DatabaseConnectionPool()
    cache_manager = CacheManager(config.REDIS_URI)
    rate_limiter = RateLimiter(cache_manager)

    # Create bot instance
    bot = MediaSearchBot(config, db_pool, cache_manager, rate_limiter)

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
        except:
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
