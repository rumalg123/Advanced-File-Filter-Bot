import uuid

from pyrogram import Client
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from core.cache.config import CacheKeyGenerator, CacheTTLConfig
from core.utils.button_builder import ButtonBuilder
from core.utils.caption import CaptionFormatter
from core.utils.error_formatter import ErrorMessageFormatter
from core.utils.logger import get_logger
from core.utils.pagination import PaginationBuilder, PaginationHelper
from handlers.commands_handlers.base import BaseCommandHandler

logger = get_logger(__name__)


class PaginationCallbackHandler(BaseCommandHandler):
    """Handler for search pagination callbacks"""

    async def handle_search_pagination(self, client: Client, query: CallbackQuery):
        """Handle search pagination callbacks"""
        callback_user_id = query.from_user.id

        # Parse callback data using helper
        parsed_data = PaginationHelper.parse_callback_data(query.data)

        if not parsed_data:
            return await query.answer("Invalid data", show_alert=True)

        # Extract parsed values (action is in callback data but offset is pre-calculated by PaginationBuilder)
        search_query = parsed_data['query']
        current_offset = parsed_data['offset']
        total = parsed_data['total']
        original_user_id = parsed_data['user_id']

        # Check ownership
        if original_user_id and callback_user_id != original_user_id:
            await query.answer(ErrorMessageFormatter.format_access_denied("You cannot interact with this message", plain_text=True), show_alert=True)
            return

        page_size = self.bot.config.MAX_BTN_SIZE
        user_id = callback_user_id

        new_offset = current_offset
        # Search for files
        files, next_offset, total, has_access, access_reason = await self.bot.file_service.search_files_with_access_check(
            user_id=user_id,
            query=search_query,
            chat_id=user_id,
            offset=new_offset,
            limit=page_size
        )

        if not has_access:
            # Check if it's daily limit or ban
            if access_reason and "Daily limit reached" in access_reason:
                # Show proper daily limit message
                user = await self.bot.user_repo.get_user(user_id)
                if user:
                    daily_limit = self.bot.user_repo.daily_limit
                    message = f"⚠️ Daily limit reached ({user.daily_retrieval_count}/{daily_limit}). Upgrade to premium for unlimited access!"
                else:
                    message = "⚠️ Daily limit reached. Upgrade to premium for unlimited access!"
            else:
                # Ban or other access denied reason
                message = ErrorMessageFormatter.format_access_denied(access_reason, plain_text=True) if access_reason else ErrorMessageFormatter.format_access_denied(plain_text=True)
            return await query.answer(message, show_alert=True)

        if not files:
            # If this is a new search (offset 0) and no results, show proper message
            if new_offset == 0:
                # This might be from a "Did you mean?" suggestion that still has no results
                # Show a helpful message (plain text for query.answer with show_alert)
                await query.answer(
                    f"⚠️ No results found for '{search_query}'. Try a different search term.",
                    show_alert=True
                )
                return
            else:
                return await query.answer("No more results", show_alert=True)

        # Generate a unique key for this search result set
        session_id = uuid.uuid4().hex[:8]
        search_key = CacheKeyGenerator.search_session(user_id, session_id)

        # Store file IDs in cache for "Send All" functionality - optimized
        # Use list comprehension for better memory efficiency
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

        await self.bot.cache.set(
            search_key,
            {'files': files_data, 'query': search_query},
            expire=CacheTTLConfig.SEARCH_SESSION  # 1 hour expiry
        )

        # Build response with new pagination builder
        pagination = PaginationBuilder(
            total_items=total,
            page_size=page_size,
            current_offset=new_offset,
            query=search_query,
            user_id=callback_user_id,
            callback_prefix="search"
        )

        # Build file buttons
        buttons = []

        # Add "Send All Files" button as the first button
        if files:
            send_all_button = ButtonBuilder.send_all_button(
                file_count=len(files),
                search_key=search_key,
                user_id=callback_user_id,
                is_private=True  # Pagination is typically in private chats
            )
            buttons.append([send_all_button])

        # Add individual file buttons
        file_buttons = ButtonBuilder.file_buttons_row(
            files=files,
            user_id=callback_user_id,
            is_private=True  # Pagination is typically in private chats
        )
        buttons.extend(file_buttons)

        # Add smart pagination buttons
        pagination_buttons = pagination.build_pagination_buttons()
        buttons.extend(pagination_buttons)

        # Update message using centralized caption formatter
        caption = CaptionFormatter.format_search_results_caption(
            query=search_query,
            total=total,
            pagination=pagination,
            delete_time=0,  # Pagination updates don't show delete time
            is_private=True  # Pagination is typically in private chats
        )
        
        await query.message.edit_text(
            caption,
            reply_markup=InlineKeyboardMarkup(buttons)
        )

        await query.answer()