from functools import wraps
from typing import Union, Optional, Callable

from pyrogram import Client
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup

from core.utils.logger import get_logger
from core.utils.validators import (
    extract_user_id, is_admin, is_auth_user, is_bot_user,
    get_special_channels, is_special_channel
)
from repositories.user import UserStatus

logger = get_logger(__name__)


class SubscriptionRequired:
    """Decorator class for handling subscription requirements"""

    @staticmethod
    def require_subscription(
            skip_for_admins: bool = True,
            skip_for_auth_users: bool = True,
            custom_message: Optional[str] = None
    ):
        """
        Decorator to require subscription before accessing commands
        """

        def decorator(func: Callable):
            @wraps(func)
            async def wrapper(self, client: Client, message: Union[Message, CallbackQuery], *args, **kwargs):
                # Get chat based on message type
                if isinstance(message, CallbackQuery):
                    chat = message.message.chat if message.message else None
                else:
                    chat = message.chat

                # Check special channels using validator
                special_channels = get_special_channels(self.bot.config)
                if chat and is_special_channel(chat.id, special_channels):
                    return

                # Skip if message is from a bot
                if is_bot_user(message):
                    return

                user_id = extract_user_id(message)

                if not user_id:
                    if isinstance(message, Message):
                        await message.reply_text("❌ Anonymous users cannot use this bot.")
                    return

                # Skip check for admins
                if skip_for_admins and is_admin(user_id, self.bot.config.ADMINS):
                    return await func(self, client, message, *args, **kwargs)

                # Skip check for auth users
                auth_users = getattr(self.bot.config, 'AUTH_USERS', [])
                if skip_for_auth_users and is_auth_user(user_id, auth_users):
                    return await func(self, client, message, *args, **kwargs)

                # Check if auth channel/groups are configured
                if not self.bot.config.AUTH_CHANNEL and not getattr(self.bot.config, 'AUTH_GROUPS', []):
                    return await func(self, client, message, *args, **kwargs)

                # Check subscription
                is_subscribed = await self.bot.subscription_manager.is_subscribed(
                    client, user_id
                )
                if not is_subscribed:
                    await SubscriptionRequired._send_subscription_message(
                        self.bot, client, message, custom_message
                    )
                    return

                # User is subscribed, proceed with original function
                return await func(self, client, message, *args, **kwargs)

            return wrapper

        return decorator

    @staticmethod
    async def _send_subscription_message(
            bot,
            client: Client,
            message: Union[Message, CallbackQuery],
            custom_message: Optional[str] = None
    ):
        """Send subscription required message with join buttons"""
        original_user_id = extract_user_id(message)

        if not original_user_id:
            return

        # Determine callback data based on message type
        callback_data = f"checksub#{original_user_id}#general"

        if isinstance(message, Message):
            cmds = getattr(message, "command", []) or []
            if len(cmds) > 1:
                callback_data = f"checksub#{original_user_id}#{cmds[1]}"
            elif message.text and not message.text.startswith("/"):
                callback_data = f"checksub#{original_user_id}#search"
        elif isinstance(message, CallbackQuery):
            if message.data.startswith('file#'):
                callback_data = f"checksub#{original_user_id}#{message.data}"

        # Build buttons using subscription manager
        buttons = await bot.subscription_manager.build_subscription_buttons(
            client=client,
            user_id=original_user_id,
            custom_callback_data=callback_data
        )

        # Default subscription message
        if not custom_message:
            custom_message = (
                "🔒 <b>Subscription Required</b>\n"
                "You need to join our channel(s) to use this bot.\n"
                "Please join the required channel(s) and try again."
            )

        reply_markup = InlineKeyboardMarkup(buttons)

        if isinstance(message, Message):
            await message.reply_text(
                custom_message,
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
        elif isinstance(message, CallbackQuery):
            await message.answer(
                "🔒 You need to join our channel(s) first!",
                show_alert=True
            )


# Create decorator instance for easy import
require_subscription = SubscriptionRequired.require_subscription


# Add this to handlers/decorators.py after the existing SubscriptionRequired class

class BanCheck:
    """Decorator class for checking if user is banned"""

    @staticmethod
    def check_ban():
        """Decorator to check if user is banned before executing commands"""

        def decorator(func: Callable):
            @wraps(func)
            async def wrapper(self, client: Client, message: Union[Message, CallbackQuery], *args, **kwargs):
                user_id = extract_user_id(message)

                if not user_id:
                    return

                # Skip ban check for admins
                if is_admin(user_id, self.bot.config.ADMINS):
                    return await func(self, client, message, *args, **kwargs)

                # Check if user is banned
                user = await self.bot.user_repo.get_user(user_id)
                if user and user.status == UserStatus.BANNED:
                    ban_text = (
                        "🚫 <b>You are banned from using this bot</b>\n"
                        f"<b>Reason:</b> {user.ban_reason or 'No reason provided'}\n"
                        f"<b>Banned on:</b> {user.updated_at.strftime('%Y-%m-%d %H:%M:%S') if user.updated_at else 'Unknown'}\n"
                        "Contact the bot admin if you think this is a mistake."
                    )

                    if isinstance(message, Message):
                        await message.reply_text(ban_text)
                    elif isinstance(message, CallbackQuery):
                        await message.answer(ban_text, show_alert=True)
                    return

                return await func(self, client, message, *args, **kwargs)

            return wrapper

        return decorator


# Add to the end of the file
check_ban = BanCheck.check_ban