import asyncio
import re

from pyrogram import Client, filters, enums
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from core.services.indexing import IndexingService, IndexRequestService
from core.utils.logger import get_logger

logger = get_logger(__name__)


class IndexingHandler:
    """Handler for file indexing commands and callbacks"""

    def __init__(
            self,
            bot,
            indexing_service: IndexingService,
            index_request_service: IndexRequestService
    ):
        self.bot = bot
        self.indexing_service = indexing_service
        self.index_request_service = index_request_service
        self._handlers = []  # Track handlers
        self._shutdown = asyncio.Event()
        self.register_handlers()

    def register_handlers(self):
        """Register indexing-related handlers"""
        # Command handlers
        handlers_to_register = []

        # Index request handler
        handler = MessageHandler(
            self.handle_index_request,
            filters.private & filters.incoming & (
                    filters.forwarded |
                    filters.regex(r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$")
            )
        )
        handlers_to_register.append(handler)

        # Admin command
        if self.bot.config.ADMINS:
            handler = MessageHandler(
                self.set_skip_command,
                filters.command("setskip") & filters.user(self.bot.config.ADMINS)
            )
            handlers_to_register.append(handler)

        # Register message handlers
        for handler in handlers_to_register:
            # Use handler_manager if available
            if hasattr(self.bot, 'handler_manager') and self.bot.handler_manager:
                self.bot.handler_manager.add_handler(handler)
            else:
                self.bot.add_handler(handler)

            self._handlers.append(handler)

        # Callback handler
        callback_handler = CallbackQueryHandler(
            self.handle_index_callback,
            filters.regex(r"^index")
        )

        # Use handler_manager if available
        if hasattr(self.bot, 'handler_manager') and self.bot.handler_manager:
            self.bot.handler_manager.add_handler(callback_handler)
        else:
            self.bot.add_handler(callback_handler)

        self._handlers.append(callback_handler)

        logger.info(f"IndexingHandler registered {len(self._handlers)} handlers")

    async def cleanup(self):
        """Clean up handler resources"""
        logger.info("Cleaning up IndexingHandler...")

        # Signal shutdown
        self._shutdown.set()

        # Cancel any ongoing indexing (always do this)
        if self.indexing_service.is_indexing:
            self.indexing_service.cancel()

        # If handler_manager is available, let it handle handler removal
        if hasattr(self.bot, 'handler_manager') and self.bot.handler_manager:
            logger.info("HandlerManager will handle handler removal")
            # Mark our handlers as removed in the manager
            for handler in self._handlers:
                handler_id = id(handler)
                self.bot.handler_manager.removed_handlers.add(handler_id)
            self._handlers.clear()
            logger.info("IndexingHandler cleanup complete")
            return

        # Manual cleanup only if no handler_manager
        for handler in self._handlers:
            try:
                self.bot.remove_handler(handler)
            except ValueError as e:
                if "x not in list" in str(e):
                    logger.debug(f"Handler already removed")
                else:
                    logger.error(f"Error removing handler: {e}")
            except Exception as e:
                logger.error(f"Error removing handler: {e}")

        self._handlers.clear()
        logger.info("IndexingHandler cleanup complete")
    async def handle_index_request(self, client: Client, message: Message):
        """Handle index request from forwarded message or link"""
        user_id = message.from_user.id if message.from_user else None
        if not user_id:
            return

        # Extract channel info
        if message.text:
            # Parse link
            regex = re.compile(
                r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)"
                r"(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$"
            )
            match = regex.match(message.text)
            if not match:
                logger.debug("Triggered in handle_index_request")
                return await message.reply("❌ Invalid link format.")

            chat_id = match.group(4)
            last_msg_id = int(match.group(5))

            if chat_id.isnumeric():
                chat_id = int("-100" + chat_id)

        elif message.forward_from_chat:
            # Forwarded message
            if message.forward_from_chat.type != enums.ChatType.CHANNEL:
                return await message.reply("❌ Please forward from a channel, not a group")

            last_msg_id = message.forward_from_message_id
            chat_id = message.forward_from_chat.username or message.forward_from_chat.id
        else:
            return

        # Validate channel
        try:
            chat_id_int, error = await self.indexing_service.validate_channel(client, chat_id)
            if error:
                return await message.reply(f"❌ {error}")

            # Check if last message exists
            try:
                last_msg = await client.get_messages(chat_id_int, last_msg_id)
                if last_msg.empty:
                    return await message.reply("❌ The specified message doesn't exist")
            except Exception as e:
                error_msg = str(e).lower()
                if "channel_private" in error_msg or "chat not found" in error_msg:
                    return await message.reply(
                        "❌ <b>Bot Access Required</b>\n"
                        "I cannot access this channel. Please:\n"
                        "1. Add me to the channel as an admin\n"
                        "2. Make sure the channel is public OR\n"
                        "3. Ensure I have proper permissions\n"
                        "Then try forwarding the message again."
                    )
                else:
                    return await message.reply(
                        "❌ Error accessing the channel. Make sure I'm an admin in the channel."
                    )

            # Admin can index directly
            if user_id in self.bot.config.ADMINS:
                buttons = [
                    [
                        InlineKeyboardButton(
                            "✅ Yes",
                            callback_data=f"index#accept#{chat_id_int}#{last_msg_id}#{user_id}"
                        )
                    ],
                    [
                        InlineKeyboardButton("❌ Cancel", callback_data="close_data")
                    ]
                ]

                await message.reply(
                    f"Do you want to index this channel/group?\n"
                    f"Chat ID/Username: <code>{chat_id}</code>\n"
                    f"Last Message ID: <code>{last_msg_id}</code>",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            else:
                # Regular user - create request
                success = await self.index_request_service.create_index_request(
                    client,
                    user_id,
                    chat_id_int,
                    last_msg_id,
                    message.id
                )

                if success:
                    return await message.reply(
                        "✅ Thank you for the contribution!\n"
                        "Your request has been sent to moderators for verification."
                    )
                else:
                    return await message.reply("❌ Failed to create index request")
        except Exception as e:
            error_msg = str(e).lower()
            if "channel_private" in error_msg:
                return await message.reply(
                    "❌ <b>Bot Access Required</b>\n\n"
                    "I cannot access this channel. Please:\n"
                    "1. Add me to the channel as an admin\n"
                    "2. Make sure the channel is public OR\n"
                    "3. Ensure I have proper permissions\n\n"
                    "Then try forwarding the message again."
                )
            else:
                logger.error(f"Error in handle_index_request: {e}")
                return await message.reply("❌ An error occurred. Please try again.")

    async def handle_index_callback(self, client: Client, query: CallbackQuery):
        """Handle index-related callbacks"""
        data = query.data.split("#")

        if len(data) < 2:
            return await query.answer("Invalid callback data")

        action = data[1]

        if action == "cancel":
            # Cancel ongoing indexing
            self.indexing_service.cancel()
            return await query.answer("Cancelling indexing...")

        elif action in ["accept", "reject"]:
            # Handle admin decision on index request
            if len(data) < 5:
                return await query.answer("Invalid callback data")

            _, action, chat_id, param, from_user = data

            if action == "reject":
                # Reject request
                await query.message.delete()

                try:
                    await client.send_message(
                        int(from_user),
                        f"❌ Your request to index <code>{chat_id}</code> has been declined by moderators.",
                        reply_to_message_id=int(param)
                    )
                except Exception:
                    pass

                return await query.answer("Request rejected")

            # Accept request - start indexing
            try:
                chat_id = int(chat_id)
            except ValueError:
                pass

            last_msg_id = int(param)

            # Start indexing
            await self._start_indexing(client, query, chat_id, last_msg_id, from_user)

    async def _start_indexing(
            self,
            client: Client,
            query: CallbackQuery,
            chat_id: int,
            last_msg_id: int,
            requested_by: str
    ):
        """Start the indexing process"""
        # Check if already indexing
        if self.indexing_service.is_indexing:
            return await query.answer("Another indexing is in progress", show_alert=True)

        await query.answer("Starting indexing process...", show_alert=True)

        # Notify requester if not admin
        if int(requested_by) not in self.bot.config.ADMINS:
            try:
                await client.send_message(
                    int(requested_by),
                    f"✅ Your request to index <code>{chat_id}</code> has been accepted!\n"
                    "Indexing will begin shortly.",
                    reply_to_message_id=last_msg_id
                )
            except Exception:
                pass

        # Update message with progress
        await query.message.edit_text(
            "🔄 Starting Indexing...",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data="index#cancel")]
            ])
        )

        # Progress callback
        async def update_progress(stats):
            try:
                text = (
                    f"🔄 <b>Indexing Progress</b>\n"
                    f"Total Messages: <code>{stats['total_messages']}</code>\n"
                    f"Files Saved: <code>{stats['total_files']}</code>\n"
                    f"Duplicates: <code>{stats['duplicate']}</code>\n"
                    f"Deleted Messages: <code>{stats['deleted']}</code>\n"
                    f"Non-Media: <code>{stats['no_media'] + stats['unsupported']}</code>\n"
                    f"Errors: <code>{stats['errors']}</code>"
                )

                await query.message.edit_text(
                    text,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("❌ Cancel", callback_data="index#cancel")]
                    ])
                )
            except Exception:
                pass

        # Start indexing
        try:
            stats = await self.indexing_service.index_files(
                self.bot,
                chat_id,
                last_msg_id,
                progress_callback=update_progress
            )

            # Final message
            if self.indexing_service.cancel_indexing:
                final_text = (
                    f"🛑 <b>Indexing Cancelled!</b>\n"
                    f"Files Saved: <code>{stats['total_files']}</code>\n"
                    f"Duplicates Skipped: <code>{stats['duplicate']}</code>\n"
                    f"Deleted Messages: <code>{stats['deleted']}</code>\n"
                    f"Non-Media: <code>{stats['no_media'] + stats['unsupported']}</code>\n"
                    f"Errors: <code>{stats['errors']}</code>"
                )
            else:
                final_text = (
                    f"✅ <b>Indexing Completed!</b>\n"
                    f"Successfully saved <code>{stats['total_files']}</code> files\n"
                    f"Duplicates Skipped: <code>{stats['duplicate']}</code>\n"
                    f"Deleted Messages: <code>{stats['deleted']}</code>\n"
                    f"Non-Media: <code>{stats['no_media'] + stats['unsupported']}</code>\n"
                    f"Errors: <code>{stats['errors']}</code>"
                )

            await query.message.edit_text(final_text)

        except Exception as e:
            logger.error(f"Indexing error: {e}")
            await query.message.edit_text(f"❌ Error during indexing: {str(e)}")

    async def set_skip_command(self, client: Client, message: Message):
        """Set skip number for indexing"""
        if len(message.command) < 2:
            return await message.reply("Usage: /setskip <number>")

        try:
            skip = int(message.command[1])
            if skip < 0:
                return await message.reply("❌ Skip number must be positive")

            await self.indexing_service.set_skip_number(skip)
            await message.reply(f"✅ Skip number set to {skip}")

        except ValueError:
            await message.reply("❌ Invalid number format")