"""
Search results builder utility for consistent search result display
"""
import random
import uuid
from typing import List, Optional, Tuple

from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup

from core.cache.config import CacheKeyGenerator, CacheTTLConfig
from core.constants import DisplayConstants, TimeConstants
from core.utils.file_emoji import get_file_emoji
from core.utils.helpers import format_file_size
from core.utils.logger import get_logger
from core.utils.pagination import PaginationBuilder

logger = get_logger(__name__)


class SearchResultsBuilder:
    """
    Shared utility for building and sending search results.
    Used by both SearchHandler and RequestHandler.
    """

    def __init__(self, cache_manager, config):
        """
        Initialize the search results builder.

        Args:
            cache_manager: Cache manager for storing search sessions
            config: Bot config with PICS, MESSAGE_DELETE_SECONDS, etc.
        """
        self.cache = cache_manager
        self.config = config

    async def send_search_results(
            self,
            message: Message,
            files: list,
            query: str,
            total: int,
            page_size: int,
            user_id: int,
            is_private: bool,
            callback_prefix: str = "search"
    ) -> Tuple[bool, Optional[Message]]:
        """
        Send search results with file buttons and pagination.

        Args:
            message: The message to reply to
            files: List of MediaFile objects
            query: Search query string
            total: Total number of results
            page_size: Number of results per page
            user_id: User ID who initiated the search
            is_private: Whether this is a private chat
            callback_prefix: Prefix for pagination callbacks

        Returns:
            Tuple of (success: bool, sent_message: Optional[Message])
        """
        try:
            # Generate unique session ID and store in cache
            session_id = uuid.uuid4().hex[:DisplayConstants.SESSION_ID_LENGTH]
            search_key = CacheKeyGenerator.search_session(user_id, session_id)

            # Store files data in cache for "Send All" functionality
            files_data = [
                {
                    'file_unique_id': f.file_unique_id,
                    'file_id': f.file_id,
                    'file_ref': f.file_ref,
                    'file_name': f.file_name,
                    'file_size': f.file_size,
                    'file_type': f.file_type.value
                }
                for f in files
            ]

            await self.cache.set(
                search_key,
                {'files': files_data, 'query': query, 'user_id': user_id},
                expire=CacheTTLConfig.SEARCH_SESSION
            )

            logger.debug(
                f"Stored search results: key={search_key}, "
                f"files={len(files_data)}, TTL={CacheTTLConfig.SEARCH_SESSION}s"
            )

            # Build buttons
            buttons = self._build_buttons(
                files, search_key, user_id, is_private, total, page_size, query, callback_prefix
            )

            # Build caption
            caption = self._build_caption(query, total, page_size)

            # Send message
            sent_msg = await self._send_message(message, caption, buttons)

            return True, sent_msg

        except Exception as e:
            logger.error(f"Error sending search results: {e}", exc_info=True)
            return False, None

    def _build_buttons(
            self,
            files: list,
            search_key: str,
            user_id: int,
            is_private: bool,
            total: int,
            page_size: int,
            query: str,
            callback_prefix: str
    ) -> List[List[InlineKeyboardButton]]:
        """Build all buttons for search results."""
        buttons = []

        # Add "Send All Files" button
        if files:
            send_all_callback = f"sendall#{search_key}" if is_private else f"sendall#{search_key}#{user_id}"
            buttons.append([
                InlineKeyboardButton(
                    f"📤 Send All Files ({len(files)})",
                    callback_data=send_all_callback
                )
            ])

        # Add individual file buttons
        for file in files:
            file_identifier = file.file_unique_id or file.file_ref
            callback_data = f"file#{file_identifier}" if is_private else f"file#{file_identifier}#{user_id}"

            file_emoji = get_file_emoji(file.file_type, file.file_name, file.mime_type)
            file_name_display = file.file_name[:DisplayConstants.FILE_NAME_DISPLAY_LENGTH] + ('...' if len(file.file_name) > DisplayConstants.FILE_NAME_DISPLAY_LENGTH else '')

            buttons.append([
                InlineKeyboardButton(
                    f"{format_file_size(file.file_size)} {file_emoji} {file_name_display}",
                    callback_data=callback_data
                )
            ])

        # Add pagination buttons if needed
        if total > page_size:
            pagination = PaginationBuilder(
                total_items=total,
                page_size=page_size,
                current_offset=0,
                query=query,
                user_id=user_id,
                callback_prefix=callback_prefix
            )
            buttons.extend(pagination.build_pagination_buttons())

        return buttons

    def _build_caption(self, query: str, total: int, page_size: int) -> str:
        """Build caption for search results."""
        total_pages = (total + page_size - 1) // page_size

        caption = (
            f"🔍 <b>Search Results for:</b> {query}\n"
            f"📁 Found {total} files\n"
            f"📊 Page 1 of {total_pages}"
        )

        delete_time = getattr(self.config, 'MESSAGE_DELETE_SECONDS', 0)
        if delete_time > 0:
            delete_minutes = delete_time // TimeConstants.SECONDS_PER_MINUTE
            caption += f"\n⏱ <b>Note:</b> Results will be auto-deleted after {delete_minutes} minutes"

        return caption

    async def _send_message(
            self,
            message: Message,
            caption: str,
            buttons: List[List[InlineKeyboardButton]]
    ) -> Message:
        """Send the search results message."""
        reply_markup = InlineKeyboardMarkup(buttons)
        pics = getattr(self.config, 'PICS', None)

        if pics:
            return await message.reply_photo(
                photo=random.choice(pics),
                caption=caption,
                reply_markup=reply_markup
            )
        else:
            return await message.reply_text(
                caption,
                reply_markup=reply_markup
            )
