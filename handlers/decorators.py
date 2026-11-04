import html
from functools import wraps
from typing import Union, Optional, Callable

from pyrogram import Client
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup

from core.database.errors import USER_ACCESS_RETRY_MESSAGE
from core.utils.error_formatter import ErrorMessageFormatter
from core.utils.logger import get_logger
from core.utils.messages import MessageHelper
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
                    from core.utils.error_formatter import ErrorMessageFormatter
                    if isinstance(message, Message):
                        await message.reply_text(ErrorMessageFormatter.format_error("Anonymous users cannot use this bot"))
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
            callback_data = f"checksub#{original_user_id}#cb#{message.data}"

        # Build buttons using subscription manager
        buttons = await bot.subscription_manager.build_subscription_buttons(
            client=client,
            user_id=original_user_id,
            custom_callback_data=callback_data
        )

        # Default subscription message - check bot config first
        if not custom_message:
            # Get bot config if available
            bot_config = getattr(bot, 'config', None)
            custom_message = MessageHelper.get_force_sub_message(bot_config)

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
            try:
                await message.message.reply_text(
                    custom_message,
                    reply_markup=reply_markup,
                    disable_web_page_preview=True
                )
            except Exception as e:
                logger.debug(f"Failed to send callback subscription message: {e}")


# Create decorator instance for easy import
require_subscription = SubscriptionRequired.require_subscription


# Add this to handlers/decorators.py after the existing SubscriptionRequired class

class BanCheck:
    """Check authoritative ban state before user operations."""

    @staticmethod
    async def _deny(message, html_text: str, plain_text: str):
        if isinstance(message, CallbackQuery) or (
            hasattr(message, 'answer') and hasattr(message, 'data')
        ):
            encoded = plain_text.encode('utf-8')
            if len(encoded) > 200:
                plain_text = encoded[:197].decode('utf-8', errors='ignore') + '…'
            await message.answer(plain_text, show_alert=True)
        elif hasattr(message, 'reply_text'):
            await message.reply_text(html_text)

    @staticmethod
    def check_ban():
        def decorator(func: Callable):
            @wraps(func)
            async def wrapper(self, client: Client, message: Union[Message, CallbackQuery], *args, **kwargs):
                user_id = extract_user_id(message)
                if not user_id:
                    return
                admins = getattr(getattr(self.bot, 'config', None), 'ADMINS', []) or []
                if is_admin(user_id, admins):
                    return await func(self, client, message, *args, **kwargs)
                try:
                    user = await self.bot.user_repo.get_user(user_id, use_cache=False)
                except Exception:
                    logger.warning("Ban state unavailable for %s", user_id, exc_info=True)
                    await BanCheck._deny(message, USER_ACCESS_RETRY_MESSAGE, USER_ACCESS_RETRY_MESSAGE)
                    return
                if user and user.status == UserStatus.BANNED:
                    reason = user.ban_reason or 'No reason provided'
                    ban_date = user.updated_at.strftime('%Y-%m-%d %H:%M:%S') if user.updated_at else 'Unknown'
                    await BanCheck._deny(
                        message,
                        ErrorMessageFormatter.format_access_denied("You are banned from using this bot") + "\n"
                        f"<b>Reason:</b> {html.escape(str(reason))}\n<b>Banned on:</b> {ban_date}\n"
                        "Contact the bot admin if you think this is a mistake.",
                        ErrorMessageFormatter.format_access_denied("You are banned from using this bot", plain_text=True) + "\n"
                        f"Reason: {reason}\nBanned on: {ban_date}\n"
                        "Contact the bot admin if you think this is a mistake.",
                    )
                    return
                return await func(self, client, message, *args, **kwargs)
            return wrapper
        return decorator


# Add to the end of the file
check_ban = BanCheck.check_ban
