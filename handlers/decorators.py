from functools import wraps
from typing import Union, Optional, Callable

from pyrogram import Client
from pyrogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from core.utils.logger import get_logger
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
                # Get chat and user based on message type
                if isinstance(message, CallbackQuery):
                    chat = message.message.chat if message.message else None
                    from_user = message.from_user
                else:
                    chat = message.chat
                    from_user = message.from_user

                # Check special channels
                special_channels = [
                    self.bot.config.LOG_CHANNEL,
                    self.bot.config.INDEX_REQ_CHANNEL,
                    self.bot.config.REQ_CHANNEL,
                    self.bot.config.DELETE_CHANNEL
                ]
                special_channels = {ch for ch in special_channels if ch}

                if chat and chat.id in special_channels:
                    return

                # Also skip if message is from a bot
                if from_user and from_user.is_bot:
                    return

                user_id = from_user.id if from_user else None

                if not user_id:
                    if isinstance(message, Message):
                        await message.reply_text("❌ Anonymous users cannot use this bot.")
                    return

                # Skip check for admins
                if skip_for_admins and user_id in self.bot.config.ADMINS:
                    return await func(self, client, message, *args, **kwargs)

                # Skip check for auth users
                if skip_for_auth_users and user_id in getattr(self.bot.config, 'AUTH_USERS', []):
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
        if isinstance(message, CallbackQuery):
            original_user_id = message.from_user.id if message.from_user else None
        else:
            original_user_id = message.from_user.id if message.from_user else None

        if not original_user_id:
            return
        # Build buttons for required subscriptions
        buttons = []
        # AUTH_CHANNEL button
        if bot.config.AUTH_CHANNEL:
            try:
                chat_link = await bot.subscription_manager.get_chat_link(
                    client, bot.config.AUTH_CHANNEL
                )

                # Get channel name
                try:
                    chat = await client.get_chat(bot.config.AUTH_CHANNEL)
                    channel_name = chat.title or f"Channel {bot.config.AUTH_CHANNEL}"
                except:
                    channel_name = f"Updates Channel"

                buttons.append([
                    InlineKeyboardButton(
                        f"📢 Join {channel_name}",
                        url=chat_link
                    )
                ])
            except Exception as e:
                logger.error(f"Error creating AUTH_CHANNEL button: {e}")

        # AUTH_GROUPS buttons
        if hasattr(bot.config, 'AUTH_GROUPS') and bot.config.AUTH_GROUPS:
            for group_id in bot.config.AUTH_GROUPS:
                try:
                    chat_link = await bot.subscription_manager.get_chat_link(
                        client, group_id
                    )

                    # Get group name
                    try:
                        chat = await client.get_chat(group_id)
                        group_name = chat.title or f"Group {group_id}"
                    except:
                        group_name = f"Required Group"

                    buttons.append([
                        InlineKeyboardButton(
                            f"👥 Join {group_name}",
                            url=chat_link
                        )
                    ])
                except Exception as e:
                    logger.error(f"Error creating AUTH_GROUP button for {group_id}: {e}")

        # Add "Try Again" button with callback data
        callback_data = f"checksub#{original_user_id}#general"

        if isinstance(message, Message):
            cmds = getattr(message, "command", []) or []
            # For start command with parameters
            if len(cmds) > 1:
                callback_data = f"checksub#{original_user_id}#{cmds[1]}"
            elif message.text and not message.text.startswith("/"):
                callback_data = f"checksub#{original_user_id}#search"
        elif isinstance(message, CallbackQuery):
            # For callbacks, extract the original action
            if message.data.startswith('file#'):
                callback_data = f"checksub#{original_user_id}#{message.data}"

        buttons.append([
            InlineKeyboardButton("🔄 Try Again", callback_data=callback_data)
        ])

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
            # Don't edit the message for callbacks, as it might break the UI


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
                # Get user based on message type
                if isinstance(message, CallbackQuery):
                    user_id = message.from_user.id if message.from_user else None
                    logger.info(f"check_ban decorator: CallbackQuery from user {user_id}, data: {message.data if hasattr(message, 'data') else 'No data'}")
                else:
                    user_id = message.from_user.id if message.from_user else None
                    logger.info(f"check_ban decorator: Message from user {user_id}")

                if not user_id:
                    logger.warning("check_ban decorator: No user_id found, returning")
                    return

                # Skip ban check for admins
                if user_id in self.bot.config.ADMINS:
                    logger.info(f"check_ban decorator: User {user_id} is admin, skipping ban check")
                    return await func(self, client, message, *args, **kwargs)

                # Check if user is banned
                logger.info(f"check_ban decorator: Checking ban status for user {user_id}")
                user = await self.bot.user_repo.get_user(user_id)
                if user and user.status == UserStatus.BANNED:
                    logger.info(f"check_ban decorator: User {user_id} is banned, blocking access")
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

                logger.info(f"check_ban decorator: User {user_id} is not banned, proceeding to function {func.__name__}")
                return await func(self, client, message, *args, **kwargs)

            return wrapper

        return decorator


# Add to the end of the file
check_ban = BanCheck.check_ban