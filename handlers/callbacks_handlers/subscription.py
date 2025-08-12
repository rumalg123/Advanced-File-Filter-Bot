import logging
from pyrogram import Client
from pyrogram.types import CallbackQuery

from handlers.commands_handlers.base import BaseCommandHandler

from core.utils.logger import get_logger
logger = get_logger(__name__)


class SubscriptionCallbackHandler(BaseCommandHandler):
    """Handler for subscription-related callbacks"""

    async def handle_checksub_callback(self, client: Client, query: CallbackQuery):
        """Handle 'Try Again' subscription check callback"""
        user_id = query.from_user.id

        # Extract original parameter from callback data
        parts = query.data.split('#', 1)
        param = parts[1] if len(parts) > 1 else "start"

        # Check subscription again
        if self.bot.config.AUTH_CHANNEL or getattr(self.bot.config, 'AUTH_GROUPS', []):
            # Skip subscription check for admins and auth users
            skip_sub_check = (
                    user_id in self.bot.config.ADMINS or
                    user_id in getattr(self.bot.config, 'AUTH_USERS', [])
            )

            if not skip_sub_check:
                is_subscribed = await self.bot.subscription_manager.is_subscribed(
                    client, user_id
                )

                if not is_subscribed:
                    await query.answer(
                        "❌ You still need to join the required channel(s)!",
                        show_alert=True
                    )
                    return

        # User is now subscribed, handle the original request
        await query.answer("✅ Subscription verified!", show_alert=True)

        # Try to delete the subscription message (might fail if bot doesn't have permission)
        try:
            await query.message.delete()
        except Exception as e:
            logger.debug(f"Could not delete subscription message: {e}")
            # Continue execution even if deletion fails

        # Handle the original command
        if param == "start":
            # Import here to avoid circular imports
            from handlers.commands_handlers.user import UserCommandHandler
            user_handler = UserCommandHandler(self.bot)

            # Create a more complete fake message object
            fake_message = type('obj', (object,), {
                'from_user': query.from_user,
                'chat': query.message.chat if query.message else None,
                'command': ['/start'],
                'reply_text': query.message.reply_text,
                'text': '/start',
                'message_id': query.message.id if query.message else None,
                'date': query.message.date if query.message else None,
                'reply_to_message': None,
                'forward_from': None,
                'forward_from_chat': None,
                'edit_date': None,
                'media_group_id': None,
                'author_signature': None,
                'via_bot': None,
                'outgoing': False,
                'matches': [],
                'caption': None,
                'entities': [],
                'caption_entities': [],
                'audio': None,
                'document': None,
                'photo': None,
                'sticker': None,
                'animation': None,
                'game': None,
                'video': None,
                'voice': None,
                'video_note': None,
                'contact': None,
                'location': None,
                'venue': None,
                'web_page': None,
                'poll': None,
                'dice': None
            })()
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

            # Create a more complete fake message object for deeplink
            fake_message = type('obj', (object,), {
                'from_user': query.from_user,
                'chat': query.message.chat if query.message else None,
                'command': ['/start', param],
                'reply_text': query.message.reply_text,
                'text': f'/start {param}',
                'message_id': query.message.id if query.message else None,
                'date': query.message.date if query.message else None,
                'reply_to_message': None,
                'forward_from': None,
                'forward_from_chat': None,
                'edit_date': None,
                'media_group_id': None,
                'author_signature': None,
                'via_bot': None,
                'outgoing': False,
                'matches': [],
                'caption': None,
                'entities': [],
                'caption_entities': [],
                'audio': None,
                'document': None,
                'photo': None,
                'sticker': None,
                'animation': None,
                'game': None,
                'video': None,
                'voice': None,
                'video_note': None,
                'contact': None,
                'location': None,
                'venue': None,
                'web_page': None,
                'poll': None,
                'dice': None
            })()
            await deeplink_handler.handle_deep_link(client, fake_message, param)