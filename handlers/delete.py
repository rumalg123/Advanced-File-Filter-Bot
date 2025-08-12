import asyncio
import logging
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
        self.processing = False
        self.handlers = []  # Store handlers for cleanup

        # Register handlers first
        self._register_handlers()

        # Create background task ONLY ONCE and store it
        self.background_task = asyncio.create_task(self._process_delete_queue())

    def _register_handlers(self):
        """Register delete handlers"""
        # Store handlers for cleanup
        if self.bot.config.DELETE_CHANNEL:
            handler = MessageHandler(
                self.handle_delete_channel_message,
                filters.chat(self.bot.config.DELETE_CHANNEL)
            )
            self.bot.add_handler(handler)
            self.handlers.append(handler)

        if self.bot.config.ADMINS:
            handler1 = MessageHandler(
                self.handle_delete_command,
                filters.command("delete") & filters.user(self.bot.config.ADMINS)
            )
            self.bot.add_handler(handler1)
            self.handlers.append(handler1)

            handler2 = MessageHandler(
                self.handle_deleteall_command,
                filters.command("deleteall") & filters.user(self.bot.config.ADMINS)
            )
            self.bot.add_handler(handler2)
            self.handlers.append(handler2)

    async def cleanup(self):
        """Clean up handler resources"""
        logger.info("Cleaning up DeleteHandler...")

        # Cancel background task
        if hasattr(self, 'background_task') and not self.background_task.done():
            self.background_task.cancel()
            try:
                await self.background_task
            except asyncio.CancelledError:
                pass

        # Clear queue
        while not self.delete_queue.empty():
            try:
                self.delete_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Remove handlers
        for handler in self.handlers:
            self.bot.remove_handler(handler)
        self.handlers.clear()

        logger.info("DeleteHandler cleanup complete")

    async def handle_delete_channel_message(self, client: Client, message: Message):
        """Handle messages forwarded to delete channel"""
        # Check if message has media
        logger.info(f"Delete channel message received: {message.id}")
        if not message.media:
            logger.info("No media found in message")
            return

        # Extract file_id
        file_id = None
        file_unique_id = None
        file_name = "Unknown"
        if message.document:
            file_unique_id = message.document.file_unique_id
            file_id = message.document.file_id
            file_name = getattr(message.document, 'file_name', 'Unknown Document')
        elif message.video:
            file_unique_id = message.video.file_unique_id
            file_id = message.video.file_id
            file_name = f"Video_{message.video.file_id[:10]}"
        elif message.audio:
            file_unique_id = message.audio.file_unique_id
            file_id = message.audio.file_id
            file_name = getattr(message.audio, 'file_name', 'Unknown Audio')
        elif message.photo:
            file_unique_id = message.photo.file_unique_id
            file_id = message.photo.file_id
            file_name = f"Photo_{message.photo.file_id[:10]}"
        elif message.animation:
            file_unique_id = message.animation.file_unique_id
            file_id = message.animation.file_id
            file_name = getattr(message.animation, 'file_name', 'Unknown Animation')
        elif message.voice:
            file_unique_id = message.voice.file_unique_id
            file_id = message.voice.file_id
            file_name = f"Voice_{message.voice.file_id[:10]}"
        elif message.video_note:
            file_unique_id = message.video_note.file_unique_id
            file_id = message.video_note.file_id
            file_name = f"VideoNote_{message.video_note.file_id[:10]}"
        elif message.sticker:
            file_unique_id = message.sticker.file_unique_id
            file_id = message.sticker.file_id
            file_name = f"Sticker_{message.sticker.file_id[:10]}"

        if not file_unique_id:
            logger.warning("No supported media type found in message")
            return

        logger.info(f"Adding file to delete queue: {file_name} ({file_id})")

        # Add to delete queue
        try:
            await self.delete_queue.put({
                'file_unique_id': file_unique_id,
                'file_name': file_name,
                'message': message
            })
            logger.info(f"File added to delete queue successfully: {file_name}")
        except asyncio.QueueFull:
            logger.warning("Delete queue is full, skipping file")

    async def handle_delete_command(self, client: Client, message: Message):
        """Handle manual delete command"""
        if not message.reply_to_message:
            await message.reply_text(
                "Reply to a media message to delete it from database.\n"
                "Or use: /delete &lt;file_unique_id&gt;"
            )
            return

        # Check if replied message has media
        reply = message.reply_to_message


        if reply.media:
            # Extract file_id from media
            media = None
            for media_type in ("document", "video", "audio", "photo", "animation"):
                media = getattr(reply, media_type, None)
                if media is not None:
                    break

            if media:
                #file_id = media.file_id
                file_unique_id = media.file_unique_id
                file_name = getattr(media, 'file_name', 'Unknown')

                # Delete from database
                deleted = await self._delete_file(file_unique_id)
                logger.info(f"Deleted media {file_unique_id}: {file_name}")
                logger.info(f"Deleted {deleted} media {file_unique_id}: {file_name}")

                if deleted:
                    await message.reply_text(
                        f"✅ File deleted from database!\n"
                        f"📁 Name: {file_name}"
                    )
                else:
                    await message.reply_text("❌ File not found in database.")
            else:
                await message.reply_text("❌ No supported media found in the message.")
        else:
            # Check if command has file_id argument
            if len(message.command) > 1:
                file_unique_id = message.command[1]
                deleted = await self._delete_file(file_unique_id)

                if deleted:
                    await message.reply_text("✅ File deleted from database!")
                else:
                    await message.reply_text("❌ File not found in database.")
            else:
                await message.reply_text("❌ Reply to a media message or provide file_unique_id.")

    async def handle_deleteall_command(self, client: Client, message: Message):
        """Handle delete all files by keyword"""
        if len(message.command) < 2:
            await message.reply_text(
                "Usage: /deleteall &lt;keyword&gt;\n"
                "This will delete all files matching the keyword."
            )
            return

        keyword = " ".join(message.command[1:])

        # Confirmation message
        confirm_msg = await message.reply_text(
            f"⚠️ **Warning!**\n\n"
            f"This will delete all files matching: **{keyword}**\n\n"
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
                    f"✅ Deleted {deleted_count} files matching: **{keyword}**"
                )
            else:
                await confirm_msg.edit_text("❌ Deletion cancelled.")

        except asyncio.TimeoutError:
            await confirm_msg.edit_text("❌ Deletion cancelled (timeout).")

    async def _process_delete_queue(self):
        """Process delete queue in background"""
        logger.info("Delete queue processor started")
        while True:
            try:
                # Process in batches
                batch = []

                # Collect up to 50 items or wait 5 seconds
                deadline = asyncio.get_event_loop().time() + 5

                while len(batch) < 50:
                    try:
                        timeout = max(1, int(deadline - asyncio.get_event_loop().time()))
                        item = await asyncio.wait_for(
                            self.delete_queue.get(),
                            timeout=timeout
                        )
                        batch.append(item)
                        logger.info(f"Item added to batch: {item['file_name']}")
                    except asyncio.TimeoutError:
                        break

                if batch:
                    logger.info(f"Processing delete batch of {len(batch)} items")
                    await self._process_delete_batch(batch)


            except asyncio.CancelledError:

                logger.info("Delete queue processor cancelled")

                break

            except Exception as e:

                logger.error(f"Error processing delete queue: {e}")

                await asyncio.sleep(5)

    async def _process_delete_batch(self, batch: List[Dict[str, Any]]):
        """Process a batch of delete requests"""
        results = {
            'deleted': 0,
            'not_found': 0,
            'errors': 0
        }

        for item in batch:
            try:
                #file_id = item['file_id']
                logger.info(f"Processing item {item['file_name']}{item['file_unique_id']}")
                file_unique_id = item['file_unique_id']
                deleted = await self._delete_file(file_unique_id)

                if deleted:
                    results['deleted'] += 1
                    logger.info(f"Deleted file: {item['file_name']}")
                else:
                    results['not_found'] += 1
                    logger.warning(f"File not found in database: {item['file_name']} ({file_unique_id})")

            except Exception as e:
                logger.error(f"Error deleting file: {e}")
                results['errors'] += 1
        logger.info(f"Batch processing results: {results}")

        # Send summary to log channel if significant deletions
        if results['deleted'] > 0 and self.bot.config.LOG_CHANNEL:
            try:
                summary = (
                    f"🗑 **Deletion Summary**\n\n"
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

    async def _delete_file(self, file_id: str) -> bool:
        """Delete a single file from database"""
        try:
            # Find file first to get file_ref
            file = await self.bot.media_repo.find_file(file_id)
            if not file:
                return False

            # Delete from database
            deleted = await self.bot.media_repo.delete(file.file_unique_id)

            # Clear cache entries
            if deleted:
                cache_key = CacheKeyGenerator.media(file.file_id)
                await self.bot.cache.delete(cache_key)

                if file.file_ref:
                    ref_cache_key = CacheKeyGenerator.media(file.file_ref)
                    await self.bot.cache.delete(ref_cache_key)

                if file.file_unique_id:
                    unique_cache_key = CacheKeyGenerator.media(file.file_unique_id)
                    await self.bot.cache.delete(unique_cache_key)
                await self.bot.cache.delete_pattern("search:*")
                await self.bot.cache.delete_pattern("search_results_*")
                await self.bot.cache.delete(CacheKeyGenerator.file_stats())
                logger.info(f"Cleared all caches for deleted file: {file.file_unique_id}")


            return deleted

        except Exception as e:
            logger.error(f"Error deleting file {file_id}: {e}")
            return False