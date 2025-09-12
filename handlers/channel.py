import asyncio
import base64
import time
from collections import defaultdict
from typing import List, Dict

from pyrogram import Client, filters
from pyrogram.file_id import FileId
from pyrogram.handlers import MessageHandler
from pyrogram.types import Message

from core.cache.config import CacheTTLConfig
from core.utils.helpers import sanitize_filename, format_file_size
from core.utils.logger import get_logger
from core.utils.file_reference import FileReferenceExtractor
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
        self._shutdown = asyncio.Event()
        self._update_lock = asyncio.Lock()
        # Add rate limiting for bulk messages
        self.message_queue = asyncio.Queue(maxsize=1000)
        self.overflow_queue = []  # Backup queue for overflow
        self.max_overflow_size = 500  # Maximum overflow items
        self.queue_full_warnings = 0
        self.last_warning_time = 0
        self.user_message_counts = defaultdict(lambda: {'count': 0, 'reset_time': time.time()})
        self.processing = False

        self.background_tasks = []

        self.init_task = None

        # Use the handler manager if available
        if not hasattr(bot, 'handler_manager') or not bot.handler_manager:
            logger.error("HandlerManager not available! Channel handler may not work properly.")
            raise RuntimeError("HandlerManager is required for ChannelHandler")

            # Create all background tasks through handler_manager
        self._create_background_tasks()

        # Initialize channels after manager is ready
        bot.handler_manager.create_background_task(
            self._setup_initial_channels(),
            name="channel_initial_setup"
        )

    def _create_background_tasks(self):
        """Create all background tasks through handler_manager"""
        tasks_config = [
            (self._process_message_queue(), "channel_message_queue"),
            (self._process_overflow_queue(), "channel_overflow_queue"),
            (self._periodic_handler_update(), "channel_handler_update"),
            (self._cleanup_user_counts(), "channel_user_cleanup")
        ]

        for coro, name in tasks_config:
            task = self.bot.handler_manager.create_background_task(coro, name=name)
            if task:
                self.background_tasks.append(task)
            else:
                logger.warning(f"Failed to create task: {name}")

    async def cleanup(self):
        """Clean up handler resources"""
        logger.info("Cleaning up ChannelHandler...")

        # Signal shutdown
        self._shutdown.set()

        # Clear queues first (always do this)
        queue_items_cleared = 0
        while not self.message_queue.empty():
            try:
                self.message_queue.get_nowait()
                queue_items_cleared += 1
            except asyncio.QueueEmpty:
                break

        overflow_items = len(self.overflow_queue)
        self.overflow_queue.clear()
        self.user_message_counts.clear()

        logger.info(f"Cleared {queue_items_cleared} items from main queue, {overflow_items} from overflow")

        # If handler_manager is available, let it handle handler removal
        if hasattr(self.bot, 'handler_manager') and self.bot.handler_manager:
            logger.info("HandlerManager will handle handler removal")
            # Mark our handlers as removed in the manager
            for handler in self._handlers:
                handler_id = id(handler)
                self.bot.handler_manager.removed_handlers.add(handler_id)
            self._handlers.clear()
            logger.info("ChannelHandler cleanup complete")
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
        logger.info("ChannelHandler cleanup complete")

    async def _cleanup_user_counts(self):
        """Periodically clean up old user message counts"""
        cleanup_interval = 3600  # 1 hour

        while not self._shutdown.is_set():
            try:
                # Wait for interval or shutdown
                await asyncio.wait_for(
                    self._shutdown.wait(),
                    timeout=cleanup_interval
                )
                break  # Shutdown requested
            except asyncio.TimeoutError:
                # Timeout occurred, do cleanup
                current_time = time.time()

                # Clean up entries older than 1 hour
                users_to_clean = [
                    user_id for user_id, data in self.user_message_counts.items()
                    if current_time - data['reset_time'] > 3600
                ]

                for user_id in users_to_clean:
                    del self.user_message_counts[user_id]

                if users_to_clean:
                    logger.info(f"Cleaned up message counts for {len(users_to_clean)} users")

                # Limit overflow queue size
                if len(self.overflow_queue) > self.max_overflow_size:
                    removed = len(self.overflow_queue) - self.max_overflow_size
                    self.overflow_queue = self.overflow_queue[-self.max_overflow_size:]
                    logger.warning(f"Trimmed {removed} old items from overflow queue")

            except asyncio.CancelledError:
                logger.info("User count cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")

        logger.info("User count cleanup task exited")

    async def _process_message_queue(self):
        """Process messages from queue with rate limiting"""
        while not self._shutdown.is_set():
            try:
                batch = []
                deadline = asyncio.get_event_loop().time() + 5

                # Dynamic batch sizing
                queue_size = self.message_queue.qsize()
                max_batch_size = 50 if queue_size > 500 else (30 if queue_size > 200 else 20)
                wait_time = 2 if queue_size > 500 else (3 if queue_size > 200 else 5)

                while len(batch) < max_batch_size and not self._shutdown.is_set():
                    try:
                        timeout = max(0.0, deadline - asyncio.get_event_loop().time())
                        if timeout <= 0:
                            break
                        item = await asyncio.wait_for(
                            self.message_queue.get(),
                            timeout=timeout
                        )
                        batch.append(item)
                    except asyncio.TimeoutError:
                        break

                if batch and not self._shutdown.is_set():
                    await self._process_message_batch(batch)
                elif not batch:
                    # No messages, wait a bit
                    try:
                        await asyncio.wait_for(self._shutdown.wait(), timeout=wait_time)
                        break  # Shutdown requested
                    except asyncio.TimeoutError:
                        pass  # Continue processing

            except asyncio.CancelledError:
                logger.info("Message queue processor cancelled")
                break
            except Exception as e:
                logger.error(f"Error processing message queue: {e}")
                await asyncio.sleep(CacheTTLConfig.CHANNEL_INDEX_DELAY)

        logger.info("Message queue processor exited")

    async def _process_overflow_queue(self):
        """Process overflow queue when main queue has space"""
        while not self._shutdown.is_set():
            try:
                # Wait for 5 seconds or shutdown
                await asyncio.wait_for(self._shutdown.wait(), timeout=5)
                break  # Shutdown requested
            except asyncio.TimeoutError:
                # Continue processing
                if self.overflow_queue and self.message_queue.qsize() < self.message_queue.maxsize - 10:
                    moved = 0
                    while self.overflow_queue and self.message_queue.qsize() < self.message_queue.maxsize - 5:
                        item = self.overflow_queue.pop(0)
                        try:
                            self.message_queue.put_nowait(item)
                            moved += 1
                        except asyncio.QueueFull:
                            self.overflow_queue.insert(0, item)
                            break

                    if moved > 0:
                        logger.info(f"Moved {moved} items from overflow to main queue")

            except asyncio.CancelledError:
                logger.info("Overflow queue processor cancelled")
                break
            except Exception as e:
                logger.error(f"Error processing overflow queue: {e}")

        logger.info("Overflow queue processor exited")

    async def _periodic_handler_update(self):
        """Periodically update handlers to catch channel changes"""
        while not self._shutdown.is_set():
            try:
                # Wait for 60 seconds or shutdown
                await asyncio.wait_for(self._shutdown.wait(), timeout=60)
                break  # Shutdown requested
            except asyncio.TimeoutError:
                # Update handlers
                try:
                    await self.update_handlers()
                except Exception as e:
                    logger.error(f"Error updating handlers: {e}")
            except asyncio.CancelledError:
                logger.info("Periodic handler update cancelled")
                break
            except Exception as e:
                logger.error(f"Error in periodic handler update: {e}")

        logger.info("Periodic handler update exited")

    async def handle_channel_media(self, client: Client, message: Message):
        """Handle media messages in monitored channels with rate limiting"""
        # Skip special channels
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
                                f"⚠️ <b>Queue Overflow Alert</b>\n"
                                f"The message queue has overflowed {self.queue_full_warnings} times.\n"
                                f"Current queue size: {self.message_queue.qsize()}/{self.message_queue.maxsize}\n"
                                f"Overflow queue size: {len(self.overflow_queue)}/{self.max_overflow_size}\n"
                                f"Consider reducing the indexing rate or increasing queue size."
                            )
                        except:
                            pass
        except Exception as e:
            logger.error(f"Error adding message to queue: {e}")

    async def _process_message_batch(self, batch: List[Dict]):
        """Process a batch of messages"""
        stats = {
            'indexed': 0,
            'duplicate': 0,
            'errors': 0
        }

        for item in batch:
            if self._shutdown.is_set():
                logger.info("Shutdown requested, stopping batch processing")
                break

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
                    f"📊 <b>Auto-Index Batch Summary</b>\n"
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
        """Process a single message"""
        try:
            # Extract media object
            media = None
            file_type = None

            for media_type in ("document", "video", "audio"):
                media = getattr(message, media_type, None)
                if media is not None:
                    file_type = media_type
                    break

            if not media:
                return "no_media"

            # Create MediaFile object
            media_file = MediaFile(
                file_id=media.file_id,
                file_unique_id=media.file_unique_id,
                file_ref=FileReferenceExtractor.extract_file_ref(media.file_id),
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
        # FIX 4: Track the initialization task
        self.init_task = asyncio.create_task(self._setup_initial_channels())

    async def _setup_initial_channels(self):
        """Setup initial channels from config"""
        try:
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

        except asyncio.CancelledError:
            logger.info("Initial channel setup cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in initial channel setup: {e}")

    async def update_handlers(self):
        """Update handlers based on current active channels"""
        # FIX 5: Use the lock that we now properly initialized
        async with self._update_lock:
            # Remove existing handlers
            for handler in self._handlers:
                try:
                    self.bot.remove_handler(handler)
                except Exception as e:
                    logger.error(f"Error removing handler: {e}")
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
                if self.bot.handler_manager:
                    handler = MessageHandler(
                        self.handle_channel_media,
                        combined_filter & self.media_filter
                    )
                    self.bot.handler_manager.add_handler(handler)
                    self._handlers.append(handler)

                logger.info(f"Updated automatic indexing for {len(channels)} active channels")


    def _get_file_type(self, media_type: str) -> FileType:
        """Convert media type string to FileType enum"""
        mapping = {
            'video': FileType.VIDEO,
            'audio': FileType.AUDIO,
            'document': FileType.DOCUMENT,
        }
        return mapping.get(media_type, FileType.DOCUMENT)



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

