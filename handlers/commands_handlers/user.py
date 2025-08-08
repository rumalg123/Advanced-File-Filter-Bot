import logging

from pyrogram import Client
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
import core.utils.messages as config_messages
from core.utils.helpers import format_file_size
from handlers.commands_handlers.base import BaseCommandHandler, private_only
from handlers.decorators import require_subscription, check_ban

from core.utils.logger import get_logger
logger = get_logger(__name__)


class UserCommandHandler(BaseCommandHandler):
    """Handler for user commands"""

    @check_ban()
    async def start_command(self, client: Client, message: Message):
        """Handle /start command - NO subscription check here to allow new users"""
        user_id = message.from_user.id if message.from_user else None
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
                    await client.send_message(
                        self.bot.config.LOG_CHANNEL,
                        f"#NewUser\n"
                        f"ID: <code>{user_id}</code>\n"
                        f"Name: {message.from_user.mention}"
                    )
                except Exception as e:
                    logger.error(f"Failed to log new user: {e}")

        # Handle deep link
        if len(message.command) > 1:
            # Import here to avoid circular imports
            from handlers.deeplink import DeepLinkHandler
            deeplink_handler = DeepLinkHandler(self.bot)
            await deeplink_handler.handle_deep_link(client, message, message.command[1])
            return

        # Send welcome message
        buttons = [
            [
                InlineKeyboardButton(
                    "➕ Add me to Group",
                    url=f"https://t.me/{self.bot.bot_username}?startgroup=true"
                )
            ],
            [
                InlineKeyboardButton("📚 Help", callback_data="help"),
                InlineKeyboardButton("ℹ️ About", callback_data="about")
            ],
            [
                InlineKeyboardButton("📊 Stats", callback_data="stats"),
                InlineKeyboardButton("💎 Premium", callback_data="plans")
            ]
        ]
        if self.bot.config.SUPPORT_GROUP_URL and self.bot.config.SUPPORT_GROUP_NAME:
            buttons.append([
                InlineKeyboardButton(
                    f"💬 {self.bot.config.SUPPORT_GROUP_NAME}",
                    url=self.bot.config.SUPPORT_GROUP_URL
                )
            ])

        # welcome_text = (
        #     f"👋 Welcome {}!\n\n"
        #     f"I'm a powerful media search bot that can help you find files quickly.\n\n"
        #     f"{'✅ Premium features are disabled - enjoy unlimited access!' if self.bot.config.DISABLE_PREMIUM else f'🆓 Free users can retrieve up to {self.bot.config.NON_PREMIUM_DAILY_LIMIT} files per day.'}\n\n"
        #     f"Use /help to learn more about my features."
        # )
        mention = message.from_user.mention
        welcome_text = config_messages.START_MSG.format(mention=mention)

        await message.reply_text(
            welcome_text,
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    @check_ban()
    @require_subscription()
    async def help_command(self, client: Client, message: Message):
        """Handle /help command"""
        help_text =config_messages.HELP_MSG.format(bot_username=self.bot.bot_username)

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
        about_text = config_messages.ABOUT_MSG.format(bot_username=self.bot.bot_username,bot_name=self.bot.bot_name)
        await message.reply_text(about_text)

    @check_ban()
    @require_subscription()
    async def stats_command(self, client: Client, message: Message):
        """Handle stats command"""
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
            for file_type, data in stats['files']['by_type'].items():
                text += f"├ {file_type.title()}: {data['count']:,} ({format_file_size(data['size'])})\n"

        await message.reply_text(text)

    @check_ban()
    @private_only
    @require_subscription()
    async def plans_command(self, client: Client, message: Message):
        """Handle plans command"""
        if self.bot.config.DISABLE_PREMIUM:
            await message.reply_text("✅ Premium features are disabled. Enjoy unlimited access!")
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
            f"⭐ <b>Premium Plan:</b>\n"
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
            InlineKeyboardButton("💳 Get Premium", url="https://your-payment-link.com")
        ]]

        await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))