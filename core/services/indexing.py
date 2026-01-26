import asyncio
import re
from typing import Dict, Optional, Tuple, List

from pyrogram import Client, enums
from pyrogram.errors import ChannelInvalid, UsernameInvalid, UsernameNotModified
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from core.cache.redis_cache import CacheManager
from core.concurrency.semaphore_manager import semaphore_manager
from core.utils.validators import normalize_filename_for_search
from core.utils.link_parser import TelegramLinkParser
from core.utils.logger import get_logger
from core.utils.telegram_api import telegram_api
from core.utils.helpers import extract_file_ref
from repositories.media import MediaRepository, MediaFile, FileType

logger = get_logger(__name__)


class IndexingService:
    """Service for indexing files from channels"""

    def __init__(
            self,
            media_repo: MediaRepository,
            cache_manager: CacheManager
    ):
        self.media_repo = media_repo
        self.cache = cache_manager
        self.current_index = 0
        self.cancel_indexing = False
        self._lock = asyncio.Lock()

    def reset_indexing(self):
        """Reset indexing state"""
        self.cancel_indexing = False
        self.current_index = 0

    def cancel(self):
        """Cancel ongoing indexing"""
        self.cancel_indexing = True

    @property
    def is_indexing(self) -> bool:
        """Check if indexing is in progress"""
        return self._lock.locked()

    async def set_skip_number(self, skip: int):
        """Set the starting message ID for indexing"""
        self.current_index = skip

    async def validate_channel(
            self,
            client_or_bot,
            channel_input: str
    ) -> Tuple[Optional[int], Optional[str]]:
        """
        Validate channel and return channel_id and error message if any
        """
        try:
            client = client_or_bot.client if hasattr(client_or_bot, 'client') else client_or_bot
            # Parse channel input
            if isinstance(channel_input, str):
                # Check if it's a link using centralized parser
                parsed_link = TelegramLinkParser.parse_link(channel_input)
                
                if parsed_link:
                    # Use the parsed chat ID or identifier
                    chat_id = parsed_link.chat_id if parsed_link.chat_id else parsed_link.chat_identifier
                else:
                    # Assume it's a username or ID
                    try:
                        chat_id = int(channel_input)
                    except ValueError:
                        chat_id = channel_input
            else:
                chat_id = channel_input

            # Verify bot has access
            chat = await telegram_api.call_api(
                client.get_chat,
                chat_id,
                chat_id=chat_id if isinstance(chat_id, int) else None
            )

            # Check if bot is admin for private channels
            if chat.type == enums.ChatType.CHANNEL:
                try:
                    member = await telegram_api.call_api(
                        client.get_chat_member,
                        chat_id,
                        "me",
                        chat_id=chat.id
                    )
                    if member.status not in [
                        enums.ChatMemberStatus.ADMINISTRATOR,
                        enums.ChatMemberStatus.OWNER
                    ]:
                        return None, "I need to be an admin in the channel to index files."
                except Exception:
                    return None, "Make sure I'm an admin in the channel."

            return chat.id, None

        except ChannelInvalid:
            return None, "This may be a private channel/group. Make me an admin to index files."
        except (UsernameInvalid, UsernameNotModified):
            return None, "Invalid link or username specified."
        except Exception as e:
            error_msg = str(e).lower()
            if "channel_private" in error_msg:
                return None, (
                    "<b>Bot Access Required</b>\n\n"
                    "This is a private channel. Please:\n"
                    "1. Add me to the channel\n"
                    "2. Make me an admin\n"
                    "3. Try again"
                )
            elif "chat not found" in error_msg:
                return None, "Channel not found. Please check the link/username."
            else:
                logger.exception(e)
                return None, f"Error: {str(e)}"

    async def index_files(
            self,
            bot,
            chat_id: int,
            last_msg_id: int,
            progress_callback=None,
            batch_size: int = 50
    ) -> Dict[str, int]:
        """
        Index files from a channel using batched processing for efficiency.
        Returns statistics of the indexing process.

        Args:
            bot: The bot client
            chat_id: Channel ID to index
            last_msg_id: Last message ID to index up to
            progress_callback: Optional callback for progress updates
            batch_size: Number of messages to process in each batch (default: 50)
        """
        stats = {
            'total_messages': 0,
            'total_files': 0,
            'duplicate': 0,
            'errors': 0,
            'deleted': 0,
            'no_media': 0,
            'unsupported': 0,
            'duplicate_by_hash': 0  # Track duplicates found by hash
        }

        async with self._lock:
            self.reset_indexing()
            current = self.current_index
            message_batch: List[Message] = []

            try:
                async for message in bot.iter_messages(
                        chat_id,
                        last_msg_id,
                        self.current_index
                ):
                    if self.cancel_indexing:
                        logger.info("Indexing cancelled by user")
                        # Process remaining messages in batch before breaking
                        if message_batch:
                            batch_stats = await self._process_message_batch(message_batch)
                            self._merge_stats(stats, batch_stats)
                        break

                    current += 1
                    stats['total_messages'] = current
                    message_batch.append(message)

                    # Process batch when it reaches batch_size
                    if len(message_batch) >= batch_size:
                        batch_stats = await self._process_message_batch(message_batch)
                        self._merge_stats(stats, batch_stats)
                        message_batch = []

                        # Progress callback after batch processing
                        if progress_callback:
                            await progress_callback(stats)
                            await asyncio.sleep(1)  # Prevent flooding

                # Process any remaining messages in the final batch
                if message_batch:
                    batch_stats = await self._process_message_batch(message_batch)
                    self._merge_stats(stats, batch_stats)

                    if progress_callback:
                        await progress_callback(stats)

            except Exception as e:
                logger.error(f"Error during indexing: {e}")
                raise

        return stats

    def _merge_stats(self, target: Dict[str, int], source: Dict[str, int]) -> None:
        """Merge batch stats into target stats"""
        for key in ['total_files', 'duplicate', 'errors', 'deleted',
                    'no_media', 'unsupported', 'duplicate_by_hash']:
            target[key] += source.get(key, 0)

    async def _process_message_batch(self, messages: List[Message]) -> Dict[str, int]:
        """
        Process a batch of messages with optimized duplicate checking.
        Uses batch_check_duplicates to reduce N+1 queries.
        """
        batch_stats = {
            'total_files': 0,
            'duplicate': 0,
            'errors': 0,
            'deleted': 0,
            'no_media': 0,
            'unsupported': 0,
            'duplicate_by_hash': 0
        }

        # First pass: Extract media files from messages
        media_files: List[MediaFile] = []
        message_to_media: Dict[int, MediaFile] = {}  # Map message.id to MediaFile

        for message in messages:
            if message.empty:
                batch_stats['deleted'] += 1
                continue

            if not message.media:
                batch_stats['no_media'] += 1
                continue

            if message.media not in [
                enums.MessageMediaType.VIDEO,
                enums.MessageMediaType.AUDIO,
                enums.MessageMediaType.DOCUMENT
            ]:
                batch_stats['unsupported'] += 1
                continue

            media = getattr(message, message.media.value, None)
            if not media:
                batch_stats['unsupported'] += 1
                continue

            try:
                file_type = self._get_file_type(message.media)
                media_file = MediaFile(
                    file_id=media.file_id,
                    file_unique_id=media.file_unique_id,
                    file_ref=extract_file_ref(media.file_id),
                    file_name=normalize_filename_for_search(
                        getattr(media, 'file_name', f'file_{media.file_unique_id}')
                    ),
                    file_size=media.file_size,
                    file_type=file_type,
                    resolution=(
                        f"{getattr(media, 'width', None)}x{getattr(media, 'height', None)}"
                        if getattr(media, 'width', None) and getattr(media, 'height', None)
                        else None
                    ),
                    mime_type=getattr(media, 'mime_type', None),
                    caption=message.caption.html if message.caption else None
                )
                media_files.append(media_file)
                message_to_media[message.id] = media_file
            except Exception as e:
                logger.error(f"Error extracting media from message {message.id}: {e}")
                batch_stats['errors'] += 1

        if not media_files:
            return batch_stats

        # Second pass: Batch check for duplicates
        try:
            duplicates_map = await self.media_repo.batch_check_duplicates(media_files)
        except Exception as e:
            logger.error(f"Batch duplicate check failed: {e}")
            # Fallback to individual processing
            for media_file in media_files:
                result = await self._save_single_file(media_file)
                if result == "saved":
                    batch_stats['total_files'] += 1
                elif result == "duplicate":
                    batch_stats['duplicate'] += 1
                elif result == "error":
                    batch_stats['errors'] += 1
            return batch_stats

        # Third pass: Save non-duplicates, count duplicates
        files_to_save: List[MediaFile] = []
        for media_file in media_files:
            existing = duplicates_map.get(media_file.file_unique_id)
            if existing:
                batch_stats['duplicate'] += 1
                logger.debug(f"Duplicate file: {media_file.file_name}")
            else:
                files_to_save.append(media_file)

        # Bulk save non-duplicate files
        if files_to_save:
            saved_count, error_count = await self._bulk_save_files(files_to_save)
            batch_stats['total_files'] += saved_count
            batch_stats['errors'] += error_count

        return batch_stats

    async def _save_single_file(self, media_file: MediaFile) -> str:
        """Save a single file (fallback for when batch fails)"""
        try:
            # Use semaphore to control concurrent database write operations
            async with semaphore_manager.acquire('database_write'):
                success, status_code, existing = await self.media_repo.save_media(media_file)
                if status_code == 1:
                    return "saved"
                elif status_code == 0:
                    return "duplicate"
                else:
                    return "error"
        except Exception as e:
            logger.error(f"Error saving file {media_file.file_name}: {e}")
            return "error"

    async def _bulk_save_files(self, files: List[MediaFile]) -> Tuple[int, int]:
        """
        Bulk save files to database.
        Returns: (saved_count, error_count)
        """
        saved_count = 0
        error_count = 0

        # Use semaphore to control concurrent database write operations
        async with semaphore_manager.acquire('database_write'):
            # Use bulk insert if available, otherwise save individually
            try:
                # Try bulk insert
                if hasattr(self.media_repo, 'bulk_save_media'):
                    result = await self.media_repo.bulk_save_media(files)
                    saved_count = result.get('saved', 0)
                    error_count = result.get('errors', 0)
                else:
                    # Fallback to individual saves
                    for media_file in files:
                        try:
                            success, status_code, _ = await self.media_repo.save_media(media_file)
                            if status_code == 1:
                                saved_count += 1
                                # Cache invalidation handled by repository
                            else:
                                error_count += 1
                        except Exception as e:
                            logger.error(f"Error saving file {media_file.file_name}: {e}")
                            error_count += 1
            except Exception as e:
                logger.error(f"Bulk save failed: {e}")
                error_count = len(files)

        return saved_count, error_count

    def _get_file_type(self, media_type: enums.MessageMediaType) -> FileType:
        """Convert Pyrogram media type to FileType enum"""
        mapping = {
            enums.MessageMediaType.VIDEO: FileType.VIDEO,
            enums.MessageMediaType.AUDIO: FileType.AUDIO,
            enums.MessageMediaType.DOCUMENT: FileType.DOCUMENT,
            enums.MessageMediaType.PHOTO: FileType.PHOTO,
            enums.MessageMediaType.ANIMATION: FileType.ANIMATION
        }
        return mapping.get(media_type, FileType.DOCUMENT)


class IndexRequestService:
    """Service for handling index requests from users"""

    def __init__(
            self,
            indexing_service: IndexingService,
            cache_manager: CacheManager,
            index_request_channel: int,
            log_channel: int = None
    ):
        self.indexing_service = indexing_service
        self.cache = cache_manager
        self.index_request_channel = index_request_channel
        self.log_channel = log_channel

    async def create_index_request(
            self,
            client: Client,
            user_id: int,
            chat_id: str | int,
            last_msg_id: int,
            message_id: int
    ) -> bool:
        """Create an index request for admin approval"""
        try:
            # Get invite link if possible
            link = f"@{chat_id}"
            if isinstance(chat_id, int):
                try:
                    invite = await telegram_api.call_api(
                        client.create_chat_invite_link,
                        chat_id,
                        chat_id=chat_id
                    )
                    link = invite.invite_link
                except Exception:
                    pass

            # Create request message
            text = (
                f"#IndexRequest\n\n"
                f"By: <a href='tg://user?id={user_id}'>{user_id}</a>\n"
                f"Chat ID/Username: <code>{chat_id}</code>\n"
                f"Last Message ID: <code>{last_msg_id}</code>\n"
                f"Invite Link: {link}"
            )

            # Buttons for admin actions
            buttons = [
                [
                    InlineKeyboardButton(
                        "✅ Accept",
                        callback_data=f"index#accept#{chat_id}#{last_msg_id}#{user_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Reject",
                        callback_data=f"index#reject#{chat_id}#{message_id}#{user_id}"
                    )
                ]
            ]
            target_channel = self.index_request_channel

            try:
                await telegram_api.call_api(
                    client.send_message,
                    target_channel,
                    text,
                    reply_markup=InlineKeyboardMarkup(buttons),
                    chat_id=target_channel
                )
                return True
            except Exception as e:
                logger.error(f"Failed to send to INDEX_REQ_CHANNEL: {e}")

                # Fallback to LOG_CHANNEL if different and available
                if (target_channel != self.log_channel and
                        self.log_channel and
                        self.log_channel != 0):
                    try:
                        await telegram_api.call_api(
                            client.send_message,
                            self.log_channel,
                            text + "\n\n⚠️ Failed to send to INDEX_REQ_CHANNEL",
                            reply_markup=InlineKeyboardMarkup(buttons),
                            chat_id=self.log_channel
                        )
                        return True
                    except Exception as e2:
                        logger.error(f"Failed to send to LOG_CHANNEL: {e2}")

            return False

        except Exception as e:
            logger.error(f"Error creating index request: {e}")
            return False