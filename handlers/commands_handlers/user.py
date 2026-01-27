import random
import uuid

from pyrogram import Client
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

import core.utils.messages as config_messages
from core.utils.messages import MessageHelper
from core.utils.helpers import format_file_size
from core.utils.file_emoji import get_file_type_display_name
from core.utils.button_builder import ButtonBuilder
from core.utils.error_formatter import ErrorMessageFormatter
from core.utils.caption import CaptionFormatter
from core.cache.config import CacheTTLConfig, CacheKeyGenerator
from repositories.media import FileType
from core.utils.logger import get_logger
from core.utils.telegram_api import telegram_api
from core.utils.validators import private_only, extract_user_id, skip_subscription_check
from handlers.commands_handlers.base import BaseCommandHandler
from handlers.decorators import require_subscription, check_ban

logger = get_logger(__name__)


class UserCommandHandler(BaseCommandHandler):
    """Handler for user commands"""

    @check_ban()
    async def start_command(self, client: Client, message: Message):
        """Handle /start command with subscription check for deeplinks"""
        user_id = extract_user_id(message)
        if not user_id:
            return

        # Ensure user exists in database
        if not await self.bot.user_repo.is_user_exist(user_id):
            await self.bot.user_repo.create_user(
                user_id,
                message.from_user.first_name or "User"
            )

            # Log new user
            if self.bot.config.LOG_CHANNEL:
                try:
                    await telegram_api.call_api(
                        client.send_message,
                        self.bot.config.LOG_CHANNEL,
                        f"#NewUser\n"
                        f"ID: <code>{user_id}</code>\n"
                        f"Name: {message.from_user.mention}",
                        chat_id=self.bot.config.LOG_CHANNEL
                    )
                except Exception as e:
                    logger.error(f"Failed to log new user: {e}")

        # Handle deep link
        if len(message.command) > 1:
            # Check subscription for deeplinks using validator
            skip_sub = skip_subscription_check(
                user_id,
                self.bot.config.ADMINS,
                getattr(self.bot.config, 'AUTH_USERS', [])
            )

            # Check if auth channel/groups are configured and user needs to subscribe
            if not skip_sub and (self.bot.config.AUTH_CHANNEL or getattr(self.bot.config, 'AUTH_GROUPS', [])):
                is_subscribed = await self.bot.subscription_manager.is_subscribed(
                    client, user_id
                )

                if not is_subscribed:
                    # Send subscription message with the deeplink parameter
                    await self._send_subscription_message_for_deeplink(
                        client, message, message.command[1]
                    )
                    return

            # User is subscribed or doesn't need subscription, handle deeplink
            from handlers.deeplink import DeepLinkHandler
            deeplink_handler = DeepLinkHandler(self.bot)
            # Remove the decorator from handle_deep_link since we're checking here
            await deeplink_handler.handle_deep_link_internal(client, message, message.command[1])
            return

        # Send welcome message (rest of the original code remains the same)
        buttons = [
            [
                ButtonBuilder.action_button(
                    "➕ Add me to Group",
                    url=f"https://t.me/{self.bot.bot_username}?startgroup=true"
                )
            ],
            [
                ButtonBuilder.action_button("📚 Help", callback_data="help"),
                ButtonBuilder.action_button("ℹ️ About", callback_data="about")
            ],
            [
                ButtonBuilder.action_button("📊 Stats", callback_data="stats"),
                ButtonBuilder.action_button("💎 Premium", callback_data="plans")
            ]
        ]

        if self.bot.config.SUPPORT_GROUP_URL and self.bot.config.SUPPORT_GROUP_NAME:
            buttons.append([
                ButtonBuilder.action_button(
                    f"💬 {self.bot.config.SUPPORT_GROUP_NAME}",
                    url=self.bot.config.SUPPORT_GROUP_URL
                )
            ])

        # Note: switch_inline_query_current_chat is not supported by ButtonBuilder yet
        buttons.append([
            InlineKeyboardButton("📁 Search Files", switch_inline_query_current_chat='')
        ])

        buttons.append([
            ButtonBuilder.action_button("🍺 Buy me a Beer", url=self.bot.config.PAYMENT_LINK)
        ])
        # Get start message (checks bot config first, then falls back to default)
        start_msg_template = MessageHelper.get_start_message(self.bot.config)
        welcome_text = start_msg_template.format(
            mention=message.from_user.mention,
            user_id=user_id,
            first_name=message.from_user.first_name or "User",
            bot_name=self.bot.bot_name,
            bot_username=self.bot.bot_username
        )

        if self.bot.config.PICS:
            await message.reply_photo(
                photo=random.choice(self.bot.config.PICS),
                caption=welcome_text,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            await message.reply_text(
                welcome_text,
                reply_markup=InlineKeyboardMarkup(buttons)
            )

    async def _send_subscription_message_for_deeplink(
            self, client: Client, message: Message, deeplink_param: str
    ):
        """Send subscription message for deeplink access"""
        from pyrogram.types import InlineKeyboardMarkup

        user_id = message.from_user.id

        # Store the deeplink parameter in cache with a short key
        session_id = uuid.uuid4().hex[:8]
        session_key = CacheKeyGenerator.deeplink_session(user_id, session_id)
        await self.bot.cache.set(
            session_key,
            {'deeplink': deeplink_param, 'user_id': user_id},
            expire=CacheTTLConfig.USER_DATA
        )

        # Build buttons using subscription manager
        buttons = await self.bot.subscription_manager.build_subscription_buttons(
            client=client,
            user_id=user_id,
            callback_type="deeplink",
            session_key=session_key
        )

        # Get subscription message from bot config or default
        message_text = MessageHelper.get_force_sub_message(self.bot.config)

        await message.reply_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(buttons),
            disable_web_page_preview=True
        )

    @check_ban()
    @require_subscription()
    async def help_command(self, client: Client, message: Message):
        """Handle /help command"""
        help_text = MessageHelper.get_help_message(self.bot.config).format(bot_username=self.bot.bot_username)

        if message.from_user and message.from_user.id in self.bot.config.ADMINS:
            help_text += (
                "\n<b>Admin Commands:</b>\n"
                "• /users - Total users count\n"
                "• /broadcast - Broadcast message\n"
                "• /ban <user_id> - Ban user\n"
                "• /unban <user_id> - Unban user\n"
                "• /addpremium <user_id> - Add premium\n"
                "• /removepremium <user_id> - Remove premium\n"
                "• /setskip <number> - Set indexing skip\n"
                "• /performance - View bot performance metrics\n"
                "\n<b>Channel Management:</b>\n"
                "• /add_channel <id> - Add channel for indexing\n"
                "• /remove_channel <id> - Remove channel\n"
                "• /list_channels - List all channels\n"
                "• /toggle_channel <id> - Enable/disable channel\n"
            )

        await message.reply_text(help_text)

    @check_ban()
    @require_subscription()
    async def about_command(self, client: Client, message: Message):
        """Handle /about command"""
        about_text = MessageHelper.get_about_message(self.bot.config).format(bot_username=self.bot.bot_username, bot_name=self.bot.bot_name)
        await message.reply_text(about_text)

    @check_ban()
    @require_subscription()
    async def stats_command(self, client: Client, message: Message):
        """Handle stats command"""
        # Get comprehensive stats
        try:
            stats = await self.bot.maintenance_service.get_system_stats()
        except Exception as e:
            logger.error(f"Error getting system stats: {e}")
            await message.reply_text(ErrorMessageFormatter.format_error("Error retrieving statistics. Please try again later."))
            return

        # Format stats message
        text = (
            f"📊 <b>Bot Statistics</b>\n\n"
            f"<b>👥 Users:</b>\n"
            f"├ Total: {stats['users']['total']:,}\n"
            f"├ Premium: {stats['users']['premium']:,}\n"
            f"├ Banned: {stats['users']['banned']:,}\n"
            f"└ Active Today: {stats['users']['active_today']:,}\n\n"
            f"<b>📁 Files:</b>\n"
            f"├ Total: {stats['files']['total_files']:,}\n"
            f"└ Size: {format_file_size(stats['files']['total_size'])}\n\n"
            f"<b>💾 Database Storage:</b>\n"
            f"├ Total: {format_file_size(stats.get('storage', {}).get('total_size', 0))}\n"
            f"├ Data: {format_file_size(stats.get('storage', {}).get('database_size', 0))}\n"
            f"├ Indexes: {format_file_size(stats.get('storage', {}).get('index_size', 0))}\n"
            f"└ Objects: {stats.get('storage', {}).get('objects_count', 0):,}\n"
        )

        # Add file type breakdown
        if stats['files']['by_type']:
            text += "\n<b>📊 By Type:</b>\n"
            from core.utils.file_type import get_file_type_from_value
            for file_type_str, data in stats['files']['by_type'].items():
                file_type = get_file_type_from_value(file_type_str)
                if file_type:
                    display_name = get_file_type_display_name(file_type)
                else:
                    display_name = file_type_str.title()
                text += f"├ {display_name}: {data['count']:,} ({format_file_size(data['size'])})\n"

        # Add collection breakdown (top 3 by size)
        if stats.get('storage', {}).get('collections'):
            collections = stats['storage']['collections']
            # Sort by storage size and show top 3
            sorted_collections = sorted(
                collections.items(), 
                key=lambda x: x[1]['storage_size'], 
                reverse=True
            )[:3]
            
            if sorted_collections:
                text += "\n<b>🗂 Top Collections:</b>\n"
                for i, (coll_name, coll_data) in enumerate(sorted_collections):
                    display_name = coll_name.replace('_', ' ').title()
                    symbol = "└" if i == len(sorted_collections) - 1 else "├"
                    text += f"{symbol} {display_name}: {format_file_size(coll_data['storage_size'])}\n"

        await message.reply_text(text)

    @check_ban()
    @private_only
    @require_subscription()
    async def plans_command(self, client: Client, message: Message):
        """Handle plans command"""
        if self.bot.config.DISABLE_PREMIUM:
            await message.reply_text(ErrorMessageFormatter.format_success("Premium features are disabled. Enjoy unlimited access!"))
            return

        user_id = message.from_user.id
        user = await self.bot.user_repo.get_user(user_id)

        # Build plans message
        text = (
            "💎 <b>Premium Plans</b>\n\n"
            f"🎯 <b>Free Plan:</b>\n"
            f"├ {self.bot.config.NON_PREMIUM_DAILY_LIMIT} files per day\n"
            f"├ Basic search features\n"
            f"└ Standard support\n\n"
            f"⭐ <b>Premium Plan:</b> <b>{self.bot.config.PREMIUM_PRICE}</b>\n"
            f"├ Unlimited file access\n"
            f"├ Priority support\n"
            f"├ Advanced features\n"
            f"└ Duration: {self.bot.config.PREMIUM_DURATION_DAYS} days\n\n"
        )

        # Add current status
        if user:
            if user.is_premium:
                is_active, status_msg = await self.bot.user_repo.check_and_update_premium_status(user)
                text += f"✅ <b>Your Status:</b> {status_msg}\n"
            else:
                remaining = self.bot.config.NON_PREMIUM_DAILY_LIMIT - user.daily_retrieval_count
                text += f"📊 <b>Your Status:</b> Free Plan\n"
                text += f"📁 Today's Usage: {user.daily_retrieval_count}/{self.bot.config.NON_PREMIUM_DAILY_LIMIT}\n"
                text += f"📁 Remaining: {remaining}\n"

        buttons = [[
            ButtonBuilder.action_button("💳 Get Premium", url=self.bot.config.PAYMENT_LINK)
        ]]

        await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    @check_ban()
    @require_subscription()
    async def request_stats_command(self, client: Client, message: Message):
        """Show user's request statistics"""
        user_id = message.from_user.id
        stats = await self.bot.user_repo.get_request_stats(user_id)

        if not stats['exists']:
            await message.reply_text(
                ErrorMessageFormatter.format_not_found("Request data") + ". Make your first request using #request in the support group!")
            return

        # Build stats message
        text = (
            "📊 <b>Your Request Statistics</b>\n\n"
            f"📅 <b>Today's Requests:</b> {stats['daily_requests']}/{stats['daily_limit']}\n"
            f"📁 <b>Remaining Today:</b> {stats['daily_remaining']}\n"
            f"{ErrorMessageFormatter.format_warning('Warnings', title='Warnings')}: {stats['warning_count']}/{stats['warning_limit']}\n"
            f"📈 <b>Total Requests:</b> {stats['total_requests']}\n"
        )

        if stats['is_at_limit']:
            text += "\n" + ErrorMessageFormatter.format_warning("Daily limit reached! Further requests will result in warnings.", title="Status")
        elif stats['is_warned']:
            text += "\n" + ErrorMessageFormatter.format_warning(f"You have {stats['warnings_remaining']} warnings remaining before ban.", title="Status")
        else:
            text += "\n" + ErrorMessageFormatter.format_success("You can make requests normally.", title="Status")

        if stats['warning_reset_in_days'] is not None:
            text += f"\n\n⏱ <b>Warning Reset:</b> {stats['warning_reset_in_days']} days"

        if stats['last_request_date']:
            text += f"\n📅 <b>Last Request:</b> {stats['last_request_date']}"

        await message.reply_text(text)

    @check_ban()
    @require_subscription()
    async def my_keywords_command(self, client: Client, message: Message):
        """Show user's most searched keywords as keyboard buttons"""
        user_id = message.from_user.id
        
        # Get search history service
        if not hasattr(self.bot, 'search_history_service') or not self.bot.search_history_service:
            await message.reply_text(
                ErrorMessageFormatter.format_error("Search history feature is not available.")
            )
            return
        
        # Get user's most searched keywords
        keywords = await self.bot.search_history_service.get_most_searched_keywords(user_id, limit=8)
        
        if not keywords:
            await message.reply_text(
                ErrorMessageFormatter.format_info(
                    "You haven't searched for anything yet. Start searching and your most used keywords will appear here!",
                    title="No Search History"
                )
            )
            return
        
        # Build keyboard with keywords (2 buttons per row)
        keyboard_buttons = []
        for i in range(0, len(keywords), 2):
            row = []
            # Add first button in row
            row.append(KeyboardButton(keywords[i]))
            # Add second button if exists
            if i + 1 < len(keywords):
                row.append(KeyboardButton(keywords[i + 1]))
            keyboard_buttons.append(row)
        
        # Add a "❌ Close" button at the end
        keyboard_buttons.append([KeyboardButton("❌ Close")])
        
        keyboard = ReplyKeyboardMarkup(
            keyboard_buttons,
            resize_keyboard=True,
            one_time_keyboard=False
        )
        
        text = (
            "🔍 <b>Your Most Searched Keywords</b>\n\n"
            f"<b>Top Searches:</b> {', '.join(keywords[:5])}\n\n"
            "Click any keyword to search, or type your own query.\n"
            "Use /my_keywords to refresh the list."
        )
        
        await message.reply_text(text, reply_markup=keyboard)

    @check_ban()
    @require_subscription()
    async def popular_keywords_command(self, client: Client, message: Message):
        """Show top 10 global searches as keyboard buttons"""
        # Get search history service
        if not hasattr(self.bot, 'search_history_service') or not self.bot.search_history_service:
            await message.reply_text(
                ErrorMessageFormatter.format_error("Search history feature is not available.")
            )
            return
        
        # Get global top searches
        keywords = await self.bot.search_history_service.get_global_top_searches(limit=10)
        
        if not keywords:
            await message.reply_text(
                ErrorMessageFormatter.format_info(
                    "No global search data available yet. Start searching and popular keywords will appear here!",
                    title="No Popular Searches"
                )
            )
            return
        
        # Build keyboard with keywords (2 buttons per row)
        keyboard_buttons = []
        for i in range(0, len(keywords), 2):
            row = []
            # Add first button in row
            row.append(KeyboardButton(keywords[i]))
            # Add second button if exists
            if i + 1 < len(keywords):
                row.append(KeyboardButton(keywords[i + 1]))
            keyboard_buttons.append(row)
        
        # Add a "❌ Close" button at the end
        keyboard_buttons.append([KeyboardButton("❌ Close")])
        
        keyboard = ReplyKeyboardMarkup(
            keyboard_buttons,
            resize_keyboard=True,
            one_time_keyboard=False
        )
        
        text = (
            "🔥 <b>Top 10 Popular Searches</b>\n\n"
            f"<b>Most Popular:</b> {', '.join(keywords[:5])}\n\n"
            "Click any keyword to search, or type your own query.\n"
            "Use /popular_keywords to refresh the list."
        )
        
        await message.reply_text(text, reply_markup=keyboard)

    @check_ban()
    @require_subscription()
    async def recommendations_command(self, client: Client, message: Message):
        """Show personalized recommendations for the user"""
        user_id = message.from_user.id
        
        # Get recommendation service
        if not hasattr(self.bot, 'recommendation_service') or not self.bot.recommendation_service:
            await message.reply_text(
                ErrorMessageFormatter.format_error("Recommendations feature is not available.")
            )
            return
        
        try:
            # Get recommendations
            recommendations = await self.bot.recommendation_service.get_recommendations_for_user(
                user_id, limit=10
            )
            
            text_parts = ["💡 <b>Personalized Recommendations</b>\n"]
            buttons = []
            
            # Similar queries section
            if recommendations.get('similar_queries'):
                text_parts.append("<b>🔍 Similar Searches:</b>")
                query_buttons = []
                for query in recommendations['similar_queries'][:6]:  # Show up to 6 queries
                    # Truncate long queries for display
                    display_query = query[:30] + "..." if len(query) > 30 else query
                    query_buttons.append(
                        ButtonBuilder.action_button(
                            f"🔍 {display_query}",
                            callback_data=f"search#page#{query}#0#0#{user_id}"
                        )
                    )
                if query_buttons:
                    # Add 2 per row
                    for i in range(0, len(query_buttons), 2):
                        buttons.append(query_buttons[i:i+2])
                    # Show query list in text
                    query_list = ", ".join([f"<code>{q[:20]}...</code>" if len(q) > 20 else f"<code>{q}</code>" 
                                           for q in recommendations['similar_queries'][:4]])
                    text_parts.append(f"  {query_list}\n")
            
            # Based on history section - fetch and display actual files
            if recommendations.get('based_on_history'):
                file_ids = recommendations['based_on_history'][:5]  # Limit to 5 files
                # Fetch files using batch lookup (efficient)
                files_dict = await self.bot.media_repo.find_files_batch(file_ids)
                files = [f for f in files_dict.values() if f is not None]  # Filter out None values
                
                if files:
                    text_parts.append(f"\n<b>📚 Based on Your History:</b> {len(files)} files")
                    # Show file names in text
                    from core.utils.file_emoji import get_file_emoji
                    file_names = []
                    file_buttons = []
                    for file in files[:5]:  # Show up to 5 files
                        emoji = get_file_emoji(file.file_type, file.file_name, file.mime_type)
                        # Truncate long filenames
                        display_name = file.file_name[:35] + "..." if len(file.file_name) > 35 else file.file_name
                        file_names.append(f"{emoji} <code>{display_name}</code>")
                        # Create clickable file button
                        file_buttons.append(
                            ButtonBuilder.file_button(file, user_id=user_id, is_private=True)
                        )
                    
                    # Add file names to text (2 per line)
                    for i in range(0, len(file_names), 2):
                        line = "  " + " • ".join(file_names[i:i+2])
                        text_parts.append(line)
                    
                    # Add file buttons (2 per row)
                    if file_buttons:
                        for i in range(0, len(file_buttons), 2):
                            buttons.append(file_buttons[i:i+2])
            
            # Trending section - fetch and display actual files
            if recommendations.get('trending_files'):
                file_ids = recommendations['trending_files'][:5]  # Limit to 5 files
                # Fetch files using batch lookup (efficient)
                files_dict = await self.bot.media_repo.find_files_batch(file_ids)
                files = [f for f in files_dict.values() if f is not None]  # Filter out None values
                
                if files:
                    text_parts.append(f"\n<b>🔥 Trending:</b> {len(files)} files")
                    # Show file names in text
                    from core.utils.file_emoji import get_file_emoji
                    file_names = []
                    file_buttons = []
                    for file in files[:5]:  # Show up to 5 files
                        emoji = get_file_emoji(file.file_type, file.file_name, file.mime_type)
                        # Truncate long filenames
                        display_name = file.file_name[:35] + "..." if len(file.file_name) > 35 else file.file_name
                        file_names.append(f"{emoji} <code>{display_name}</code>")
                        # Create clickable file button
                        file_buttons.append(
                            ButtonBuilder.file_button(file, user_id=user_id, is_private=True)
                        )
                    
                    # Add file names to text (2 per line)
                    for i in range(0, len(file_names), 2):
                        line = "  " + " • ".join(file_names[i:i+2])
                        text_parts.append(line)
                    
                    # Add file buttons (2 per row)
                    if file_buttons:
                        for i in range(0, len(file_buttons), 2):
                            buttons.append(file_buttons[i:i+2])
            
            if not recommendations.get('similar_queries') and not recommendations.get('based_on_history') and not recommendations.get('trending_files'):
                text_parts.append(
                    "\n" + ErrorMessageFormatter.format_info(
                        "Start searching to get personalized recommendations!",
                        title="No Recommendations Yet"
                    )
                )
            
            text = "\n".join(text_parts)
            
            # Add refresh and close buttons
            action_buttons = []
            if recommendations.get('similar_queries') or recommendations.get('based_on_history') or recommendations.get('trending_files'):
                action_buttons.append(ButtonBuilder.action_button("🔄 Refresh", callback_data="refresh_recommendations"))
            action_buttons.append(ButtonBuilder.action_button("❌ Close", callback_data="close_recommendations"))
            
            if action_buttons:
                buttons.append(action_buttons)
            
            await message.reply_text(
                text,
                reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
                parse_mode=CaptionFormatter.get_parse_mode()
            )
            
        except Exception as e:
            logger.error(f"Error getting recommendations: {e}", exc_info=True)
            await message.reply_text(
                ErrorMessageFormatter.format_error("Error getting recommendations. Please try again later.")
            )