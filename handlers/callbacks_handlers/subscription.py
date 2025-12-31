from pyrogram import Client
from pyrogram.types import CallbackQuery

from core.utils.helpers import MessageProxy
from core.utils.logger import get_logger
from handlers.commands_handlers.base import BaseCommandHandler

logger = get_logger(__name__)


class SubscriptionCallbackHandler(BaseCommandHandler):
    """Handler for subscription-related callbacks"""

    async def handle_checksub_callback(self, client: Client, query: CallbackQuery):
        """Handle 'Try Again' subscription check callback"""
        current_user_id = query.from_user.id

        # Parse callback data
        parts = query.data.split('#', 2)

        # Check if it's a deeplink subscription check
        if len(parts) >= 3 and parts[1] == 'dl':
            # It's a deeplink with cached parameter
            session_key = parts[2]

            # Retrieve the cached deeplink
            cached_data = await self.bot.cache.get(session_key)
            if not cached_data:
                await query.answer("❌ Session expired. Please try again.", show_alert=True)
                return

            original_user_id = cached_data.get('user_id', current_user_id)
            param = cached_data.get('deeplink', 'start')

            # Clear the cache
            await self.bot.cache.delete(session_key)

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

        # Check if current user matches original user
        if current_user_id != original_user_id:
            await query.answer(
                "❌ This subscription check is for another user. Please use your own command.",
                show_alert=True
            )
            return

        # Check subscription again
        if self.bot.config.AUTH_CHANNEL or getattr(self.bot.config, 'AUTH_GROUPS', []):
            # Skip subscription check for admins and auth users
            skip_sub_check = (
                    current_user_id in self.bot.config.ADMINS or
                    current_user_id in getattr(self.bot.config, 'AUTH_USERS', [])
            )

            if not skip_sub_check:
                is_subscribed = await self.bot.subscription_manager.is_subscribed(
                    client, current_user_id
                )

                if not is_subscribed:
                    await query.answer(
                        "❌ You still need to join the required channel(s)!",
                        show_alert=True
                    )
                    return

        # User is now subscribed, handle the original request
        await query.answer("✅ Subscription verified!", show_alert=True)

        # Try to delete the subscription message
        try:
            await query.message.delete()
        except Exception as e:
            logger.debug(f"Could not delete subscription message: {e}")

        # Handle the original command
        if param == "start":
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
            # Just show success for search
            await query.message.reply_text(
                "✅ Subscription verified! You can now search for files."
            )

        elif param.startswith("file#"):
            # Import here to avoid circular imports
            from handlers.callbacks_handlers.file import FileCallbackHandler
            file_handler = FileCallbackHandler(self.bot)

            # Handle file callback
            await file_handler.handle_file_callback(client, query)

        elif param == "general":
            # General try again - just show success
            await query.message.reply_text(
                "✅ Subscription verified! You can now use the bot."
            )
        else:
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