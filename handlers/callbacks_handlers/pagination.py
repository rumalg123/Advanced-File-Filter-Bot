import logging
import uuid

from pyrogram import Client
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from handlers.commands_handlers.base import BaseCommandHandler

from core.utils.logger import get_logger
logger = get_logger(__name__)


class PaginationCallbackHandler(BaseCommandHandler):
    """Handler for search pagination callbacks"""

    async def handle_search_pagination(self, client: Client, query: CallbackQuery):
        """Handle search pagination callbacks"""
        callback_user_id = query.from_user.id

        # Parse callback data: search#action#query#offset#total#user_id
        parts = query.data.split("#")
        if len(parts) < 6:
            # Check for old format
            if len(parts) < 5:
                return await query.answer("Invalid data", show_alert=True)
            # Old format without user_id
            _, action, search_query, current_offset, total = parts
            original_user_id = None
        else:
            _, action, search_query, current_offset, total, original_user_id = parts
            original_user_id = int(original_user_id)

        # Check ownership
        if original_user_id and callback_user_id != original_user_id:
            await query.answer("❌ You cannot interact with this message!", show_alert=True)
            return

        current_offset = int(current_offset)
        total = int(total)
        page_size = self.bot.config.MAX_BTN_SIZE
        user_id = callback_user_id

        # Calculate new offset based on action
        if action == "first":
            new_offset = 0
        elif action == "prev":
            new_offset = max(0, current_offset - page_size)
        elif action == "next":
            new_offset = current_offset + page_size
        elif action == "last":
            new_offset = ((total - 1) // page_size) * page_size
        else:
            return await query.answer("Invalid action", show_alert=True)

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

        # Store file IDs in cache for "Send All" functionality
        files_data = []
        for f in files:
            files_data.append({
                'file_unique_id': f.file_unique_id,
                'file_id': f.file_id,
                'file_ref': f.file_ref,
                'file_name': f.file_name,
                'file_size': f.file_size,
                'file_type': f.file_type.value
            })

        await self.bot.cache.set(
            search_key,
            {'files': files_data, 'query': search_query},
            expire=self.bot.cache.ttl_config.SEARCH_SESSION  # 1 hour expiry
        )

        # Build response
        current_page = (new_offset // page_size) + 1
        total_pages = ((total - 1) // page_size) + 1

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
            file_button = InlineKeyboardButton(
                f"📁 {file.file_name[:50]}{'...' if len(file.file_name) > 50 else ''}",
                callback_data=f"file#{file_identifier}"
            )
            buttons.append([file_button])

        # Add pagination buttons
        nav_buttons = []

        # First and Previous buttons
        if new_offset > 0:
            nav_buttons.append(
                InlineKeyboardButton("⏮ First",
                                     callback_data=f"search#first#{search_query}#0#{total}#{callback_user_id}")
            )
            nav_buttons.append(
                InlineKeyboardButton("◀️ Prev",
                                     callback_data=f"search#prev#{search_query}#{new_offset}#{total}#{callback_user_id}")
            )
        else:
            nav_buttons.append(InlineKeyboardButton("⏮", callback_data=f"noop#{callback_user_id}"))
            nav_buttons.append(InlineKeyboardButton("◀️", callback_data=f"noop#{callback_user_id}"))

        # Current page indicator
        nav_buttons.append(
            InlineKeyboardButton(f"📄 {current_page}/{total_pages}", callback_data=f"noop#{callback_user_id}")
        )

        # Next and Last buttons
        if new_offset + page_size < total:
            nav_buttons.append(
                InlineKeyboardButton("Next ▶️", callback_data=f"search#next#{search_query}#{new_offset}#{total}#{callback_user_id}")
            )
            nav_buttons.append(
                InlineKeyboardButton("Last ⏭", callback_data=f"search#last#{search_query}#{new_offset}#{total}#{callback_user_id}")
            )
        else:
            nav_buttons.append(InlineKeyboardButton("▶️", callback_data=f"noop#{callback_user_id}"))
            nav_buttons.append(InlineKeyboardButton("⏭", callback_data=f"noop#{callback_user_id}"))

        buttons.append(nav_buttons)

        # Update message
        await query.message.edit_text(
            f"🔍 **Search Results for:** {search_query}\n\n"
            f"📁 Found {total} files\n"
            f"📊 Page {current_page} of {total_pages}",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

        await query.answer()