import asyncio
import base64
import hashlib
import json
import os
import time
import uuid
from typing import Dict, Any, Optional, List, Tuple

from pyrogram import Client, enums
from pyrogram.errors import FloodWait
from pyrogram.types import Message

from core.cache.config import CacheTTLConfig
from core.cache.redis_cache import CacheManager
from core.utils.caption import CaptionFormatter
from core.utils.helpers import sanitize_filename
from core.utils.logger import get_logger
from core.utils.link_parser import TelegramLinkParser, ParsedTelegramLink
from core.utils.telegram_api import telegram_api
from core.utils.file_reference import FileReferenceExtractor
from repositories.media import MediaRepository, MediaFile, FileType
from repositories.batch_link import BatchLinkRepository, BatchLink

logger = get_logger(__name__)


class FileStoreService:
    """Service for managing file store operations"""

    def __init__(
            self,
            media_repo: MediaRepository,
            cache_manager: CacheManager,
            config: Any,
            batch_link_repo: Optional[BatchLinkRepository] = None

    ):
        self.media_repo = media_repo
        self.cache = cache_manager
        self.config = config
        self.batch_link_repo = batch_link_repo
        self.batch_cache = {}  # In-memory cache for batch files
        self.batch_cache_ttl = CacheTTLConfig.SEARCH_SESSION   # 1 hour
        self.max_batch_cache_size = 100
        self.batch_cache_access_time = {}

    async def _auto_delete_message(self, message: Message, delay: int):
        """Auto-delete message after delay"""
        try:
            await asyncio.sleep(delay)
            await message.delete()
        except Exception as e:
            logger.debug(f"Failed to delete message: {e}")

    def encode_file_identifier(self, file_identifier: str, protect: bool = False) -> str:
        """
        Encode file identifier (file_ref) to shareable string
        Now uses file_ref for consistency
        """
        prefix = 'filep_' if protect else 'file_'
        string = prefix + file_identifier
        return base64.urlsafe_b64encode(string.encode("ascii")).decode().strip("=")

    def decode_file_identifier(self, encoded: str) -> Tuple[str|None, bool]:
        """
        Decode file identifier from shareable string
        Returns: (file_identifier, is_protected)
        """
        try:
            # Validate input
            if not encoded or not isinstance(encoded, str):
                logger.warning(f"Invalid encoded string: {encoded}")
                return None, False
                
            # Clean the encoded string
            encoded = encoded.strip()
            if not encoded:
                logger.warning("Empty encoded string after stripping")
                return None, False
            
            # Validate base64 character length
            if len(encoded) % 4 == 1:
                logger.error(f"Invalid base64 length: {len(encoded)} - cannot be 1 more than multiple of 4")
                return None, False
            
            # Add proper padding
            padding = "=" * (-len(encoded) % 4)
            encoded_padded = encoded + padding
            
            decoded = base64.urlsafe_b64decode(encoded_padded).decode("ascii")

            if decoded.startswith('filep_'):
                return decoded[6:], True
            elif decoded.startswith('file_'):
                return decoded[5:], False
            else:
                # Try without prefix (backward compatibility)
                parts = decoded.split("_", 1)
                if len(parts) == 2:
                    return parts[1], parts[0] == 'filep'
                return decoded, False

        except Exception as e:
            logger.error(f"Error decoding file identifier '{encoded}': {e}")
            return None, False

    # Backward compatibility methods
    def encode_file_id(self, file_id: str, protect: bool = False) -> str:
        """Backward compatibility - converts file_id to file_ref then encodes"""
        return self.encode_file_identifier(file_id, protect)

    def decode_file_id(self, encoded: str) -> Tuple[str, bool]:
        """Backward compatibility - same as decode_file_identifier"""
        return self.decode_file_identifier(encoded)




    async def _cleanup_batch_cache(self):
        """Remove oldest entries if cache is too large"""
        if len(self.batch_cache) > self.max_batch_cache_size:
            # Sort by access time and remove oldest
            sorted_keys = sorted(
                self.batch_cache_access_time.items(),
                key=lambda x: x[1]
            )
            to_remove = len(self.batch_cache) - self.max_batch_cache_size
            for key, _ in sorted_keys[:to_remove]:
                self.batch_cache.pop(key, None)
                self.batch_cache_access_time.pop(key, None)



    async def create_file_link(
            self,
            client: Client,
            message: Message,
            protect: bool = False
    ) -> Optional[str]:
        """Create shareable link for a file using file_ref"""
        if not message.reply_to_message:
            return None

        file_type = message.reply_to_message.media
        if file_type not in [enums.MessageMediaType.VIDEO, enums.MessageMediaType.AUDIO,
                             enums.MessageMediaType.DOCUMENT]:
            return None

        # Get media object
        media = getattr(message.reply_to_message, str(file_type.value))
        #logger.info(f"media is {media}")
        media_file_unique_id = media.file_unique_id
        #logger.info(f"media_file_unique_id is {media_file_unique_id}")

        # Find file in database to get file
        file = await self.media_repo.find_file(media_file_unique_id)

        if not file:
            # File not in database, create and save it
            file_ref = FileReferenceExtractor.extract_file_ref(media.file_id)
            identifier = media_file_unique_id

            # Create MediaFile and save to database
            # Determine file type
            file_type_enum = FileType.DOCUMENT
            if file_type == enums.MessageMediaType.VIDEO:
                file_type_enum = FileType.VIDEO
            elif file_type == enums.MessageMediaType.AUDIO:
                file_type_enum = FileType.AUDIO

            # Sanitize filename
            filename = getattr(media, 'file_name', f'{file_type.value}_{media.file_unique_id}')
            filename = sanitize_filename(filename)

            media_file = MediaFile(
                file_id=media.file_id,
                file_unique_id=identifier,
                file_ref=file_ref,
                file_name=filename,
                file_size=media.file_size,
                file_type=file_type_enum,
                mime_type=getattr(media, 'mime_type', None),
                caption=message.reply_to_message.caption.html if message.reply_to_message.caption else None
            )

            # Save to database - now returns existing file if duplicate
            success, status, existing_file = await self.media_repo.save_media(media_file)

            if status == 0 and existing_file:
                # Duplicate found, use the existing file
                file = existing_file
                identifier = file.file_unique_id
                logger.info(f"Using existing duplicate file with ref: {identifier}")
            elif success:
                # New file saved successfully
                identifier = media_file.file_unique_id
                logger.info(f"Successfully saved new file to database with ref: {identifier}")
            else:
                # Error saving file and no duplicate found
                logger.error(f"Failed to save file to database: {media_file_unique_id}")
                return None
        else:
            # Use file_ref from existing database entry
            identifier = file.file_unique_id
            logger.info(f"Using existing file_ref from database: {identifier}")

        # Generate link
        encoded = self.encode_file_identifier(identifier, protect)
        bot_username = (await client.get_me()).username

        # Ensure the encoded string isn't too long for Telegram
        if len(encoded) > 64:
            logger.error(f"Encoded identifier too long: {len(encoded)} characters")
            # Try using a shorter identifier
            short_ref = hashlib.md5(identifier.encode()).hexdigest()[:16]

            # Update the file with short ref
            if file:
                await self.media_repo.update(file.file_unique_id, {'file_ref': short_ref})
            else:
                await self.media_repo.update(media_file_unique_id, {'file_ref': short_ref})

            encoded = self.encode_file_identifier(short_ref, protect)
            logger.info(f"Using shortened ref: {short_ref}")

        link = f"https://t.me/{bot_username}?start={encoded}"
        logger.info(f"Generated link: {link} for file_ref: {identifier}")
        return link

    async def create_batch_link(
            self,
            client: Client,
            first_msg_link: str,
            last_msg_link: str,
            protect: bool = False
    ) -> Optional[str]:
        """Create batch link for multiple files"""
        # Parse message links
        import re

        # Updated regex pattern to handle both numeric IDs and usernames
        link_pattern = re.compile(
            r"(?:https?://)?(?:t\.me|telegram\.me|telegram\.dog)/"
            r"(?:c/)?(\d+|[a-zA-Z][a-zA-Z0-9_-]*)/(\d+)/?$"
        )

        # Parse first link
        match = link_pattern.match(first_msg_link.strip())
        if not match:
            logger.error(f"First link doesn't match pattern: {first_msg_link}")
            return None

        f_chat_id = match.group(1)
        f_msg_id = int(match.group(2))

        # Handle channel IDs (numeric IDs from /c/ links need -100 prefix)
        if f_chat_id.isdigit():
            if '/c/' in first_msg_link:
                f_chat_id = int("-100" + f_chat_id)
            else:
                # Regular numeric ID (might already have -100 prefix)
                f_chat_id = int(f_chat_id)
        else:
            # It's a username, try to get channel info
            try:
                chat = await client.get_chat(f_chat_id)
                f_chat_id = chat.id
            except Exception as e:
                logger.error(f"Error resolving chat {f_chat_id}: {e}")
                return None

        # Parse last link
        match = link_pattern.match(last_msg_link.strip())
        if not match:
            logger.error(f"Last link doesn't match pattern: {last_msg_link}")
            return None

        l_chat_id = match.group(1)
        l_msg_id = int(match.group(2))

        # Handle channel IDs
        if l_chat_id.isdigit():
            if '/c/' in last_msg_link:
                l_chat_id = int("-100" + l_chat_id)
            else:
                l_chat_id = int(l_chat_id)
        else:
            try:
                chat = await client.get_chat(l_chat_id)
                l_chat_id = chat.id
            except Exception as e:
                logger.error(f"Error resolving chat {l_chat_id}: {e}")
                return None

        if f_chat_id != l_chat_id:
            logger.error(f"Chat IDs don't match: {f_chat_id} != {l_chat_id}")
            return None

        # Create batch data
        string = f"{f_msg_id}_{l_msg_id}_{f_chat_id}_{'pbatch' if protect else 'batch'}"
        b_64 = base64.urlsafe_b64encode(string.encode("ascii")).decode().strip("=")
        bot_username = (await client.get_me()).username
        return f"https://t.me/{bot_username}?start=DSTORE-{b_64}"

    async def create_premium_batch_link(
            self,
            client: Client,
            first_msg_link: str,
            last_msg_link: str,
            protect: bool = False,
            premium_only: bool = True,
            created_by: int = 0
    ) -> Optional[str]:
        """Create premium-only batch link using robust parsing and validation"""
        if not self.batch_link_repo:
            logger.error("BatchLinkRepository not initialized - falling back to regular batch link")
            return await self.create_batch_link(client, first_msg_link, last_msg_link, protect)
        
        # Use robust link parser
        parsed_links = TelegramLinkParser.parse_link_pair(first_msg_link, last_msg_link)
        if not parsed_links:
            logger.error(f"Failed to parse link pair: {first_msg_link} -> {last_msg_link}")
            return None
            
        first_parsed, last_parsed = parsed_links
        
        # Resolve chat ID if needed (for username-based links)
        chat_id = first_parsed.chat_id
        if chat_id is None:
            try:
                # Use API wrapper for flood protection
                chat = await telegram_api.call_api(
                    client.get_chat, 
                    first_parsed.chat_identifier,
                    chat_id=None  # No per-chat limiting for get_chat
                )
                chat_id = chat.id
                logger.info(f"Resolved chat {first_parsed.chat_identifier} to ID {chat_id}")
            except Exception as e:
                logger.error(f"Error resolving chat {first_parsed.chat_identifier}: {e}")
                return None
        
        # Validate bot has access to source channel
        try:
            # Check if bot can access the first message (quick validation)
            await telegram_api.call_api(
                client.get_messages,
                chat_id,
                first_parsed.message_id,
                chat_id=chat_id
            )
        except Exception as e:
            logger.error(f"Bot cannot access source channel {chat_id}: {e}")
            return None

        # Check for duplicate batch links to prevent spam
        existing_links = await self.batch_link_repo.get_user_batch_links(created_by, limit=5)
        for existing in existing_links:
            if (existing.source_chat_id == chat_id and 
                existing.from_msg_id == first_parsed.message_id and
                existing.to_msg_id == last_parsed.message_id and
                existing.protected == protect and
                existing.premium_only == premium_only):
                logger.info(f"Returning existing duplicate batch link: {existing.id}")
                bot_username = (await client.get_me()).username
                return f"https://t.me/{bot_username}?start=PBLINK-{existing.id}"

        # Generate unique batch link ID
        batch_id = f"BL-{uuid.uuid4().hex[:12]}"
        
        # Create BatchLink entity with validated data
        batch_link = BatchLink(
            id=batch_id,
            source_chat_id=chat_id,
            from_msg_id=first_parsed.message_id,
            to_msg_id=last_parsed.message_id,
            protected=protect,
            premium_only=premium_only,
            created_by=created_by
        )

        # Save to database
        success = await self.batch_link_repo.create_batch_link(batch_link)
        if not success:
            logger.error(f"Failed to save batch link: {batch_id}")
            return None

        # Structured logging for audit trail
        logger.info(f"Created premium batch link", extra={
            "event": "batch.link.created",
            "batch_id": batch_id,
            "created_by": created_by,
            "source_chat_id": chat_id,
            "message_range": f"{first_parsed.message_id}-{last_parsed.message_id}",
            "message_count": last_parsed.message_id - first_parsed.message_id + 1,
            "protected": protect,
            "premium_only": premium_only
        })

        # Generate the link using API wrapper
        try:
            me = await telegram_api.call_api(client.get_me)
            bot_username = me.username
            return f"https://t.me/{bot_username}?start=PBLINK-{batch_id}"
        except Exception as e:
            logger.error(f"Failed to get bot username: {e}")
            return None

    async def get_premium_batch_link(self, batch_id: str) -> Optional[BatchLink]:
        """Get premium batch link details"""
        if not self.batch_link_repo:
            return None
        return await self.batch_link_repo.get_batch_link(batch_id)

    async def check_premium_batch_access(
            self,
            batch_link: BatchLink,
            user_id: int,
            user_is_premium: bool,
            global_premium_enabled: bool
    ) -> Tuple[bool, str]:
        """
        Check if user can access premium batch link based on updated rules:
        1. If link.premium_only = true:
           - If global premium is DISABLED → deny (premium features not available)
           - If global premium is ENABLED → require user.is_premium
        2. Else if global_premium = true → require user.is_premium
        3. Else → allow

        Premium batch links now require global premium to be enabled
        """
        correlation_id = f"user_{user_id}_batch_{batch_link.id}"

        # Premium batch link check
        if batch_link.premium_only:
            # Check if global premium is disabled
            if not global_premium_enabled:
                logger.info(f"Premium batch access denied - premium features disabled", extra={
                    "event": "batch.access.denied",
                    "correlation_id": correlation_id,
                    "user_id": user_id,
                    "batch_id": batch_link.id,
                    "reason": "premium_features_disabled",
                    "user_premium": user_is_premium,
                    "global_premium": global_premium_enabled,
                    "link_premium_only": batch_link.premium_only
                })
                return False, "❌ Premium features are currently disabled. This batch link requires premium features to be enabled."

            # Global premium is enabled, check user premium status
            if not user_is_premium:
                logger.info(f"Premium batch access denied - link requires premium", extra={
                    "event": "batch.access.denied",
                    "correlation_id": correlation_id,
                    "user_id": user_id,
                    "batch_id": batch_link.id,
                    "reason": "link_premium_required",
                    "user_premium": user_is_premium,
                    "global_premium": global_premium_enabled,
                    "link_premium_only": batch_link.premium_only
                })
                return False, "❌ This batch link requires premium membership. Upgrade to access premium-only content!"
            else:
                logger.info(f"Premium batch access granted - user has premium", extra={
                    "event": "batch.access.granted",
                    "correlation_id": correlation_id,
                    "user_id": user_id,
                    "batch_id": batch_link.id,
                    "reason": "link_premium_satisfied",
                    "user_premium": user_is_premium
                })
                return True, ""

        # Global premium check (only applies if link is not premium-only)
        elif global_premium_enabled:
            if not user_is_premium:
                logger.info(f"Batch access denied - global premium required", extra={
                    "event": "batch.access.denied",
                    "correlation_id": correlation_id,
                    "user_id": user_id,
                    "batch_id": batch_link.id,
                    "reason": "global_premium_required",
                    "user_premium": user_is_premium,
                    "global_premium": global_premium_enabled
                })
                return False, "❌ Premium membership required. Upgrade to access this content!"
            else:
                logger.info(f"Batch access granted - global premium satisfied", extra={
                    "event": "batch.access.granted",
                    "correlation_id": correlation_id,
                    "user_id": user_id,
                    "batch_id": batch_link.id,
                    "reason": "global_premium_satisfied",
                    "user_premium": user_is_premium
                })
                return True, ""

        # No premium requirements
        logger.info(f"Batch access granted - no premium required", extra={
            "event": "batch.access.granted",
            "correlation_id": correlation_id,
            "user_id": user_id,
            "batch_id": batch_link.id,
            "reason": "no_premium_required"
        })
        return True, ""

    async def get_batch_data(
            self,
            client: Client,
            batch_identifier: str
    ) -> Optional[List[Dict[str, Any]]]:
        """Retrieve batch data from cache or download"""
        if batch_identifier in self.batch_cache:
            self.batch_cache_access_time[batch_identifier] = time.time()
            return self.batch_cache[batch_identifier]
        # Check cache first
        if batch_identifier in self.batch_cache:
            return self.batch_cache[batch_identifier]

        # Try to find file by identifier
        file = await self.media_repo.find_file(batch_identifier)
        if not file:
            return None

        # Download from telegram using file_id
        try:
            file_path = await client.download_media(file.file_id)

            if not file_path:
                return None

            with open(file_path, 'r', encoding='utf-8') as f:
                batch_data = json.load(f)

            # Cache for future use
            self.batch_cache[batch_identifier] = batch_data

            # Clean up
            os.remove(file_path)
            if batch_data:
                self.batch_cache[batch_identifier] = batch_data
                self.batch_cache_access_time[batch_identifier] = time.time()
                await self._cleanup_batch_cache()

            return batch_data

        except Exception as e:
            logger.error(f"Error retrieving batch data: {e}")
            return None

    async def send_stored_file(
            self,
            client: Client,
            user_id: int,
            file_identifier: str,
            protect: bool = False,
            caption_func=None
    ) -> bool:
        """Send a stored file to user using file identifier"""
        try:
            # Get file details from database using unified lookup
            file = await self.media_repo.find_file(file_identifier)

            if not file:
                logger.warning(f"File {file_identifier} not found in database")
                return False

            caption = CaptionFormatter.format_file_caption(
                file=file,
                custom_caption=self.config.CUSTOM_FILE_CAPTION,
                batch_caption=self.config.BATCH_FILE_CAPTION,
                keep_original=self.config.KEEP_ORIGINAL_CAPTION,
                is_batch=False,
                auto_delete_minutes=int(self.config.MESSAGE_DELETE_SECONDS/60) if self.config.MESSAGE_DELETE_SECONDS > 0 else None,
                auto_delete_message=self.config.AUTO_DELETE_MESSAGE
            )

            # Use the actual file_id for sending
            sent_msg = await client.send_cached_media(
                chat_id=user_id,
                file_id=file.file_id,
                caption=caption,
                protect_content=protect,
                parse_mode=CaptionFormatter.get_parse_mode()
            )

            # Schedule auto-deletion if enabled
            if self.config.MESSAGE_DELETE_SECONDS > 0:
                asyncio.create_task(self._auto_delete_message(sent_msg, self.config.MESSAGE_DELETE_SECONDS))

            return True

        except FloodWait as e:
            await asyncio.sleep(e.value)
            return await self.send_stored_file(
                client, user_id, file_identifier, protect, caption_func
            )
        except Exception as e:
            logger.error(f"Error sending file: {e}")
            return False

    async def send_batch_files(
            self,
            client: Client,
            user_id: int,
            batch_data: List[Dict[str, Any]],
            caption_func=None
    ) -> Tuple[int, int]:
        """
        Send batch files to user
        Returns: (success_count, total_count)
        """
        success_count = 0

        for file_data in batch_data:
            # Initialize variables outside try block to avoid uninitialized variable warnings
            file_id_to_send = file_data.get("file_id", file_data.get("file_identifier"))
            caption = ""  # Default value
            
            try:
                caption = CaptionFormatter.format_file_caption(
                    file=MediaFile(  # Create temporary MediaFile object
                        file_unique_id=file_data.get('file_unique_id'),
                        file_id=file_data.get("file_id"),
                        file_ref=file_data.get("file_ref"),
                        file_name=file_data.get("title", ""),
                        file_size=file_data.get("size", 0),
                        file_type=FileType.DOCUMENT,
                        mime_type=None,
                        caption=file_data.get("caption", "")
                    ),
                    custom_caption=self.config.CUSTOM_FILE_CAPTION,
                    batch_caption=self.config.BATCH_FILE_CAPTION,
                    keep_original=self.config.KEEP_ORIGINAL_CAPTION,
                    use_original_for_batch=self.config.USE_ORIGINAL_CAPTION_FOR_BATCH,
                    is_batch=True,
                    auto_delete_minutes=int(self.config.MESSAGE_DELETE_SECONDS/60) if self.config.MESSAGE_DELETE_SECONDS > 0 else None,
                    auto_delete_message=self.config.AUTO_DELETE_MESSAGE
                )

                sent_msg = await telegram_api.call_api(
                    client.send_cached_media,
                    chat_id=user_id,
                    file_id=file_id_to_send,
                    caption=caption,
                    protect_content=file_data.get("protect", False),
                    parse_mode=CaptionFormatter.get_parse_mode()
                )

                # Schedule auto-deletion if enabled
                if self.config.MESSAGE_DELETE_SECONDS > 0:
                    asyncio.create_task(self._auto_delete_message(sent_msg, self.config.MESSAGE_DELETE_SECONDS))

                success_count += 1
                await asyncio.sleep(1)  # Avoid flooding

            except FloodWait as e:
                await asyncio.sleep(e.value)
                # Retry
                try:
                    await client.send_cached_media(
                        chat_id=user_id,
                        file_id=file_id_to_send,
                        caption=caption,
                        protect_content=file_data.get("protect", False),
                        parse_mode=CaptionFormatter.get_parse_mode()
                    )
                    success_count += 1
                except Exception:
                    continue

            except Exception as e:
                logger.error(f"Error sending batch file: {e}")
                continue

        return success_count, len(batch_data)

    async def send_channel_files(
            self,
            bot,  # Changed from client: Client to bot
            user_id: int,
            chat_id: int,
            first_msg_id: int,
            last_msg_id: int,
            protect: bool = False,
    ) -> Tuple[int, int]:
        """
        Send files directly from channel (DSTORE method)
        Returns: (success_count, total_count)
        """
        success_count = 0
        total_count = 0
        sent_messages = []  # Track sent messages for deletion

        try:
            # Use bot.iter_messages instead of client.iter_messages
            async for message in bot.iter_messages(
                    chat_id, last_msg_id, first_msg_id
            ):
                total_count += 1

                if message.media:
                    # Initialize caption with default value to avoid uninitialized variable warnings
                    caption = message.caption.html if message.caption else ""
                    
                    try:
                        # Get media object
                        media = getattr(message, message.media.value)
                        file_name = getattr(media, 'file_name', f'{message.media.value}_{media.file_unique_id}')
                        file_size = getattr(media, 'file_size', 0)
                        mime_type = getattr(media, 'mime_type', None)
                        caption_text = message.caption.html if message.caption else None

                        # Prepare caption
                        caption = CaptionFormatter.format_file_caption(
                            file=MediaFile(  # Create temporary MediaFile object
                                file_unique_id=media.file_unique_id,
                                file_id=media.file_id,
                                file_ref=None,
                                file_name=file_name,
                                file_size=file_size,
                                file_type=FileType.DOCUMENT,
                                mime_type=mime_type,
                                caption=caption_text
                            ),
                            custom_caption=self.config.CUSTOM_FILE_CAPTION,
                            batch_caption=self.config.BATCH_FILE_CAPTION,
                            keep_original=self.config.KEEP_ORIGINAL_CAPTION,
                            use_original_for_batch=self.config.USE_ORIGINAL_CAPTION_FOR_BATCH,
                            is_batch=True,
                            auto_delete_minutes=int(self.config.MESSAGE_DELETE_SECONDS/60) if self.config.MESSAGE_DELETE_SECONDS > 0 else None,
                            auto_delete_message=self.config.AUTO_DELETE_MESSAGE
                        )

                                # Copy message with flood protection
                        sent_msg = await telegram_api.call_api(
                            message.copy,
                            user_id,
                            caption=caption,
                            protect_content=protect,
                            parse_mode=CaptionFormatter.get_parse_mode()
                        )

                        # Schedule auto-deletion if enabled
                        if self.config.MESSAGE_DELETE_SECONDS > 0:
                            asyncio.create_task(self._auto_delete_message(sent_msg, self.config.MESSAGE_DELETE_SECONDS))

                        sent_messages.append(sent_msg)
                        success_count += 1

                    except FloodWait as e:
                        await asyncio.sleep(e.value)
                        await message.copy(user_id, caption=caption, protect_content=protect,parse_mode=CaptionFormatter.get_parse_mode())
                        success_count += 1
                    except Exception as e:
                        logger.error(f"Error copying message: {e}")
                        continue

                elif not message.empty:
                    # Non-media message
                    try:
                        await message.copy(user_id, protect_content=protect)
                        success_count += 1
                    except Exception:
                        continue

                await asyncio.sleep(1)  # Avoid flooding

        except Exception as e:
            logger.error(f"Error sending channel files: {e}")

        return success_count, total_count