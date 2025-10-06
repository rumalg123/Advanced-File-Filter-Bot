from pyrogram import filters
from pyrogram.handlers import MessageHandler, CallbackQueryHandler

from core.utils.logger import get_logger
from core.utils.verify_alignment import verify_alignment_command
from handlers.callbacks_handlers import UserCallbackHandler
from handlers.callbacks_handlers.file import FileCallbackHandler
from handlers.callbacks_handlers.filter import FilterCallBackHandler
from handlers.callbacks_handlers.pagination import PaginationCallbackHandler
# Import callback handlers
from handlers.callbacks_handlers.subscription import SubscriptionCallbackHandler
from handlers.commands_handlers.admin import AdminCommandHandler
from handlers.commands_handlers.bot_settings import BotSettingsHandler
from handlers.commands_handlers.channel import ChannelCommandHandler
# Import all command handlers
from handlers.commands_handlers.user import UserCommandHandler

logger = get_logger(__name__)




class CommandHandler:
    """Centralized command handler that coordinates all sub-handlers"""

    def __init__(self, bot):
        self.bot = bot

        # Initialize sub-handlers
        self.user_handler = UserCommandHandler(bot)
        self.admin_handler = AdminCommandHandler(bot)
        self.channel_handler = ChannelCommandHandler(bot)

        self.subscription_callback_handler = SubscriptionCallbackHandler(bot)
        self.file_callback_handler = FileCallbackHandler(bot)
        self.pagination_callback_handler = PaginationCallbackHandler(bot)
        self.filter_callback_handler = FilterCallBackHandler(bot)
        self.user_callback_handler = UserCallbackHandler(bot)
        self.bot_settings_handler = BotSettingsHandler(bot)

        # Register all handlers
        self.register_handlers()

    def register_handlers(self):
        """Register all command and callback handlers"""

        # User commands
        self.bot.add_handler(
            MessageHandler(self.user_handler.start_command, filters.command("start") & filters.incoming)
        )
        self.bot.add_handler(
            MessageHandler(self.user_handler.help_command, filters.command("help") & filters.incoming)
        )
        self.bot.add_handler(
            MessageHandler(self.user_handler.about_command, filters.command("about") & filters.incoming)
        )
        self.bot.add_handler(
            MessageHandler(self.user_handler.stats_command, filters.command("stats") & filters.incoming)
        )
        self.bot.add_handler(
            MessageHandler(self.user_handler.plans_command, filters.command("plans") & filters.private)
        )
        # Add this command registration in the user commands section:
        self.bot.add_handler(
            MessageHandler(
                self.user_handler.request_stats_command,
                filters.command("request_stats") & filters.private
            )
        )

        # In the register_handlers method, add this BEFORE registering search handlers (around line 42):

        # Bot settings management
        self.bot.add_handler(
            MessageHandler(
                self.bot_settings_handler.bsetting_command,
                filters.command("bsetting") & filters.user(self.bot.config.ADMINS[0:1])
            )
        )
        self.bot.add_handler(
            MessageHandler(
                self.bot_settings_handler.restart_command,
                filters.command("restart") & filters.user(self.bot.config.ADMINS)
            )
        )
        # Usage: Add to your admin commands
        self.bot.add_handler(
             MessageHandler(
                 verify_alignment_command,
                 filters.command("verify") & filters.user(self.bot.config.ADMINS)
             )
         )

        # Bot settings callbacks - single handler for all bset_ callbacks
        self.bot.add_handler(
            CallbackQueryHandler(
                self.bot_settings_handler.settings_callback,
                filters.regex(r"^bset_")
            )
        )


        # IMPORTANT: Add this handler for bot settings input BEFORE search handlers
        if self.bot.config.ADMINS:
            self.bot.add_handler(
                MessageHandler(
                    self.bot_settings_handler.handle_edit_input,
                    filters.text & filters.private & filters.user(self.bot.config.ADMINS[0]) & 
                    (filters.regex(r"^[^/]") | filters.command("cancel"))
                ),
                group=-5  # Higher priority than search
            )

        # Add standalone cancel handler for better reliability 
        if self.bot.config.ADMINS:
            self.bot.add_handler(
                MessageHandler(
                    self.bot_settings_handler.handle_cancel,
                    filters.command("cancel") & filters.private & filters.user(self.bot.config.ADMINS[0])
                ),
                group=-10  # Very high priority
            )

        # Callback handlers
        self.bot.add_handler(
            CallbackQueryHandler(
                self.subscription_callback_handler.handle_checksub_callback,
                filters.regex(r"^checksub")
            )
        )
        logger.info("Registering file callback handler with pattern: ^file#")
        self.bot.add_handler(
            CallbackQueryHandler(
                self.file_callback_handler.handle_file_callback,
                filters.regex(r"^file#")
            )
        )
        logger.info("File callback handler registered successfully")
        self.bot.add_handler(
            CallbackQueryHandler(
                self.file_callback_handler.handle_sendall_callback,
                filters.regex(r"^sendall#")
            )
        )
        self.bot.add_handler(
            CallbackQueryHandler(
                self.pagination_callback_handler.handle_search_pagination,
                filters.regex(r"^search#")
            )
        )
        self.bot.add_handler(
            CallbackQueryHandler(
                lambda c, q: q.answer(),
                filters.regex(r"^noop$")
            )
        )

        # In the register_handlers method, add these callback handlers:

        # Filter alert callback
        self.bot.add_handler(
            CallbackQueryHandler(
                self.filter_callback_handler.handle_filter_alert_callback,
                filters.regex(r"^alertmessage:")
            )
        )

        # Delete all filters confirmation
        self.bot.add_handler(
            CallbackQueryHandler(
                self.filter_callback_handler.handle_delall_confirm_callback,
                filters.regex(r"^delallconfirm#")
            )
        )

        # Delete all filters cancel
        self.bot.add_handler(
            CallbackQueryHandler(
                self.filter_callback_handler.handle_delall_cancel_callback,
                filters.regex(r"^delallcancel$")
            )
        )

        self.bot.add_handler(
            CallbackQueryHandler(
                self.user_callback_handler.handle_help_callback,
                filters.regex(r"^help$")
            )
        )
        self.bot.add_handler(
            CallbackQueryHandler(
                self.user_callback_handler.handle_about_callback,
                filters.regex(r"^about$")
            )
        )
        self.bot.add_handler(
            CallbackQueryHandler(
                self.user_callback_handler.handle_stats_callback,
                filters.regex(r"^stats$")
            )
        )
        self.bot.add_handler(
            CallbackQueryHandler(
                self.user_callback_handler.handle_plans_callback,
                filters.regex(r"^plans$")
            )
        )
        self.bot.add_handler(
            CallbackQueryHandler(
                self.user_callback_handler.handle_start_menu_callback,
                filters.regex(r"^start_menu$")
            )
        )
        
        # Broadcast confirmation callbacks
        if self.bot.config.ADMINS:
            self.bot.add_handler(
                CallbackQueryHandler(
                    self.admin_handler.handle_broadcast_confirmation,
                    filters.regex(r"^(confirm_broadcast|cancel_broadcast)$") & filters.user(self.bot.config.ADMINS)
                )
            )
        # Admin commands - check if ADMINS is configured
        if self.bot.config.ADMINS:
            # User management
            self.bot.add_handler(
                MessageHandler(
                    self.admin_handler.add_premium_command,
                    filters.command("addpremium") & filters.user(self.bot.config.ADMINS)
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.admin_handler.remove_premium_command,
                    filters.command("removepremium") & filters.user(self.bot.config.ADMINS)
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.admin_handler.broadcast_command,
                    filters.command("broadcast") & filters.user(self.bot.config.ADMINS)
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.admin_handler.stop_broadcast_command,
                    filters.command("stop_broadcast") & filters.user(self.bot.config.ADMINS)
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.admin_handler.reset_broadcast_limit_command,
                    filters.command("reset_broadcast_limit") & filters.user(self.bot.config.ADMINS)
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.admin_handler.users_command,
                    filters.command("users") & filters.user(self.bot.config.ADMINS)
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.admin_handler.ban_command,
                    filters.command("ban") & filters.user(self.bot.config.ADMINS)
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.admin_handler.unban_command,
                    filters.command("unban") & filters.user(self.bot.config.ADMINS)
                )
            )

            # Channel management
            self.bot.add_handler(
                MessageHandler(
                    self.channel_handler.add_channel_command,
                    filters.command("add_channel") & filters.user(self.bot.config.ADMINS)
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.channel_handler.remove_channel_command,
                    filters.command("remove_channel") & filters.user(self.bot.config.ADMINS)
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.channel_handler.list_channels_command,
                    filters.command("list_channels") & filters.user(self.bot.config.ADMINS)
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.channel_handler.toggle_channel_command,
                    filters.command("toggle_channel") & filters.user(self.bot.config.ADMINS)
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.admin_handler.log_command,
                    filters.command("log") & filters.user(self.bot.config.ADMINS)
                )
            )

            self.bot.add_handler(
                MessageHandler(
                    self.admin_handler.performance_command,
                    filters.command("performance") & filters.user(self.bot.config.ADMINS)
                )
            )

            if self.bot.config.ADMINS:
                # Cache monitoring commands
                self.bot.add_handler(
                    MessageHandler(
                        self.admin_handler.cache_stats_command,
                        filters.command("cache_stats") & filters.user(self.bot.config.ADMINS)
                    )
                )

                self.bot.add_handler(
                    MessageHandler(
                        self.admin_handler.cache_analyze_command,
                        filters.command("cache_analyze") & filters.user(self.bot.config.ADMINS)
                    )
                )

                self.bot.add_handler(
                    MessageHandler(
                        self.admin_handler.cache_cleanup_command,
                        filters.command("cache_cleanup") & filters.user(self.bot.config.ADMINS)
                    )
                )

                # Shell command - only for primary admin
                if self.bot.config.ADMINS:
                    self.bot.add_handler(
                        MessageHandler(
                            self.admin_handler.shell_command,
                            filters.command("shell") & filters.user(self.bot.config.ADMINS[0:1])
                        )
                    )



        logger.info("All command handlers registered successfully")