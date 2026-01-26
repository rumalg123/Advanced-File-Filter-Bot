from pyrogram import Client
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from core.utils.error_formatter import ErrorMessageFormatter
from core.utils.helpers import format_file_size
from core.utils.file_emoji import get_file_type_display_name
import core.utils.messages as config_messages
from core.utils.messages import MessageHelper
from repositories.media import FileType
from handlers.commands_handlers.base import BaseCommandHandler
from handlers.decorators import require_subscription

from core.utils.logger import get_logger
logger = get_logger(__name__)


class UserCallbackHandler(BaseCommandHandler):
    """Handler for user-related callbacks"""

    @require_subscription()
    async def handle_help_callback(self, client: Client, query: CallbackQuery):
        """Handle help button callback"""
        help_text = MessageHelper.get_help_message(self.bot.config).format(bot_username=self.bot.bot_username)

        if query.from_user and query.from_user.id in self.bot.config.ADMINS:
            help_text += (
                "\n<b>Admin Commands:</b>\n"
                "• /users - Total users count\n"
                "• /broadcast - Broadcast message\n"
                "• /ban <user_id> - Ban user\n"
                "• /unban <user_id> - Unban user\n"
                "• /addpremium <user_id> - Add premium\n"
                "• /removepremium <user_id> - Remove premium\n"
                "• /setskip <number> - Set indexing skip\n"
                "\n<b>Channel Management:</b>\n"
                "• /add_channel <id> - Add channel for indexing\n"
                "• /remove_channel <id> - Remove channel\n"
                "• /list_channels - List all channels\n"
                "• /toggle_channel <id> - Enable/disable channel\n"
            )

        back_button = InlineKeyboardMarkup([
            [ButtonBuilder.action_button("⬅️ Back", callback_data="start_menu")]
        ])

        await query.message.edit_text(help_text, reply_markup=back_button)
        await query.answer()

    @require_subscription()
    async def handle_about_callback(self, client: Client, query: CallbackQuery):
        """Handle about button callback"""
        about_text = MessageHelper.get_about_message(self.bot.config).format(bot_username=self.bot.bot_username, bot_name=self.bot.bot_name)

        back_button = InlineKeyboardMarkup([
            [ButtonBuilder.action_button("⬅️ Back", callback_data="start_menu")]
        ])

        await query.message.edit_text(about_text, reply_markup=back_button)
        await query.answer()

    @require_subscription()
    async def handle_stats_callback(self, client: Client, query: CallbackQuery):
        """Handle stats button callback"""
        # Get comprehensive stats
        stats = await self.bot.maintenance_service.get_system_stats()

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
            f"└ Size: {format_file_size(stats['files']['total_size'])}\n"
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

        back_button = InlineKeyboardMarkup([
            [ButtonBuilder.action_button("⬅️ Back", callback_data="start_menu")]
        ])

        await query.message.edit_text(text, reply_markup=back_button)
        await query.answer()

    @require_subscription()
    async def handle_plans_callback(self, client: Client, query: CallbackQuery):
        """Handle plans button callback"""
        if self.bot.config.DISABLE_PREMIUM:
            await query.answer(ErrorMessageFormatter.format_success("Premium features are disabled. Enjoy unlimited access!"))
            return

        user_id = query.from_user.id
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

        buttons = [
            [ButtonBuilder.action_button("💳 Get Premium", url=self.bot.config.PAYMENT_LINK)],
            [ButtonBuilder.action_button("⬅️ Back", callback_data="start_menu")]
        ]

        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        await query.answer()

    async def handle_start_menu_callback(self, client: Client, query: CallbackQuery):
        """Handle back to start menu"""
        user_id = query.from_user.id

        # Ensure user exists in database
        if not await self.bot.user_repo.is_user_exist(user_id):
            await self.bot.user_repo.create_user(
                user_id,
                query.from_user.first_name or "User"
            )

        # Send welcome message
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
        mention = query.from_user.mention
        # Check for custom start message from bot settings
        start_msg_template = MessageHelper.get_start_message(self.bot.config)
        welcome_text = start_msg_template.format(
            mention=mention,
            user_id=query.from_user.id,
            first_name=query.from_user.first_name or "User",
            bot_name=self.bot.bot_name,
            bot_username=self.bot.bot_username
        )

        await query.message.edit_text(
            welcome_text,
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        await query.answer()