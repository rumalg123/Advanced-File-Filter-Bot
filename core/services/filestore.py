import asyncio
from copy import deepcopy
import tempfile
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

from config.settings import settings

from core.utils.service_tasks import ServiceTasks
from core.cache.config import CacheTTLConfig
from core.cache.redis_cache import CacheManager
from core.utils.caption import CaptionFormatter
from core.utils.error_formatter import ErrorMessageFormatter
from core.utils.validators import normalize_filename_for_search
from core.utils.logger import get_logger
from core.utils.link_parser import TelegramLinkParser, ParsedTelegramLink
from core.utils.telegram_api import telegram_api
from core.utils.helpers import extract_file_ref, parse_media_metadata
from core.utils.media_factory import MediaFileFactory
from core.concurrency import semaphore_manager
from repositories.media import MediaRepository, MediaFile, FileType
from repositories.batch_link import BatchLinkRepository, BatchLink

logger = get_logger(__name__)


class BatchSourceUnavailableError(RuntimeError):
    """The source range could not be completely verified for quota admission."""


class FileStoreService:
    """Service for managing file store operations"""

    def __init__(
            self,
            media_repo: MediaRepository,
            cache_manager: CacheManager,
            config: Any,
            batch_link_repo: Optional[BatchLinkRepository] = None,
            task_manager=None,
            channel_repo=None,

    ):
        self.tasks = ServiceTasks(task_manager)
        self.media_repo = media_repo
        self.cache = cache_manager
        self.config = config
        self.batch_link_repo = batch_link_repo
        self.channel_repo = channel_repo
        self.batch_cache = {}  # In-memory cache for batch files
        self.batch_cache_ttl = CacheTTLConfig.SEARCH_SESSION   # 1 hour
        self.max_batch_cache_size = 100
        self.batch_cache_access_time = {}
        self.batch_cache_created_at = {}
        self._batch_cache_lock = asyncio.Lock()  # Protect concurrent cache access

    async def _auto_delete_message(self, message: Message, delay: int):
        """Auto-delete message after delay"""
        if delay <= 0:
            return
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

    def decode_file_identifier(self, encoded: str) -> Tuple[Optional[str], bool]:
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

    async def _cleanup_batch_cache(self):
        """Remove oldest entries if cache is too large"""
        async with self._batch_cache_lock:
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
                    self.batch_cache_created_at.pop(key, None)



    async def create_file_link(
            self,
            client: Client,
            message: Message,
            protect: bool = False
    ) -> Optional[str]:
        """Create shareable link for a file using file_ref"""
        if not message.reply_to_message:
            return None

        # Extract media using unified extractor
        from core.utils.media_extractor import extract_media_by_type
        
        file_type = message.reply_to_message.media
        if file_type not in [enums.MessageMediaType.VIDEO, enums.MessageMediaType.AUDIO,
                             enums.MessageMediaType.DOCUMENT]:
            return None

        # Get media object
        media = extract_media_by_type(message.reply_to_message, file_type)
        if not media:
            return None
        
        media_file_unique_id = media.file_unique_id
        #logger.info(f"media_file_unique_id is {media_file_unique_id}")

        # Find file in database to get file
        file = await self.media_repo.find_file(media_file_unique_id)

        if not file:
            # File not in database, create and save it using MediaFileFactory
            media_file = MediaFileFactory.from_pyrogram_media(
                media=media,
                message=message.reply_to_message if message.reply_to_message else message,
                file_type=file_type,
                file_unique_id=media_file_unique_id
            )

            # Save to database - now returns existing file if duplicate
            success, status, existing_file = await self.media_repo.save_media(media_file)

            if status == 0 and existing_file:
                # Duplicate found, use the existing file
                file = existing_file
                identifier = file.file_ref or file.file_unique_id
                logger.info(f"Using existing duplicate file with ref: {identifier}")
            elif success:
                # New file saved successfully
                file = media_file
                identifier = file.file_ref or file.file_unique_id
                logger.info(f"Successfully saved new file to database with ref: {identifier}")
                feature_service = getattr(self, 'feature_service', None)
                if feature_service:
                    if hasattr(feature_service, "persist_new_media"):
                        await feature_service.persist_new_media(media_file)
                    else:
                        feature_service.schedule_new_media(media_file)
            else:
                # Error saving file and no duplicate found
                logger.error(f"Failed to save file to database: {media_file_unique_id}")
                return None
        else:
            # Use file_ref from existing database entry
            identifier = file.file_ref or file.file_unique_id
            logger.info(f"Using existing file_ref from database: {identifier}")

        # Generate link
        encoded = self.encode_file_identifier(identifier, protect)
        me = await telegram_api.call_api(client.get_me)
        bot_username = me.username

        # Ensure the encoded string isn't too long for Telegram
        if len(encoded) > 64:
            logger.error(f"Encoded identifier too long: {len(encoded)} characters")
            # Try using a shorter identifier
            short_ref = hashlib.md5(identifier.encode()).hexdigest()[:16]

            # Update the file with short ref
            if not file:
                logger.error(f"Cannot persist shortened file ref for {media_file_unique_id}")
                return None

            updated = await self.media_repo.update(file.file_id, {'file_ref': short_ref})
            if not updated:
                logger.error(f"Failed to persist shortened file ref for {media_file_unique_id}")
                return None

            encoded = self.encode_file_identifier(short_ref, protect)
            identifier = short_ref
            logger.info(f"Using shortened ref: {short_ref}")

        link = f"https://t.me/{bot_username}?start={encoded}"
        logger.info(f"Generated link: {link} for file_ref: {identifier}")
        return link

    async def _can_create_source_batch(self, client: Client, user_id: int, chat_id: int) -> bool:
        """Require an authorized creator for the source channel."""
        admins = getattr(self.config, 'ADMINS', []) or []
        if user_id not in admins:
            if not user_id or not getattr(self.config, 'PUBLIC_FILE_STORE', False):
                return False
            try:
                member = await telegram_api.call_api(client.get_chat_member, chat_id, user_id, chat_id=chat_id)
                present = member.status in (enums.ChatMemberStatus.OWNER, enums.ChatMemberStatus.ADMINISTRATOR,
                                            enums.ChatMemberStatus.MEMBER)
                if member.status == enums.ChatMemberStatus.RESTRICTED:
                    present = member.is_member is True
                if not present:
                    return False
            except Exception as e:
                logger.warning("Cannot verify file-store creator in source %s: %s", chat_id, e)
                return False
        return True

    async def can_read_legacy_batch(self, client: Client, user_id: int, chat_id: int) -> bool:
        """Unsigned legacy ranges are restricted to explicitly configured media sources."""
        if user_id in (getattr(self.config, 'ADMINS', []) or []):
            return True
        configured = getattr(self.config, 'CHANNELS', []) or []
        if isinstance(configured, str):
            configured = configured.replace(',', ' ').split()
        targets = list(configured)
        filestore = getattr(self.config, 'FILE_STORE_CHANNEL', '')
        if filestore:
            targets.extend(str(filestore).replace(',', ' ').split())
        for target in targets:
            try:
                resolved = int(target)
            except (ValueError, TypeError):
                try:
                    chat = await telegram_api.call_api(client.get_chat, target, chat_id=None)
                    resolved = chat.id
                except Exception as e:
                    logger.warning("Cannot resolve configured legacy batch source %s: %s", target, e)
                    continue
            if resolved and resolved == chat_id:
                return True
        if self.channel_repo is not None:
            channel = await self.channel_repo.find_by_id(chat_id, use_cache=False)
            return bool(channel and channel.enabled is True)
        return False

    async def create_batch_link(
            self,
            client: Client,
            first_msg_link: str,
            last_msg_link: str,
            protect: bool = False,
            created_by: int = 0,
    ) -> Optional[str]:
        """Create batch link for multiple files"""
        first = TelegramLinkParser.parse_link(first_msg_link)
        last = TelegramLinkParser.parse_link(last_msg_link)
        if not first or not last or not TelegramLinkParser.is_valid_batch_range(
            first.message_id, last.message_id, settings.processing.max_batch_messages
        ):
            logger.warning("Invalid batch message range")
            return None

        # Resolve both formats before comparing, preserving mixed username/ID links.
        chat_ids = []
        for parsed in (first, last):
            chat_id = parsed.chat_id
            if chat_id is None:
                try:
                    chat = await telegram_api.call_api(
                        client.get_chat, parsed.chat_identifier, chat_id=None
                    )
                    chat_id = chat.id
                except Exception:
                    logger.warning("Unable to resolve batch source", exc_info=True)
                    return None
            chat_ids.append(chat_id)
        if chat_ids[0] != chat_ids[1]:
            logger.warning("Batch links belong to different chats")
            return None
        f_chat_id = chat_ids[0]
        f_msg_id, l_msg_id = first.message_id, last.message_id

        if not self.batch_link_repo:
            logger.error("BatchLinkRepository not initialized - cannot create a batch link")
            return None
        if not await self._can_create_source_batch(client, created_by, f_chat_id):
            return None
        try:
            source_message = await telegram_api.call_api(client.get_messages, f_chat_id, f_msg_id, chat_id=f_chat_id)
            if source_message is None or source_message.empty:
                return None
        except Exception as e:
            logger.warning("Cannot read batch source %s: %s", f_chat_id, e)
            return None
        batch_id = f"BL-{uuid.uuid4().hex}"
        batch = BatchLink(id=batch_id, source_chat_id=f_chat_id,
                          from_msg_id=f_msg_id, to_msg_id=l_msg_id,
                          protected=protect, premium_only=False, created_by=created_by)
        if not await self.batch_link_repo.create_batch_link(batch):
            return None
        me = await telegram_api.call_api(client.get_me)
        return f"https://t.me/{me.username}?start=DSTORE-{batch_id}"

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
            logger.error("BatchLinkRepository not initialized - cannot create a premium batch link")
            return None
        
        # Use robust link parser
        parsed_links = TelegramLinkParser.parse_link_pair(first_msg_link, last_msg_link,
            max_messages=settings.processing.max_batch_messages, require_same_chat=False)
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
        
        last_chat_id = last_parsed.chat_id
        if last_chat_id is None:
            if last_parsed.chat_identifier == first_parsed.chat_identifier:
                last_chat_id = chat_id
            else:
                try:
                    last_chat_id = (await telegram_api.call_api(client.get_chat, last_parsed.chat_identifier, chat_id=None)).id
                except Exception as e:
                    logger.error("Error resolving last batch source %s: %s", last_parsed.chat_identifier, e)
                    return None
        if last_chat_id != chat_id:
            logger.warning("Premium batch links belong to different chats")
            return None

        if not await self._can_create_source_batch(client, created_by, chat_id):
            return None

        # Validate bot has access to source channel
        try:
            # Check if bot can access the first message (quick validation)
            source_message = await telegram_api.call_api(
                client.get_messages,
                chat_id,
                first_parsed.message_id,
                chat_id=chat_id
            )
            if source_message is None or source_message.empty:
                return None
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
                me = await telegram_api.call_api(client.get_me)
                bot_username = me.username
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
        if user_id in (getattr(self.config, 'ADMINS', []) or []):
            logger.info("Privileged batch access granted for user %s", user_id)
            return True, ""

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
                return False, ErrorMessageFormatter.format_error("Premium features are currently disabled. This batch link requires premium features to be enabled.")

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
                return False, ErrorMessageFormatter.format_access_denied("This batch link requires premium membership. Upgrade to access premium-only content!")
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
                return False, ErrorMessageFormatter.format_access_denied("Premium membership required. Upgrade to access this content!")
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

    @staticmethod
    def _valid_batch_metadata(data) -> bool:
        if not isinstance(data, list) or len(data) > settings.processing.max_batch_messages:
            return False
        for row in data:
            if not isinstance(row, dict):
                return False
            identifier = row.get('file_id') or row.get('file_identifier')
            if not isinstance(identifier, str) or not identifier.strip():
                return False
            if 'protect' in row and type(row['protect']) is not bool:
                return False
            size = row.get('size')
            if size is not None and (type(size) is not int or size < 0):
                return False
            if any(row.get(field) is not None and not isinstance(row[field], str)
                   for field in ('title', 'caption', 'file_unique_id', 'file_ref')):
                return False
        return True

    async def get_batch_data(
            self,
            client: Client,
            batch_identifier: str
    ) -> Optional[List[Dict[str, Any]]]:
        """Load validated JSON metadata with bounded lifetime and owned temp files."""
        now = time.monotonic()
        cached = self.batch_cache.get(batch_identifier)
        created = self.batch_cache_created_at.get(batch_identifier)
        if (cached is not None and created is not None and now - created < self.batch_cache_ttl
                and self._valid_batch_metadata(cached)):
            self.batch_cache_access_time[batch_identifier] = now
            return deepcopy(cached)
        self.batch_cache.pop(batch_identifier, None)
        self.batch_cache_access_time.pop(batch_identifier, None)
        self.batch_cache_created_at.pop(batch_identifier, None)
        file = await self.media_repo.find_file(batch_identifier)
        if not file:
            return None
        name = (getattr(file, 'file_name', '') or '').lower()
        mime = (getattr(file, 'mime_type', '') or '').lower()
        if not name.endswith('.json') and mime not in ('application/json', 'text/json'):
            logger.warning("Batch metadata source is not a JSON document")
            return None
        download_path = file_path = None
        try:
            descriptor, download_path = tempfile.mkstemp(prefix='affb-batch-', suffix='.json')
            os.close(descriptor)
            async with semaphore_manager.acquire('file_processing', f'download_{batch_identifier}'):
                file_path = await telegram_api.call_api(client.download_media, file.file_id, file_name=download_path)
                if not file_path:
                    return None
                with open(file_path, 'r', encoding='utf-8') as stream:
                    batch_data = json.load(stream)
            if not self._valid_batch_metadata(batch_data):
                logger.warning("Rejected invalid batch metadata for %s", batch_identifier)
                return None
            if batch_data:
                self.batch_cache[batch_identifier] = deepcopy(batch_data)
                self.batch_cache_created_at[batch_identifier] = time.monotonic()
                self.batch_cache_access_time[batch_identifier] = time.monotonic()
                await self._cleanup_batch_cache()
            return batch_data
        except Exception as e:
            logger.error(f"Error retrieving batch data: {e}")
            return None
        finally:
            for path in {file_path, download_path} - {None}:
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass
                except OSError as e:
                    logger.warning("Could not remove batch temporary file: %s", e)

    async def send_stored_file(
            self,
            client: Client,
            user_id: int,
            file_identifier: str,
            protect: bool = False,
            caption_func=None,
            delivery_progress=None,
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

            # Use telegram_api for concurrency control
            sent_msg = await telegram_api.call_api(
                client.send_cached_media,
                user_id,
                file.file_id,
                caption=caption,
                protect_content=protect,
                parse_mode=CaptionFormatter.get_parse_mode(),
                chat_id=user_id
            )

            # Schedule auto-deletion if enabled
            if self.config.MESSAGE_DELETE_SECONDS > 0:
                self.tasks.create(self._auto_delete_message(sent_msg, self.config.MESSAGE_DELETE_SECONDS), auto_delete=True)

            return True
        except Exception as e:
            logger.error(f"Error sending file: {e}")
            return False

    async def send_batch_files(
            self,
            client: Client,
            user_id: int,
            batch_data: List[Dict[str, Any]],
            caption_func=None,
            delivery_progress=None,
            access_check=None,
    ) -> Tuple[int, int]:
        """
        Send batch files to user
        Returns: (success_count, total_count)
        """
        success_count = 0

        for file_data in batch_data:
            if access_check is not None and not await access_check():
                break
            # Initialize variables outside try block to avoid uninitialized variable warnings
            file_id_to_send = file_data.get("file_id") or file_data.get("file_identifier")
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

                # telegram_api.call_api already uses semaphore_manager internally
                if delivery_progress is not None:
                    delivery_progress.attempted += 1
                sent_msg = await telegram_api.call_api(
                    client.send_cached_media,
                    user_id,
                    file_id_to_send,
                    caption=caption,
                    protect_content=file_data.get("protect", False),
                    parse_mode=CaptionFormatter.get_parse_mode(),
                    chat_id=user_id
                )

                if delivery_progress is not None:
                    delivery_progress.confirmed += 1

                # Schedule auto-deletion if enabled
                if self.config.MESSAGE_DELETE_SECONDS > 0:
                    self.tasks.create(self._auto_delete_message(sent_msg, self.config.MESSAGE_DELETE_SECONDS), auto_delete=True)

                success_count += 1
                await asyncio.sleep(1)  # Avoid flooding

            except Exception as e:
                # telegram_api.call_api already handles FloodWait with retries
                logger.error(f"Error sending batch file: {e}")
                continue

        return success_count, len(batch_data)

    async def count_channel_media_items(
            self,
            bot,
            chat_id: int,
            first_msg_id: int,
            last_msg_id: int,
            max_items: Optional[int] = None,
    ) -> int:
        """Count media messages in a channel range for quota reservation."""
        media_count = 0

        try:
            async for message in bot.iter_messages(
                    chat_id, last_msg_id, first_msg_id
            ):
                if message.media:
                    media_count += 1
                    if max_items is not None and media_count >= max_items:
                        return media_count
        except Exception as e:
            logger.error(f"Error counting channel media items: {e}")
            raise BatchSourceUnavailableError("Source media count is unavailable") from e

        return media_count

    async def send_channel_files(
            self,
            bot,  # Changed from client: Client to bot
            user_id: int,
            chat_id: int,
            first_msg_id: int,
            last_msg_id: int,
            protect: bool = False,
            delivery_progress=None,
            access_check=None,
            media_limit: Optional[int] = None,
    ) -> Tuple[int, int, int]:
        """
        Send files directly from channel (DSTORE method)
        Returns: (success_count, total_count, media_success_count)
        """
        success_count = 0
        total_count = 0
        media_success_count = 0
        media_attempt_count = 0
        sent_messages = []  # Track sent messages for deletion

        try:
            # Use bot.iter_messages instead of client.iter_messages
            async for message in bot.iter_messages(
                    chat_id, last_msg_id, first_msg_id
            ):
                if access_check is not None and not await access_check():
                    return success_count, last_msg_id - first_msg_id + 1, media_success_count
                total_count += 1

                if message.media:
                    if media_limit is not None and media_attempt_count >= media_limit:
                        continue
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

                        # telegram_api.call_api already uses semaphore_manager internally
                        media_attempt_count += 1
                        if delivery_progress is not None:
                            delivery_progress.attempted += 1
                        sent_msg = await telegram_api.call_api(
                            message.copy,
                            user_id,
                            caption=caption,
                            protect_content=protect,
                            parse_mode=CaptionFormatter.get_parse_mode()
                        )

                        if delivery_progress is not None:
                            delivery_progress.confirmed += 1

                        # Schedule auto-deletion if enabled
                        if self.config.MESSAGE_DELETE_SECONDS > 0:
                            self.tasks.create(self._auto_delete_message(sent_msg, self.config.MESSAGE_DELETE_SECONDS), auto_delete=True)

                        sent_messages.append(sent_msg)
                        success_count += 1
                        media_success_count += 1

                    except Exception as e:
                        # telegram_api.call_api already handles FloodWait with retries
                        logger.error(f"Error copying message: {e}")
                        continue

                elif not message.empty:
                    # Non-media message - telegram_api.call_api handles concurrency
                    try:
                        await telegram_api.call_api(
                            message.copy,
                            user_id,
                            protect_content=protect
                        )
                        success_count += 1
                    except Exception as e:
                        logger.error(f"Error sending non-media message: {e}")
                        continue

                await asyncio.sleep(1)  # Avoid flooding

        except Exception as e:
            logger.error(f"Error sending channel files: {e}")

        return success_count, total_count, media_success_count
