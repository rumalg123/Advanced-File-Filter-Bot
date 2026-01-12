from pyrogram import Client, enums
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup

from core.cache.config import SearchSessionCache
from core.utils.logger import get_logger
from core.utils.messages import ErrorMessages
from core.utils.pagination import PaginationHelper
from core.utils.search_results import SearchResultsBuilder
from handlers.commands_handlers.base import BaseCommandHandler

logger = get_logger(__name__)


class PaginationCallbackHandler(BaseCommandHandler):
    """Handler for search pagination callbacks"""

    def __init__(self, bot):
        super().__init__(bot)
        self.session_cache = SearchSessionCache(bot.cache)
        self.results_builder = SearchResultsBuilder(bot.cache, bot.config)

    async def handle_search_pagination(self, client: Client, query: CallbackQuery):
        """Handle search pagination callbacks"""
        callback_user_id = query.from_user.id

        # Parse callback data using helper
        parsed_data = PaginationHelper.parse_callback_data(query.data)

        if not parsed_data:
            return await query.answer(ErrorMessages.INVALID_DATA, show_alert=True)

        # Extract parsed values (action is in callback data but offset is pre-calculated by PaginationBuilder)
        search_query = parsed_data['query']
        current_offset = parsed_data['offset']
        total = parsed_data['total']
        original_user_id = parsed_data['user_id']

        # Check ownership
        if original_user_id and callback_user_id != original_user_id:
            await query.answer(ErrorMessages.NOT_YOUR_MESSAGE, show_alert=True)
            return

        page_size = self.bot.config.MAX_BTN_SIZE
        user_id = callback_user_id

        # Search for files
        files, next_offset, total, has_access = await self.bot.file_service.search_files_with_access_check(
            user_id=user_id,
            query=search_query,
            chat_id=user_id,
            offset=current_offset,
            limit=page_size
        )

        if not has_access:
            return await query.answer(ErrorMessages.ACCESS_DENIED, show_alert=True)

        if not files:
            return await query.answer("No more results", show_alert=True)

        # Cache files using SearchSessionCache
        search_key = await self.session_cache.store_files(files, search_query, user_id)

        # Determine if this is a private chat
        is_private = query.message.chat.type == enums.ChatType.PRIVATE

        # Calculate current page for caption
        current_page = (current_offset // page_size) + 1

        # Build buttons using SearchResultsBuilder
        buttons = self.results_builder.build_buttons(
            files=files,
            search_key=search_key,
            user_id=callback_user_id,
            is_private=is_private,
            total=total,
            page_size=page_size,
            query=search_query,
            callback_prefix="search",
            current_offset=current_offset
        )

        # Build caption using SearchResultsBuilder (without delete notice for pagination updates)
        caption = self.results_builder.build_caption(
            query=search_query,
            total=total,
            page_size=page_size,
            current_page=current_page,
            include_delete_notice=False
        )

        # Update message
        await query.message.edit_text(
            caption,
            reply_markup=InlineKeyboardMarkup(buttons)
        )

        await query.answer()
