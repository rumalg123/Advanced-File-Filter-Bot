import asyncio
import base64
import time
from collections import defaultdict
from typing import List, Dict

from pyrogram import Client, filters
from pyrogram.file_id import FileId
from pyrogram.handlers import MessageHandler
from pyrogram.types import Message

from core.utils.helpers import sanitize_filename, format_file_size
from core.utils.logger import get_logger
from repositories.channel import ChannelRepository
from repositories.media import MediaFile, FileType

logger = get_logger(__name__)


class ChannelHandler:
    """Handler for automatic file indexing from channels"""

    def __init__(self, bot, channel_repo: ChannelRepository = None):
        self.bot = bot
        self.channel_repo = channel_repo or ChannelRepository(bot.db_pool, bot.cache)
        self.media_filter = filters.document | filters.video | filters.audio
        self._handlers = []
        self._update_lock = asyncio.Lock()
        self.background_tasks = []
        self.cleanup_interval = 3600  # Clean every hour

        # Add rate limiting for bulk messages
        self.message_queue = asyncio.Queue(maxsize=1000)
        self.overflow_queue = []  # Backup queue for overflow
        self.max_overflow_size = 500  # Maximum overflow items
        self.queue_full_warnings = 0
        self.last_warning_time = 0
        self.user_message_counts = defaultdict(lambda: {'count': 0, 'reset_time': time.time()})
        self.processing = False

        # Create and store background tasks ONLY ONCE
        self.background_tasks.append(
            asyncio.create_task(self._process_message_queue())
        )
        self.background_tasks.append(
            asyncio.create_task(self._process_overflow_queue())
        )
        self.background_tasks.append(
            asyncio.create_task(self._periodic_handler_update())
        )
        self.background_tasks.append(
            asyncio.create_task(self._cleanup_user_counts())
        )

        # Start with channels from config
        self._initialize_channels()

    async def _cleanup_user_counts(self):
        """Periodically clean up old user message counts"""
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval)
                current_time = time.time()

                # Clean up entries older than 1 hour
                users_to_clean = []
                for user_id, data in self.user_message_counts.items():
                    if current_time - data['reset_time'] > 3600:
                        users_to_clean.append(user_id)

                for user_id in users_to_clean:
                    del self.user_message_counts[user_id]

                if users_to_clean:
                    logger.info(f"Cleaned up message counts for {len(users_to_clean)} users")

                # Also limit overflow queue size
                if len(self.overflow_queue) > self.max_overflow_size:
                    removed = len(self.overflow_queue) - self.max_overflow_size
                    self.overflow_queue = self.overflow_queue[-self.max_overflow_size:]
                    logger.warning(f"Trimmed {removed} old items from overflow queue")

            except asyncio.CancelledError:
                logger.info("User count cleanup task cancelled")  # Add logging
                break
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")

    async def cleanup(self):
        """Clean up handler resources"""
        logger.info("Cleaning up ChannelHandler...")

        # Cancel all background tasks
        for task in self.background_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Clear queues
        while not self.message_queue.empty():
            try:
                self.message_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        self.overflow_queue.clear()
        self.user_message_counts.clear()

        # Remove handlers
        for handler in self._handlers:
            self.bot.remove_handler(handler)
        self._handlers.clear()

        logger.info("ChannelHandler cleanup complete")

    async def handle_channel_media(self, client: Client, message: Message):
        """Handle media messages in monitored channels with rate limiting"""

        special_channels = [
            self.bot.config.LOG_CHANNEL,
            self.bot.config.INDEX_REQ_CHANNEL,
            self.bot.config.REQ_CHANNEL,
            self.bot.config.DELETE_CHANNEL
        ]
        special_channels = {ch for ch in special_channels if ch}
        if message.chat.id in special_channels:
            return
        if message.from_user and message.from_user.is_bot:
            return
        try:
            # Add to queue instead of processing directly
            await self.message_queue.put({
                'message': message,
                'timestamp': time.time()
            })
        except asyncio.QueueFull:
            if len(self.overflow_queue) < self.max_overflow_size:
                self.overflow_queue.append({
                    'message': message,
                    'timestamp': time.time()
                })
                logger.debug(f"Message added to overflow queue. Overflow size: {len(self.overflow_queue)}")
            else:
                # Drop oldest message from overflow if at max capacity
                dropped = self.overflow_queue.pop(0)
                self.overflow_queue.append({
                    'message': message,
                    'timestamp': time.time()
                })

                # Rate limit warnings
                current_time = time.time()
                if current_time - self.last_warning_time > 60:  # One warning per minute
                    logger.warning(f"Message queue overflow! Dropped message from {dropped['timestamp']}")
                    self.last_warning_time = current_time
                    self.queue_full_warnings += 1

                    # Send alert to log channel if too many warnings
                    if self.queue_full_warnings % 10 == 0 and self.bot.config.LOG_CHANNEL:
                        try:
                            await self.bot.send_message(
                                self.bot.config.LOG_CHANNEL,
                                f"⚠️ **Queue Overflow Alert**\n\n"
                                f"The message queue has overflowed {self.queue_full_warnings} times.\n"
                                f"Current queue size: {self.message_queue.qsize()}/{self.message_queue.maxsize}\n"
                                f"Overflow queue size: {len(self.overflow_queue)}/{self.max_overflow_size}\n\n"
                                f"Consider reducing the indexing rate or increasing queue size."
                            )
                        except:
                            pass
        except Exception as e:
            logger.error(f"Error adding message to queue: {e}")

    async def _process_overflow_queue(self):
        """Process overflow queue when main queue has space"""
        while True:
            try:
                await asyncio.sleep(5)  # Check every 5 seconds

                if self.overflow_queue and self.message_queue.qsize() < self.message_queue.maxsize - 10:
                    # Move items from overflow to main queue
                    moved = 0
                    while self.overflow_queue and self.message_queue.qsize() < self.message_queue.maxsize - 5:
                        item = self.overflow_queue.pop(0)
                        try:
                            self.message_queue.put_nowait(item)
                            moved += 1
                        except asyncio.QueueFull:
                            # Put it back and stop
                            self.overflow_queue.insert(0, item)
                            break

                    if moved > 0:
                        logger.info(f"Moved {moved} items from overflow queue to main queue")

            except asyncio.CancelledError:
                logger.info("Overflow queue processor cancelled")
                break  # Exit the loop cleanly
            except Exception as e:
                logger.error(f"Error processing overflow queue: {e}")
                await asyncio.sleep(1)  # Short delay before retry

    # handlers/channel.py
    async def _process_message_queue(self):
        """Process messages from queue with rate limiting"""
        while True:
            try:
                batch = []
                deadline = asyncio.get_event_loop().time() + 5  # 5 second window
                queue_size = self.message_queue.qsize()
                if queue_size > 500:
                    max_batch_size = 50  # Process more when queue is full
                    wait_time = 2
                elif queue_size > 200:
                    max_batch_size = 30
                    wait_time = 3
                else:
                    max_batch_size = 20
                    wait_time = 5

                while len(batch) < max_batch_size:
                    try:
                        timeout = max(0.0, deadline - asyncio.get_event_loop().time())
                        item = await asyncio.wait_for(
                            self.message_queue.get(),
                            timeout=timeout
                        )
                        batch.append(item)
                    except asyncio.TimeoutError:
                        break

                if batch:
                    await self._process_message_batch(batch)
                    if queue_size > 100 and self.bot.config.LOG_CHANNEL:
                        try:
                            await self.bot.send_message(
                                self.bot.config.LOG_CHANNEL,
                                f"📊 **Queue Status**\n"
                                f"Main Queue: {queue_size}/1000\n"
                                f"Overflow Queue: {len(self.overflow_queue)}/{self.max_overflow_size}\n"
                                f"Batch Processed: {len(batch)} messages"
                            )
                        except:
                            pass
                else:
                    await asyncio.sleep(wait_time)

            except asyncio.CancelledError:
                logger.info("Message queue processor cancelled")
                break  # Exit the loop cleanly
            except Exception as e:
                logger.error(f"Error processing message queue: {e}")
                await asyncio.sleep(5)

    async def _process_message_batch(self, batch: List[Dict]):
        """Process a batch of messages"""
        stats = {
            'indexed': 0,
            'duplicate': 0,
            'errors': 0
        }

        for item in batch:
            message = item['message']

            try:
                # Process individual message
                result = await self._process_single_message(message)

                if result == 'indexed':
                    stats['indexed'] += 1
                elif result == 'duplicate':
                    stats['duplicate'] += 1
                else:
                    stats['errors'] += 1

                # Small delay between messages
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"Error processing message: {e}")
                stats['errors'] += 1

        # Log batch results if significant
        if stats['indexed'] > 0 and self.bot.config.LOG_CHANNEL:
            try:
                summary = (
                    f"📊 **Auto-Index Batch Summary**\n\n"
                    f"✅ Indexed: {stats['indexed']}\n"
                    f"🔄 Duplicates: {stats['duplicate']}\n"
                    f"❌ Errors: {stats['errors']}\n"
                    f"📦 Total Processed: {len(batch)}"
                )

                await self.bot.send_message(
                    self.bot.config.LOG_CHANNEL,
                    summary
                )
            except:
                pass

    async def _process_single_message(self, message: Message) -> str:
        """Process a single message (extracted from original handle_channel_media)"""
        try:
            # Extract media object
            media = None
            file_type = None

            for media_type in ("document", "video", "audio"):
                media = getattr(message, media_type, None)
                logger.info(f"Processing media type: {media_type}")
                #logger.info(f"media : {media}")
                if media is not None:
                    file_type = media_type
                    break

            if not media:
                return "no_media"

            # Create MediaFile object
            media_file = MediaFile(
                file_id=media.file_id,
                file_unique_id=media.file_unique_id,
                file_ref=self._extract_file_ref(media.file_id),
                file_name=sanitize_filename(
                    getattr(media, 'file_name', f'{file_type}_{media.file_unique_id}')
                ),
                file_size=media.file_size,
                file_type=self._get_file_type(file_type),
                mime_type=getattr(media, 'mime_type', None),
                caption=message.caption.html if message.caption else None
            )

            # Save to database
            success, status_code, existing_file = await self.bot.media_repo.save_media(media_file)

            if status_code == 1:
                logger.info(f"Successfully indexed: {media_file.file_name}")
                await self.channel_repo.update_indexed_count(message.chat.id)
                return "indexed"
            elif status_code == 0:
                logger.debug(f"Duplicate file: {media_file.file_name}")
                return "duplicate"
            else:
                logger.error(f"Failed to index: {media_file.file_name}")
                return "error"

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return "error"



    def _initialize_channels(self):
        """Initialize channels from config on startup"""
        asyncio.create_task(self._setup_initial_channels())

    async def _setup_initial_channels(self):
        """Setup initial channels from config"""
        # Add channels from environment config to database
        for channel in self.bot.config.CHANNELS:
            if channel and channel != 0:
                try:
                    await self.channel_repo.add_channel(
                        channel_id=channel if isinstance(channel, int) else 0,
                        channel_username=channel if isinstance(channel, str) else None,
                        added_by=None  # System added
                    )
                except Exception as e:
                    logger.error(f"Error adding channel {channel} from config: {e}")

        # Register handlers
        await self.update_handlers()

    async def update_handlers(self):
        """Update handlers based on current active channels"""
        async with self._update_lock:
            # Remove existing handlers
            for handler in self._handlers:
                self.bot.remove_handler(handler)
            self._handlers.clear()

            # Get active channels
            channels = await self.channel_repo.get_active_channels()

            if not channels:
                logger.info("No active channels for automatic indexing")
                return

            # Build filter for all channels
            channel_filters = []
            for channel in channels:
                channel_filters.append(filters.chat(channel.channel_id))

            # Combine all channel filters
            if channel_filters:
                combined_filter = channel_filters[0]
                for f in channel_filters[1:]:
                    combined_filter = combined_filter | f

                # Create and register handler
                handler = MessageHandler(
                    self.handle_channel_media,
                    combined_filter & self.media_filter
                )
                self.bot.add_handler(handler)
                self._handlers.append(handler)

                logger.info(f"Updated automatic indexing for {len(channels)} active channels")

    async def _periodic_handler_update(self):
        """Periodically update handlers to catch channel changes"""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                await self.update_handlers()
            except asyncio.CancelledError:
                logger.info("Periodic handler update cancelled")
                break  # Exit the loop cleanly
            except Exception as e:
                logger.error(f"Error updating channel handlers: {e}")

    def _get_file_type(self, media_type: str) -> FileType:
        """Convert media type string to FileType enum"""
        mapping = {
            'video': FileType.VIDEO,
            'audio': FileType.AUDIO,
            'document': FileType.DOCUMENT,
        }
        return mapping.get(media_type, FileType.DOCUMENT)


    @staticmethod
    def _extract_file_ref(file_id: str) -> str:
        """Extract file reference from file_id"""
        try:
            decoded = FileId.decode(file_id)
            file_ref = base64.urlsafe_b64encode(
                decoded.file_reference
            ).decode().rstrip("=")
            return file_ref
        except Exception:
            # Generate a fallback ref
            import hashlib
            return hashlib.md5(file_id.encode()).hexdigest()[:20]

    async def _send_index_notification(
            self,
            client: Client,
            message: Message,
            media_file: MediaFile,
            status: str
    ):
        """Send indexing notification to log channel"""
        try:
            notification = (
                f"<b>{status}</b>\n\n"
                f"📁 <b>File:</b> <code>{media_file.file_name}</code>\n"
                f"📊 <b>Size:</b> {format_file_size(media_file.file_size)}\n"
                f"🎬 <b>Type:</b> {media_file.file_type.value.title()}\n"
                f"📢 <b>Channel:</b> {message.chat.title or message.chat.id}\n"
                f"🔗 <b>Message:</b> {message.link if message.link else 'N/A'}"
            )

            await client.send_message(
                self.bot.config.LOG_CHANNEL,
                notification,
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"Failed to send index notification: {e}")

