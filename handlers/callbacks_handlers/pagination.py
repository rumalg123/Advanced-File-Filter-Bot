import uuid

from pyrogram import Client
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from core.cache.config import CacheTTLConfig
from core.utils.file_emoji import get_file_emoji
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

        # Extract parsed values
        action = parsed_data['action']
        search_query = parsed_data['query']
        current_offset = parsed_data['offset']
        total = parsed_data['total']
        original_user_id = parsed_data['user_id']

        # Check ownership
        if original_user_id and callback_user_id != original_user_id:
            await query.answer("❌ You cannot interact with this message!", show_alert=True)
            return

        page_size = self.bot.config.MAX_BTN_SIZE
        user_id = callback_user_id

        new_offset = current_offset
        # Search for files
        files, next_offset, total, has_access = await self.bot.file_service.search_files_with_access_check(
            user_id=user_id,
            query=search_query,
            chat_id=user_id,
            offset=new_offset,
            limit=page_size
        )

        if not has_access:
            return await query.answer("❌ Access denied", show_alert=True)

        if not files:
            return await query.answer("No more results", show_alert=True)

        # Generate a unique key for this search result set
        search_key = f"search_results_{user_id}_{uuid.uuid4().hex[:8]}"

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

        ttl = CacheTTLConfig()
        await self.bot.cache.set(
            search_key,
            {'files': files_data, 'query': search_query},
            expire=ttl.SEARCH_SESSION  # 1 hour expiry
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
            buttons.append([
                InlineKeyboardButton(
                    f"📤 Send All Files ({len(files)})",
                    callback_data=f"sendall#{search_key}"
                )
            ])

        for file in files:
            file_identifier = file.file_unique_id if file.file_unique_id else file.file_id
            file_emoji = get_file_emoji(file.file_type, file.file_name, file.mime_type)
            file_button = InlineKeyboardButton(
                f"{file_emoji} {file.file_name[:50]}{'...' if len(file.file_name) > 50 else ''}",
                callback_data=f"file#{file_identifier}#{callback_user_id}"
            )
            buttons.append([file_button])

        # Add smart pagination buttons
        pagination_buttons = pagination.build_pagination_buttons()
        buttons.extend(pagination_buttons)

        # Update message
        await query.message.edit_text(
            f"🔍 <b>Search Results for:</b> {search_query}\n"
            f"📁 Found {total} files\n"
            f"📊 Page {pagination.current_page} of {pagination.total_pages}",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

        await query.answer()