"""
Search results builder utility for consistent search result display
"""
import random
from typing import List, Optional, Tuple

from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup

from core.cache.config import SearchSessionCache
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
        self.session_cache = SearchSessionCache(cache_manager)
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
            # Cache files and get search key
            search_key = await self.cache_files(files, query, user_id)

            # Build buttons
            buttons = self.build_buttons(
                files, search_key, user_id, is_private, total, page_size, query, callback_prefix
            )

            # Build caption
            caption = self.build_caption(query, total, page_size)

            # Send message
            sent_msg = await self._send_message(message, caption, buttons)

            return True, sent_msg

        except Exception as e:
            logger.error(f"Error sending search results: {e}", exc_info=True)
            return False, None

    async def cache_files(
            self,
            files: list,
            query: str,
            user_id: int
    ) -> str:
        """
        Cache files data for "Send All" functionality.
        Delegates to SearchSessionCache.

        Args:
            files: List of MediaFile objects
            query: Search query string
            user_id: User ID who initiated the search

        Returns:
            The generated search_key for retrieving cached files
        """
        return await self.session_cache.store_files(files, query, user_id)

    def build_buttons(
            self,
            files: list,
            search_key: str,
            user_id: int,
            is_private: bool,
            total: int,
            page_size: int,
            query: str,
            callback_prefix: str,
            current_offset: int = 0
    ) -> List[List[InlineKeyboardButton]]:
        """
        Build all buttons for search results.

        Args:
            files: List of MediaFile objects
            search_key: Cache key for "Send All" functionality
            user_id: User ID who initiated the search
            is_private: Whether this is a private chat
            total: Total number of results
            page_size: Number of results per page
            query: Search query string
            callback_prefix: Prefix for pagination callbacks
            current_offset: Current pagination offset (default 0)

        Returns:
            List of button rows
        """
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
                current_offset=current_offset,
                query=query,
                user_id=user_id,
                callback_prefix=callback_prefix
            )
            buttons.extend(pagination.build_pagination_buttons())

        return buttons

    def build_caption(
            self,
            query: str,
            total: int,
            page_size: int,
            current_page: int = 1,
            include_delete_notice: bool = True
    ) -> str:
        """
        Build caption for search results.

        Args:
            query: Search query string
            total: Total number of results
            page_size: Number of results per page
            current_page: Current page number (default 1)
            include_delete_notice: Whether to include auto-delete notice (default True)

        Returns:
            Formatted caption string
        """
        total_pages = (total + page_size - 1) // page_size

        caption = (
            f"🔍 <b>Search Results for:</b> {query}\n"
            f"📁 Found {total} files\n"
            f"📊 Page {current_page} of {total_pages}"
        )

        if include_delete_notice:
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
