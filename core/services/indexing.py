import asyncio
import base64
import re
from typing import Dict, Optional, Tuple

from pyrogram import Client, enums
from pyrogram.errors import ChannelInvalid, UsernameInvalid, UsernameNotModified
from pyrogram.file_id import FileId
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from core.cache.config import CacheKeyGenerator
from core.cache.redis_cache import CacheManager
from core.utils.helpers import sanitize_filename
from core.utils.link_parser import TelegramLinkParser
from core.utils.logger import get_logger
from core.utils.telegram_api import telegram_api
from core.utils.file_reference import FileReferenceExtractor
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
            chat = await client.get_chat(chat_id)

            # Check if bot is admin for private channels
            if chat.type == enums.ChatType.CHANNEL:
                try:
                    member = await client.get_chat_member(chat_id, "me")
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
            progress_callback=None
    ) -> Dict[str, int]:
        """
        Index files from a channel
        Returns statistics of the indexing process
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

            try:
                async for message in bot.iter_messages(
                        chat_id,
                        last_msg_id,
                        self.current_index
                ):
                    if self.cancel_indexing:
                        logger.info("Indexing cancelled by user")
                        break

                    current += 1
                    stats['total_messages'] = current

                    # Progress callback every 20 messages
                    if current % 20 == 0 and progress_callback:
                        await progress_callback(stats)
                        await asyncio.sleep(2)  # Prevent flooding

                    # Process message
                    result = await self._process_message(message)

                    if result == "saved":
                        stats['total_files'] += 1
                    elif result == "duplicate":
                        stats['duplicate'] += 1
                    elif result == "duplicate_hash":
                        stats['duplicate'] += 1
                        stats['duplicate_by_hash'] += 1
                    elif result == "deleted":
                        stats['deleted'] += 1
                    elif result == "no_media":
                        stats['no_media'] += 1
                    elif result == "unsupported":
                        stats['unsupported'] += 1
                    elif result == "error":
                        stats['errors'] += 1

            except Exception as e:
                logger.error(f"Error during indexing: {e}")
                raise

        return stats

    async def _process_message(self, message: Message) -> str:
        """Process a single message and return status"""
        if message.empty:
            return "deleted"

        if not message.media:
            return "no_media"

        # Check supported media types
        if message.media not in [
            enums.MessageMediaType.VIDEO,
            enums.MessageMediaType.AUDIO,
            enums.MessageMediaType.DOCUMENT
        ]:
            return "unsupported"

        # Get media object
        media = getattr(message, message.media.value, None)
        if not media:
            return "unsupported"

        # Extract file info
        try:
            file_type = self._get_file_type(message.media)

            # Create MediaFile object
            media_file = MediaFile(
                file_id=media.file_id,
                file_unique_id=media.file_unique_id,
                file_ref=FileReferenceExtractor.extract_file_ref(media.file_id),
                file_name=sanitize_filename(
                    getattr(media, 'file_name', f'file_{media.file_unique_id}')
                ),
                file_size=media.file_size,
                file_type=file_type,
                mime_type=getattr(media, 'mime_type', None),
                caption=message.caption.html if message.caption else None
            )

            # Save to database with improved duplicate handling
            success, status_code, existing_file = await self.media_repo.save_media(media_file)

            if status_code == 1:
                logger.debug(f"Successfully indexed: {media_file.file_name}")
                common_terms = media_file.file_name.lower().split()[:3]
                for term in common_terms:
                    pattern = f"search:{term}*"
                    cache_key = CacheKeyGenerator.search_results(term, None, 0, 10, True)
                    await self.cache.delete(cache_key)
                return "saved"
            elif status_code == 0:
                if existing_file and existing_file.file_unique_id == media_file.file_unique_id:
                    logger.debug(f"Duplicate file (same content): {media_file.file_name}")
                    return "duplicate"
                else:
                    logger.debug(f"Duplicate file (different content): {media_file.file_name}")
                    return "duplicate"
            else:
                logger.error(f"Failed to index file: {media_file.file_name}")
                return "error"

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return "error"

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



    def _encode_file_id(self, s: bytes) -> str:
        """Encode file ID to URL-safe base64"""
        r = b""
        n = 0

        for i in s + bytes([22]) + bytes([4]):
            if i == 0:
                n += 1
            else:
                if n:
                    r += b"\x00" + bytes([n])
                    n = 0
                r += bytes([i])

        return base64.urlsafe_b64encode(r).decode().rstrip("=")


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
                    invite = await client.create_chat_invite_link(chat_id)
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