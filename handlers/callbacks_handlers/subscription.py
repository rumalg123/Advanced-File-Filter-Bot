from pyrogram import Client
from pyrogram.types import CallbackQuery

from core.utils.error_formatter import ErrorMessageFormatter
from core.utils.helpers import MessageProxy
from core.utils.logger import get_logger
from core.utils.validators import extract_user_id, skip_subscription_check
from handlers.commands_handlers.base import BaseCommandHandler

logger = get_logger(__name__)


class _CallbackQueryProxy:
    """Minimal callback query proxy that replays the original callback data."""

    def __init__(self, query: CallbackQuery, data: str):
        self._query = query
        self.id = getattr(query, "id", None)
        self.from_user = query.from_user
        self.message = query.message
        self.chat_instance = getattr(query, "chat_instance", None)
        self.data = data

    async def answer(self, *args, **kwargs):
        return await self._query.answer(*args, **kwargs)


class SubscriptionCallbackHandler(BaseCommandHandler):
    """Handler for subscription-related callbacks"""

    async def handle_checksub_callback(self, client: Client, query: CallbackQuery):
        """Handle 'Try Again' subscription check callback"""
        current_user_id = extract_user_id(query)

        # Parse callback data
        parts = query.data.split('#', 2)

        # Check if it's a deeplink subscription check
        if len(parts) >= 3 and parts[1] == 'dl':
            # It's a deeplink with cached parameter
            session_key = parts[2]

            # Retrieve the cached deeplink
            cached_data = await self.bot.cache.get(session_key)
            if not cached_data:
                await query.answer(ErrorMessageFormatter.format_error("Session expired. Please try again.", plain_text=True), show_alert=True)
                return

            original_user_id = cached_data.get('user_id', current_user_id)
            param = cached_data.get('deeplink', 'start')

            # Clear the cache
            await self.bot.cache_invalidator.invalidate_subscription_session(session_key)

        elif len(parts) == 2:
            # Old format: checksub#param
            _, param = parts
            original_user_id = current_user_id
        elif len(parts) >= 3:
            # New format: checksub#user_id#param (for non-deeplink cases)
            _, original_user_id_str, param = parts[0], parts[1], '#'.join(parts[2:]) if len(parts) > 2 else parts[2]
            try:
                original_user_id = int(original_user_id_str)
            except ValueError:
                # If parsing fails, treat as old format
                param = '#'.join(parts[1:])
                original_user_id = current_user_id
        else:
            param = "start"
            original_user_id = current_user_id

        should_delete_message = True

        # Check if current user matches original user
        if current_user_id != original_user_id:
            await query.answer(
                ErrorMessageFormatter.format_error("This subscription check is for another user. Please use your own command."),
                show_alert=True
            )
            return

        # Check subscription again
        if self.bot.config.AUTH_CHANNEL or getattr(self.bot.config, 'AUTH_GROUPS', []):
            # Skip subscription check for admins and auth users using validator
            skip_sub = skip_subscription_check(
                current_user_id,
                self.bot.config.ADMINS,
                getattr(self.bot.config, 'AUTH_USERS', [])
            )

            if not skip_sub:
                is_subscribed = await self.bot.subscription_manager.is_subscribed(
                    client, current_user_id
                )

                if not is_subscribed:
                    await query.answer(
                        ErrorMessageFormatter.format_access_denied("You still need to join the required channel(s)!", plain_text=True),
                        show_alert=True
                    )
                    return

        # Handle the original command
        if param == "start":
            await query.answer(ErrorMessageFormatter.format_success("Subscription verified!", plain_text=True), show_alert=True)
            # Import here to avoid circular imports
            from handlers.commands_handlers.user import UserCommandHandler
            user_handler = UserCommandHandler(self.bot)

            # Create a message proxy from the callback query
            fake_message = MessageProxy.from_callback_query(
                query,
                text='/start',
                command=['/start']
            )
            await user_handler.start_command(client, fake_message)

        elif param == "search":
            await query.answer(ErrorMessageFormatter.format_success("Subscription verified!", plain_text=True), show_alert=True)
            # Just show success for search
            await query.message.reply_text(
                ErrorMessageFormatter.format_success("Subscription verified! You can now search for files.")
            )

        elif param.startswith("file#"):
            # Import here to avoid circular imports
            from handlers.callbacks_handlers.file import FileCallbackHandler
            file_handler = FileCallbackHandler(self.bot)

            callback_query = _CallbackQueryProxy(query, param)
            await file_handler.handle_file_callback(client, callback_query)

        elif param.startswith("sendall#"):
            # Import here to avoid circular imports
            from handlers.callbacks_handlers.file import FileCallbackHandler
            file_handler = FileCallbackHandler(self.bot)

            callback_query = _CallbackQueryProxy(query, param)
            await file_handler.handle_sendall_callback(client, callback_query)

        elif param.startswith("cb#"):
            original_callback = param[3:]
            callback_query = _CallbackQueryProxy(query, original_callback)
            should_delete_message = False

            from handlers.callbacks_handlers.user import UserCallbackHandler
            user_handler = UserCallbackHandler(self.bot)

            callback_routes = {
                "help": user_handler.handle_help_callback,
                "about": user_handler.handle_about_callback,
                "stats": user_handler.handle_stats_callback,
                "plans": user_handler.handle_plans_callback,
                "start_menu": user_handler.handle_start_menu_callback,
                "refresh_recommendations": user_handler.handle_refresh_recommendations_callback,
                "close_recommendations": user_handler.handle_close_recommendations_callback,
            }

            handler = callback_routes.get(original_callback)
            if not handler:
                await callback_query.answer(
                    ErrorMessageFormatter.format_invalid("callback action", plain_text=True),
                    show_alert=True
                )
                return

            await handler(client, callback_query)

        elif param == "general":
            await query.answer(ErrorMessageFormatter.format_success("Subscription verified!", plain_text=True), show_alert=True)
            # General try again - just show success
            await query.message.reply_text(
                ErrorMessageFormatter.format_success("Subscription verified! You can now use the bot.")
            )
        else:
            await query.answer(ErrorMessageFormatter.format_success("Subscription verified!", plain_text=True), show_alert=True)
            # Handle deep link parameter
            from handlers.deeplink import DeepLinkHandler
            deeplink_handler = DeepLinkHandler(self.bot)

            # Create a message proxy from the callback query
            fake_message = MessageProxy.from_callback_query(
                query,
                text=f'/start {param}',
                command=['/start', param]
            )

            # Call the internal method directly (without decorator check)
            await deeplink_handler.handle_deep_link_internal(client, fake_message, param)

        if should_delete_message:
            try:
                await query.message.delete()
            except Exception as e:
                logger.debug(f"Could not delete subscription message: {e}")
