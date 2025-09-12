import asyncio
from typing import List, Dict, Any

from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler
from pyrogram.types import Message

from core.cache.config import CacheKeyGenerator
from core.utils.logger import get_logger

logger = get_logger(__name__)


class DeleteHandler:
    """Handler for file deletion from database"""

    def __init__(self, bot):
        self.bot = bot
        self.delete_queue = asyncio.Queue(maxsize=1000)
        self._shutdown = asyncio.Event()
        self.handlers = []  # Store handlers for cleanup
        self.background_task = None  # Track background task

        # Register handlers first
        self._register_handlers()

        # Create background task with proper tracking
        if hasattr(bot, 'handler_manager') and bot.handler_manager:
            self.background_task = bot.handler_manager.create_background_task(
                self._process_delete_queue(),
                name="delete_queue_processor"
            )
        else:
            # Fallback if handler_manager not available
            logger.warning("HandlerManager not available for DeleteHandler")
            self.background_task = asyncio.create_task(self._process_delete_queue())

    def _register_handlers(self):
        """Register delete handlers"""
        handlers_registered = 0

        # Register DELETE_CHANNEL handler if configured
        if self.bot.config.DELETE_CHANNEL:
            handler = MessageHandler(
                self.handle_delete_channel_message,
                filters.chat(self.bot.config.DELETE_CHANNEL)
            )

            # Use handler_manager if available
            if hasattr(self.bot, 'handler_manager') and self.bot.handler_manager:
                self.bot.handler_manager.add_handler(handler)
            else:
                self.bot.add_handler(handler)

            self.handlers.append(handler)
            handlers_registered += 1
            logger.info(f"Registered DELETE_CHANNEL handler for channel {self.bot.config.DELETE_CHANNEL}")

        # Register admin commands if ADMINS configured
        if self.bot.config.ADMINS:
            handler1 = MessageHandler(
                self.handle_delete_command,
                filters.command("delete") & filters.user(self.bot.config.ADMINS)
            )
            handler2 = MessageHandler(
                self.handle_deleteall_command,
                filters.command("deleteall") & filters.user(self.bot.config.ADMINS)
            )

            # Use handler_manager if available
            if hasattr(self.bot, 'handler_manager') and self.bot.handler_manager:
                self.bot.handler_manager.add_handler(handler1)
                self.bot.handler_manager.add_handler(handler2)
            else:
                self.bot.add_handler(handler1)
                self.bot.add_handler(handler2)

            self.handlers.extend([handler1, handler2])
            handlers_registered += 2
            logger.info(f"Registered delete commands for {len(self.bot.config.ADMINS)} admins")

        logger.info(f"DeleteHandler registered {handlers_registered} handlers")

    async def cleanup(self):
        """Clean up handler resources"""
        logger.info("Cleaning up DeleteHandler...")
        logger.info(f"Queue size: {self.delete_queue.qsize()}")

        # Signal shutdown
        self._shutdown.set()

        # Clear queue (always do this)
        items_cleared = 0
        while not self.delete_queue.empty():
            try:
                self.delete_queue.get_nowait()
                items_cleared += 1
            except asyncio.QueueEmpty:
                break

        logger.info(f"Cleared {items_cleared} items from delete queue")

        # If handler_manager is available, let it handle everything
        if hasattr(self.bot, 'handler_manager') and self.bot.handler_manager:
            logger.info("HandlerManager will handle handler removal and task cancellation")
            # Mark our handlers as removed in the manager
            for handler in self.handlers:
                handler_id = id(handler)
                self.bot.handler_manager.removed_handlers.add(handler_id)
            self.handlers.clear()
            logger.info("DeleteHandler cleanup complete")
            return

        # Manual cleanup only if no handler_manager
        # Cancel background task if it exists
        if hasattr(self, 'background_task') and self.background_task and not self.background_task.done():
            self.background_task.cancel()
            try:
                await self.background_task
            except asyncio.CancelledError:
                logger.info("Background task cancelled successfully")

        # Remove handlers
        for handler in self.handlers:
            try:
                self.bot.remove_handler(handler)
            except ValueError as e:
                if "x not in list" in str(e):
                    logger.debug(f"Handler already removed")
                else:
                    logger.error(f"Error removing handler: {e}")
            except Exception as e:
                logger.error(f"Error removing handler: {e}")

        self.handlers.clear()
        logger.info("DeleteHandler cleanup complete")

    async def _process_delete_queue(self):
        """Process delete queue in background"""
        logger.info("Delete queue processor started")

        while not self._shutdown.is_set():
            try:
                batch = []
                deadline = asyncio.get_event_loop().time() + 5  # 5 second batch window

                while len(batch) < 50 and not self._shutdown.is_set():
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
        file_info = self._extract_file_info(message)

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
                except:
                    pass

    def _extract_file_info(self, message: Message) -> Dict[str, Any] | None:
        """Extract file information from message"""
        media_types = [
            ('document', lambda m: m.document),
            ('video', lambda m: m.video),
            ('audio', lambda m: m.audio),
            ('photo', lambda m: m.photo),
            ('animation', lambda m: m.animation),
            ('voice', lambda m: m.voice),
            ('video_note', lambda m: m.video_note),
            ('sticker', lambda m: m.sticker)
        ]

        for media_type, getter in media_types:
            media = getter(message)
            if media:
                file_name = getattr(media, 'file_name', None)
                if not file_name:
                    # Generate a descriptive name
                    file_name = f"{media_type.title()}_{media.file_unique_id[:10]}"

                return {
                    'file_unique_id': media.file_unique_id,
                    'file_id': media.file_id,
                    'file_name': file_name,
                    'message': message
                }

        return None

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
        file_info = self._extract_file_info(message.reply_to_message)

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

        # Confirmation message
        confirm_msg = await message.reply_text(
            f"⚠️ <b>Warning!</b>\n\n"
            f"This will delete all files matching: <b>{keyword}</b>\n\n"
            f"Reply with 'YES' within 30 seconds to confirm."
        )

        # Wait for confirmation
        try:
            response = await client.wait_for_message(
                chat_id=message.chat.id,
                filters=filters.user(message.from_user.id) & filters.text,
                timeout=30
            )

            if response and response.text and response.text.upper() == "YES":
                # Delete files
                status_msg = await message.reply_text("🗑 Deleting files...")

                deleted_count = await self.bot.media_repo.delete_files_by_keyword(keyword)

                await status_msg.edit_text(
                    f"✅ Deleted {deleted_count} files matching: <b>{keyword}</b>"
                )

                # Log the bulk deletion
                if self.bot.config.LOG_CHANNEL:
                    await self.bot.send_message(
                        self.bot.config.LOG_CHANNEL,
                        f"#BulkDelete\n"
                        f"Admin: {message.from_user.mention}\n"
                        f"Keyword: {keyword}\n"
                        f"Files deleted: {deleted_count}"
                    )
            else:
                await confirm_msg.edit_text("❌ Deletion cancelled.")

        except asyncio.TimeoutError:
            await confirm_msg.edit_text("❌ Deletion cancelled (timeout).")

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
            # Find file first to get all identifiers
            file = await self.bot.media_repo.find_file(file_unique_id)
            if not file:
                logger.debug(f"File not found: {file_unique_id}")
                return False

            # Delete from database
            deleted = await self.bot.media_repo.delete(file.file_unique_id)

            # Clear cache entries if deletion successful
            if deleted:
                # Clear all related cache entries
                cache_keys_cleared = 0

                if file.file_id:
                    await self.bot.cache.delete(CacheKeyGenerator.media(file.file_id))
                    cache_keys_cleared += 1

                if file.file_ref:
                    await self.bot.cache.delete(CacheKeyGenerator.media(file.file_ref))
                    cache_keys_cleared += 1

                if file.file_unique_id:
                    await self.bot.cache.delete(CacheKeyGenerator.media(file.file_unique_id))
                    cache_keys_cleared += 1

                # Clear search-related caches
                await self.bot.cache.delete_pattern("search:*")
                await self.bot.cache.delete_pattern("search_results_*")
                await self.bot.cache.delete(CacheKeyGenerator.file_stats())

                logger.info(f"Deleted file {file_unique_id} and cleared {cache_keys_cleared} cache keys")

            return deleted

        except Exception as e:
            logger.error(f"Error deleting file {file_unique_id}: {e}", exc_info=True)
            return False