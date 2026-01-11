import asyncio
from typing import List, Dict, Any, Optional

from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from core.constants import ProcessingConstants
from core.utils.helpers import extract_file_info
from core.utils.logger import get_logger
from core.utils.validators import is_original_requester, validate_callback_data
from handlers.base import BaseHandler

logger = get_logger(__name__)


class DeleteHandler(BaseHandler):
    """Handler for file deletion from database"""

    def __init__(self, bot):
        super().__init__(bot)
        self.delete_queue = asyncio.Queue(maxsize=1000)
        self._register_queue(self.delete_queue)

        # Register handlers
        self.register_handlers()

        # Create background task for queue processing
        task = self._track_task(self._process_delete_queue())
        if task:
            logger.info("Delete queue processor task created")

    def register_handlers(self) -> None:
        """Register delete handlers"""
        handlers_registered = 0

        # Register DELETE_CHANNEL handler if configured
        if self.bot.config.DELETE_CHANNEL:
            handler = MessageHandler(
                self.handle_delete_channel_message,
                filters.chat(self.bot.config.DELETE_CHANNEL)
            )
            self._register_handler(handler)
            handlers_registered += 1
            logger.info(f"Registered DELETE_CHANNEL handler for channel {self.bot.config.DELETE_CHANNEL}")

        # Register admin commands if ADMINS configured
        if self.bot.config.ADMINS:
            self._register_message_handlers([
                (self.handle_delete_command, filters.command("delete") & filters.user(self.bot.config.ADMINS)),
                (self.handle_deleteall_command, filters.command("deleteall") & filters.user(self.bot.config.ADMINS))
            ])
            handlers_registered += 2

            # Callback handler for deleteall confirmation
            self._register_callback_handlers([
                (self.handle_deleteall_callback, filters.regex(r"^deleteall_(confirm|cancel)#"))
            ])
            handlers_registered += 1
            logger.info(f"Registered delete commands for {len(self.bot.config.ADMINS)} admins")

        logger.info(f"DeleteHandler registered {handlers_registered} handlers")

    async def _process_delete_queue(self):
        """Process delete queue in background"""
        logger.info("Delete queue processor started")

        while not self._shutdown.is_set():
            try:
                batch = []
                deadline = asyncio.get_event_loop().time() + ProcessingConstants.DELETE_BATCH_TIMEOUT

                while len(batch) < ProcessingConstants.DELETE_BATCH_SIZE and not self._shutdown.is_set():
                    try:
                        remaining = deadline - asyncio.get_event_loop().time()
                        if remaining <= 0:
                            break  # Deadline passed, process what we have

                        timeout = min(remaining, 5.0)  # Cap at 5 seconds

                        item = await asyncio.wait_for(
                            self.delete_queue.get(),
                            timeout=timeout
                        )
                        batch.append(item)

                    except asyncio.TimeoutError:
                        break  # Timeout reached, process batch

                if batch and not self._shutdown.is_set():
                    await self._process_delete_batch(batch)
                elif not batch:
                    # No items to process, wait a bit before checking again
                    try:
                        await asyncio.wait_for(self._shutdown.wait(), timeout=1.0)
                        break  # Shutdown requested
                    except asyncio.TimeoutError:
                        pass  # Continue checking for items

            except asyncio.CancelledError:
                logger.info("Delete queue processor cancelled")
                break
            except Exception as e:
                logger.error(f"Error processing delete queue: {e}", exc_info=True)
                # Wait before retrying to avoid tight error loop
                try:
                    await asyncio.wait_for(self._shutdown.wait(), timeout=5.0)
                    break  # Shutdown requested
                except asyncio.TimeoutError:
                    pass  # Continue after wait

        logger.info("Delete queue processor exited")

    async def handle_delete_channel_message(self, client: Client, message: Message):
        """Handle messages forwarded to delete channel"""
        logger.debug(f"Delete channel message received: {message.id}")

        if not message.media:
            logger.debug("No media found in message")
            return

        # Extract file information
        file_info = extract_file_info(message)

        if not file_info:
            logger.warning("No supported media type found in message")
            return

        logger.info(f"Adding file to delete queue: {file_info['file_name']} ({file_info['file_unique_id']})")

        # Add to delete queue
        try:
            # Try to add without blocking
            self.delete_queue.put_nowait(file_info)
            logger.info(f"File added to delete queue successfully: {file_info['file_name']}")
        except asyncio.QueueFull:
            logger.warning(f"Delete queue is full, dropping file: {file_info['file_name']}")
            # Optionally, send alert to log channel
            if self.bot.config.LOG_CHANNEL:
                try:
                    await self.bot.send_message(
                        self.bot.config.LOG_CHANNEL,
                        "⚠️ Delete queue is full! Consider increasing queue size or processing rate."
                    )
                except Exception as e:
                    logger.warning(f"Failed to send queue full alert: {e}")

    async def handle_delete_command(self, client: Client, message: Message):
        """Handle manual delete command"""
        if len(message.command) > 1:
            # Delete by file_unique_id
            file_unique_id = message.command[1]
            deleted = await self._delete_file(file_unique_id)

            if deleted:
                await message.reply_text("✅ File deleted from database!")
            else:
                await message.reply_text("❌ File not found in database.")
            return

        if not message.reply_to_message:
            await message.reply_text(
                "Reply to a media message to delete it from database.\n"
                "Or use: <code>/delete &lt;file_unique_id&gt;</code>"
            )
            return

        # Extract file info from replied message
        file_info = extract_file_info(message.reply_to_message)

        if not file_info:
            await message.reply_text("❌ No supported media found in the message.")
            return

        # Delete from database
        deleted = await self._delete_file(file_info['file_unique_id'])

        if deleted:
            await message.reply_text(
                f"✅ File deleted from database!\n"
                f"📁 Name: {file_info['file_name']}"
            )
        else:
            await message.reply_text("❌ File not found in database.")

    async def handle_deleteall_command(self, client: Client, message: Message):
        """Handle delete all files by keyword"""
        if len(message.command) < 2:
            await message.reply_text(
                "<b>Usage:</b> <code>/deleteall &lt;keyword&gt;</code>\n\n"
                "This will delete all files matching the keyword.\n"
                "Example: <code>/deleteall movie</code>"
            )
            return

        keyword = " ".join(message.command[1:])
        user_id = message.from_user.id

        # Store pending deletion in cache for callback handler
        cache_key = f"deleteall_pending:{user_id}"
        await self.bot.cache.set(cache_key, keyword, expire=60)  # 60 second TTL

        # Confirmation message with buttons
        await message.reply_text(
            f"⚠️ <b>Warning!</b>\n\n"
            f"This will delete all files matching: <b>{keyword}</b>\n\n"
            f"Click 'Confirm' to proceed or 'Cancel' to abort.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Confirm", callback_data=f"deleteall_confirm#{user_id}"),
                    InlineKeyboardButton("❌ Cancel", callback_data=f"deleteall_cancel#{user_id}")
                ]
            ])
        )

    async def handle_deleteall_callback(self, client: Client, callback_query):
        """Handle deleteall confirmation callback"""
        # Validate callback data using validator
        is_valid, parts = validate_callback_data(callback_query, expected_parts=2)
        if not is_valid:
            await callback_query.answer("Invalid callback data", show_alert=True)
            return

        action = parts[0]
        original_user_id = int(parts[1])
        callback_user_id = callback_query.from_user.id

        # Only the original requester can confirm/cancel using validator
        if not is_original_requester(callback_user_id, original_user_id):
            await callback_query.answer("❌ You cannot interact with this!", show_alert=True)
            return

        cache_key = f"deleteall_pending:{original_user_id}"
        keyword = await self.bot.cache.get(cache_key)

        if action == "deleteall_cancel":
            await self.bot.cache.delete(cache_key)
            await callback_query.message.edit_text("❌ Deletion cancelled.")
            await callback_query.answer()
            return

        if action == "deleteall_confirm":
            if not keyword:
                await callback_query.message.edit_text("❌ Deletion request expired. Please try again.")
                await callback_query.answer()
                return

            # Delete from cache
            await self.bot.cache.delete(cache_key)

            # Update message to show progress
            await callback_query.message.edit_text("🗑 Deleting files...")

            # Delete files
            deleted_count = await self.bot.media_repo.delete_files_by_keyword(keyword)

            await callback_query.message.edit_text(
                f"✅ Deleted {deleted_count} files matching: <b>{keyword}</b>"
            )

            # Log the bulk deletion
            if self.bot.config.LOG_CHANNEL:
                try:
                    await self.bot.send_message(
                        self.bot.config.LOG_CHANNEL,
                        f"#BulkDelete\n"
                        f"Admin: {callback_query.from_user.mention}\n"
                        f"Keyword: {keyword}\n"
                        f"Files deleted: {deleted_count}"
                    )
                except Exception as e:
                    logger.error(f"Failed to log bulk deletion: {e}")

            await callback_query.answer("Deletion complete!")

    async def _process_delete_batch(self, batch: List[Dict[str, Any]]):
        """Process a batch of delete requests"""
        results = {
            'deleted': 0,
            'not_found': 0,
            'errors': 0
        }

        for item in batch:
            if self._shutdown.is_set():
                logger.info("Shutdown requested, stopping batch processing")
                break

            try:
                file_unique_id = item['file_unique_id']
                file_name = item.get('file_name', 'Unknown')

                logger.debug(f"Processing deletion for: {file_name} ({file_unique_id})")

                deleted = await self._delete_file(file_unique_id)

                if deleted:
                    results['deleted'] += 1
                    logger.info(f"Deleted file: {file_name}")
                else:
                    results['not_found'] += 1
                    logger.debug(f"File not found: {file_name} ({file_unique_id})")

                # Small delay to avoid overwhelming the database
                await asyncio.sleep(0.1)

            except Exception as e:
                logger.error(f"Error deleting file {item.get('file_name', 'Unknown')}: {e}")
                results['errors'] += 1

        logger.info(f"Batch processing complete: {results}")

        # Send summary to log channel if significant deletions
        if results['deleted'] > 0 and self.bot.config.LOG_CHANNEL:
            try:
                summary = (
                    f"🗑 <b>Deletion Summary</b>\n\n"
                    f"✅ Deleted: {results['deleted']}\n"
                    f"❌ Not Found: {results['not_found']}\n"
                    f"⚠️ Errors: {results['errors']}\n"
                    f"📊 Total Processed: {len(batch)}"
                )

                await self.bot.send_message(
                    self.bot.config.LOG_CHANNEL,
                    summary
                )
            except Exception as e:
                logger.error(f"Failed to send deletion summary: {e}")

    async def _delete_file(self, file_unique_id: str) -> bool:
        """Delete a single file from database"""
        try:
            # Repository handles finding, deleting, and cache invalidation
            deleted = await self.bot.media_repo.delete(file_unique_id)
            if deleted:
                logger.info(f"Deleted file: {file_unique_id}")
            else:
                logger.debug(f"File not found: {file_unique_id}")
            return deleted
        except Exception as e:
            logger.error(f"Error deleting file {file_unique_id}: {e}", exc_info=True)
            return False
