import asyncio
import time
from collections import defaultdict
from typing import List, Dict

from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler
from pyrogram.types import Message

from config.settings import settings
from core.cache.config import CacheTTLConfig
from core.constants import ProcessingConstants
from core.utils.validators import normalize_filename_for_search, get_special_channels
from core.utils.helpers import extract_file_ref, parse_media_metadata
from core.utils.media_factory import MediaFileFactory
from core.utils.error_formatter import ErrorMessageFormatter
from core.utils.logger import get_logger
from core.utils.telegram_api import telegram_api
from repositories.channel import ChannelRepository
from repositories.channel_index_jobs import ChannelIndexJobRepository
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
        # Add rate limiting for bulk messages - use config values
        self.processing_config = settings.processing
        # Off by default. When enabled, store every accepted update in a new
        # MongoDB queue collection before returning from this handler.
        self.durable_jobs = (
            ChannelIndexJobRepository(
                bot.db_pool,
                lease_seconds=self.processing_config.durable_indexing_lease_seconds
            )
            if self.processing_config.durable_indexing else None
        )
        self.message_queue = asyncio.Queue(maxsize=self.processing_config.message_queue_size)
        self.overflow_queue = []  # Backup queue for overflow
        self.max_overflow_size = self.processing_config.overflow_queue_size
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
        # noinspection PyTypeChecker
        bot.handler_manager.create_background_task(  # noqa
            self._setup_initial_channels(),
            name="channel_initial_setup"
        )

    def _create_background_tasks(self):
        """Create all background tasks through handler_manager"""
        tasks_config = [
            (self._periodic_handler_update(), "channel_handler_update"),
            (self._cleanup_user_counts(), "channel_user_cleanup"),
        ]
        if self.durable_jobs is not None:
            tasks_config.append(
                (self._process_durable_queue(), "channel_durable_indexing")
            )
        else:
            tasks_config.extend([
                (self._process_message_queue(), "channel_message_queue"),
                (self._process_overflow_queue(), "channel_overflow_queue"),
            ])

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
        cleanup_interval = ProcessingConstants.USER_COUNT_CLEANUP_INTERVAL

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

                # PH-005: never silently trim pending messages. When both
                # bounded queues are full the handler now awaits backpressure
                # rather than dropping accepted messages.

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

                # Dynamic batch sizing using config values
                queue_size = self.message_queue.qsize()
                cfg = self.processing_config
                if queue_size > cfg.queue_high_threshold:
                    max_batch_size = cfg.batch_size_high_load
                    wait_time = cfg.batch_wait_time_high
                elif queue_size > cfg.queue_medium_threshold:
                    max_batch_size = cfg.batch_size_medium_load
                    wait_time = cfg.batch_wait_time_medium
                else:
                    max_batch_size = cfg.batch_size_low_load
                    wait_time = cfg.batch_wait_time_low

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
                # PH-005: the previous "-10" / "-5" limits prevented any
                # draining when a queue had <= 10 slots.
                if self.overflow_queue and not self.message_queue.full():
                    moved = 0
                    while self.overflow_queue and not self.message_queue.full():
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
        if message.chat.id in get_special_channels(self.bot.config):
            return

        if message.from_user and message.from_user.is_bot:
            return

        if getattr(self, "durable_jobs", None) is not None:
            # The snapshot is persisted before acknowledging the Telegram
            # update. Never queue a live Pyrogram Message object in MongoDB.
            from core.utils.media_extractor import extract_media_from_message
            result = extract_media_from_message(
                message, supported_types=["document", "video", "audio"]
            )
            if not result:
                return
            media, file_type, _ = result
            media_file = MediaFileFactory.from_pyrogram_media(
                media=media, message=message, file_type=file_type
            )
            # An enqueue exception is deliberately propagated and logged by
            # the handler framework. We cannot claim durability on DB outage.
            await self.durable_jobs.enqueue(
                message.chat.id,
                message.id,
                self.bot.media_repo._entity_to_dict(media_file),
            )
            return

        item = {'message': message, 'timestamp': time.time()}
        try:
            self.message_queue.put_nowait(item)
        except asyncio.QueueFull:
            if len(self.overflow_queue) < self.max_overflow_size:
                self.overflow_queue.append({
                    'message': message,
                    'timestamp': time.time()
                })
                logger.debug(f"Message added to overflow queue. Overflow size: {len(self.overflow_queue)}")
            else:
                # Never evict the oldest unprocessed message. Backpressure
                # awaits a free main-queue slot instead. For crash recovery
                # use PROCESSING_DURABLE_INDEXING=true on staging first.
                self.queue_full_warnings += 1
                if time.time() - self.last_warning_time > 60:
                    logger.warning(
                        "Indexing queues full; waiting for capacity "
                        "(main=%d, overflow=%d). No item discarded.",
                        self.message_queue.qsize(), len(self.overflow_queue),
                    )
                    self.last_warning_time = time.time()
                await self.message_queue.put(item)
        except Exception as e:
            logger.error(f"Error adding message to queue: {e}")

    async def _process_durable_queue(self):
        """At-least-once indexing worker with crash recovery and dead letters."""
        while not self._shutdown.is_set():
            try:
                await self.durable_jobs.ensure_indexes()
                break
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Cannot initialize durable index queue; retrying")
                try:
                    await asyncio.wait_for(self._shutdown.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass

        while not self._shutdown.is_set():
            try:
                job = await self.durable_jobs.claim()
                if job is None:
                    try:
                        await asyncio.wait_for(self._shutdown.wait(), timeout=1)
                    except asyncio.TimeoutError:
                        pass
                    continue

                try:
                    media_file = self.bot.media_repo._dict_to_entity(
                        dict(job["media"])
                    )
                    success, status, _ = await self.bot.media_repo.save_media(media_file)
                    if status not in (0, 1):
                        raise RuntimeError("Media repository did not accept indexed file")

                    # The Mongo record exists before the job is acknowledged.
                    acked = await self.durable_jobs.acknowledge(job)
                    if not acked:
                        logger.warning("Lost lease while acknowledging indexing job %s", job["_id"])
                        continue

                    if status == 1:
                        try:
                            await self.channel_repo.update_indexed_count(job["chat_id"])
                        except Exception:
                            logger.exception("Indexed file but channel counter update failed")
                        feature_service = getattr(self.bot, "feature_service", None)
                        if feature_service:
                            try:
                                if hasattr(feature_service, "persist_new_media"):
                                    await feature_service.persist_new_media(media_file)
                                else:
                                    feature_service.schedule_new_media(media_file)
                            except Exception:
                                # Media has already been saved and indexing job
                                # acknowledged; surface the cross-write gap.
                                logger.exception("Indexed file but durable alert enqueue failed")
                    await asyncio.sleep(self.processing_config.inter_message_delay)

                except asyncio.CancelledError:
                    # Leave current job leased; a replacement worker can reclaim
                    # it after lease_until. Never acknowledge on cancellation.
                    raise
                except Exception as error:
                    logger.exception("Durable indexing job %s failed", job["_id"])
                    await self.durable_jobs.fail(job, error)

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Durable channel indexing worker error")
                try:
                    await asyncio.wait_for(self._shutdown.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass

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

                await telegram_api.call_api(
                    self.bot.send_message,
                    self.bot.config.LOG_CHANNEL,
                    summary,
                    chat_id=self.bot.config.LOG_CHANNEL
                )
            except Exception:
                pass

    async def _process_single_message(self, message: Message) -> str:
        """Process a single message"""
        try:
            # Extract media object using unified extractor
            from core.utils.media_extractor import extract_media_from_message
            
            result = extract_media_from_message(message, supported_types=["document", "video", "audio"])
            if not result:
                return "no_media"
            
            media, file_type, _ = result

            # Create MediaFile object using MediaFileFactory
            media_file = MediaFileFactory.from_pyrogram_media(
                media=media,
                message=message,
                file_type=file_type
            )

            # Save to database
            success, status_code, existing_file = await self.bot.media_repo.save_media(media_file)

            if status_code == 1:
                logger.info(f"Successfully indexed: {media_file.file_name}")
                await self.channel_repo.update_indexed_count(message.chat.id)
                feature_service = getattr(self.bot, 'feature_service', None)
                if feature_service:
                    if hasattr(feature_service, "persist_new_media"):
                        await feature_service.persist_new_media(media_file)
                    else:
                        feature_service.schedule_new_media(media_file)
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
                    if self.bot.handler_manager:
                        self.bot.handler_manager.remove_handler(handler)
                    else:
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


