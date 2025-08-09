import asyncio
import io
import random
import re
import uuid


import aiohttp
from pyrogram import Client, filters, enums
from pyrogram.handlers import MessageHandler, InlineQueryHandler
from pyrogram.types import Message, InlineQuery, InlineQueryResultCachedDocument, InlineKeyboardButton, \
    InlineKeyboardMarkup

from core.cache.config import CacheKeyGenerator, CacheTTLConfig
from core.utils.caption import CaptionFormatter
from core.utils.helpers import format_file_size
from handlers.decorators import require_subscription, check_ban

from core.utils.logger import get_logger
from repositories.user import UserStatus

logger = get_logger(__name__)


class SearchHandler:
    """Handler for search functionality with subscription checks"""

    def __init__(self, bot):
        self.bot = bot
        self.ttl = CacheTTLConfig()
        self.register_handlers()


    def register_handlers(self):
        """Register search handlers"""
        # Text message search in groups and private chats
        excluded_commands = [
            'start', 'help', 'about', 'stats', 'plans',
            'broadcast', 'users', 'ban', 'unban', 'addpremium', 'removepremium',
            'add_channel', 'remove_channel', 'list_channels', 'toggle_channel',
            'connect', 'disconnect', 'connections', 'setskip',
            'delete', 'deleteall', 'link', 'plink', 'batch', 'pbatch', 'filters',
            'viewfilters', "filters", "viewfilters", "del", "delall", "delallf", "deleteallf",
            "delf", "deletef", "add", "filter"
        ]
        self.bot.add_handler(
            MessageHandler(
                self.handle_text_search,
                filters.text & filters.incoming & ~filters.command(excluded_commands)
            )
        )

        # Inline query handler
        self.bot.add_handler(
            InlineQueryHandler(self.handle_inline_query)
        )

    @check_ban()
    @require_subscription(custom_message=(
            "🔒 **Subscription Required**\n\n"
            "To search for files, you need to join our channel(s) first.\n\n"
            "👇 Click the button(s) below to join, then try your search again."
    ))
    async def handle_text_search(self, client: Client, message: Message):
        """Handle text search in groups and private chats"""

        special_channels = [
            self.bot.config.LOG_CHANNEL,
            self.bot.config.INDEX_REQ_CHANNEL,
            self.bot.config.REQ_CHANNEL,
            self.bot.config.DELETE_CHANNEL
        ]

        # Remove None values and convert to set
        special_channels = {ch for ch in special_channels if ch}
        if message.chat.id in special_channels:
            return

            # Also skip if message is from a bot
        if message.from_user and message.from_user.is_bot:
            return

        user_id = message.from_user.id if message.from_user else None
        if not user_id:
            return

        if hasattr(self.bot, 'bot_settings_handler') and hasattr(self.bot.bot_settings_handler, 'edit_sessions'):
            if user_id in self.bot.bot_settings_handler.edit_sessions:
                return
        cache_key = CacheKeyGenerator.recent_settings_edit(user_id)
        if await self.bot.cache.exists(cache_key):
            return
        # Get search query
        query = message.text.strip()
        if not query or len(query) < 2:
            return

        # Check if it's a private chat
        if message.chat.type == enums.ChatType.PRIVATE:
            await self._handle_private_search(client, message, query, user_id)
        elif message.chat.type == enums.ChatType.GROUP:
            # Group search - implement based on your needs
            await self._handle_group_search(client, message, query, user_id)
        elif message.chat.type == enums.ChatType.SUPERGROUP:
            await self._handle_group_search(client, message, query, user_id)


    async def handle_inline_query(self, client: Client, query: InlineQuery):
        """Handle inline search queries - send files directly when clicked"""
        user_id = query.from_user.id if query.from_user else None
        if not user_id:
            await query.answer(
                results=[],
                cache_time=0,
                switch_pm_text="❌ Authentication Error",
                switch_pm_parameter="start"
            )
            return
        if user_id not in self.bot.config.ADMINS:
            user = await self.bot.user_repo.get_user(user_id)
            if user and user.status == UserStatus.BANNED:
                await query.answer(
                    results=[],
                    cache_time=0,
                    switch_pm_text="🚫 You are banned",
                    switch_pm_parameter="banned"
                )
                return
        # Manual subscription check for inline queries (decorators don't work well with inline)
        # Skip subscription check for admins and auth users
        if not (user_id in self.bot.config.ADMINS or
                user_id in getattr(self.bot.config, 'AUTH_USERS', [])):

            # If auth requirements exist, check subscription
            if self.bot.config.AUTH_CHANNEL or getattr(self.bot.config, 'AUTH_GROUPS', []):
                is_subscribed = await self.bot.subscription_manager.is_subscribed(
                    client, user_id
                )

                if not is_subscribed:
                    await query.answer(
                        results=[],
                        cache_time=0,
                        switch_pm_text="🔒 Join channel to use bot",
                        switch_pm_parameter="subscribe"
                    )
                    return

        # Get search query
        search_query = query.query.strip()

        # Parse query for file type filter
        file_type = None
        if '|' in search_query:
            parts = search_query.split('|', maxsplit=1)
            search_query = parts[0].strip()
            file_type_str = parts[1].strip().lower()
            # You can add file type parsing here if needed

        if not search_query or len(search_query) < 2:
            await query.answer(
                results=[],
                cache_time=0,
                switch_pm_text="🔍 Type to search...",
                switch_pm_parameter="start"
            )
            return

        # Perform search
        try:
            offset = int(query.offset or 0)
            files, next_offset, total, has_access = await self.bot.file_service.search_files_with_access_check(
                user_id=user_id,
                query=search_query,
                chat_id=user_id,  # Use user_id for private context
                file_type=file_type,
                offset=offset,
                limit=10  # Limit to 10 for inline results
            )

            if not has_access:
                await query.answer(
                    results=[],
                    cache_time=0,
                    switch_pm_text="❌ Access Denied",
                    switch_pm_parameter="premium"
                )
                return

            if not files:
                await query.answer(
                    results=[],
                    cache_time=10,
                    switch_pm_text="❌ No results found",
                    switch_pm_parameter="start"
                )
                return

            # Build inline results - files will be sent directly when clicked
            results = []
            for i, file in enumerate(files):
                # Create unique ID for each result using offset and index
                unique_id = f"{offset}_{i}_{file.file_unique_id}"

                delete_time = self.bot.config.MESSAGE_DELETE_SECONDS
                delete_minutes = delete_time // 60
                caption = CaptionFormatter.format_file_caption(
                    file=file,
                    custom_caption=self.bot.config.CUSTOM_FILE_CAPTION,
                    batch_caption=self.bot.config.BATCH_FILE_CAPTION,
                    keep_original=self.bot.config.KEEP_ORIGINAL_CAPTION,
                    is_batch=False,
                    auto_delete_minutes=delete_minutes if delete_time > 0 else None
                )

                # Create inline result without buttons - file will be sent when clicked
                result = InlineQueryResultCachedDocument(
                    id=unique_id,  # Unique ID for this result
                    title=file.file_name,
                    document_file_id=file.file_id,  # The actual file to send
                    description=f"📊 {format_file_size(file.file_size)} • {file.file_type.value.title()}",
                    caption=caption,
                    parse_mode=enums.ParseMode.HTML
                    # No reply_markup - file sends directly when clicked
                )
                results.append(result)

            # Answer the inline query
            await query.answer(
                results=results,
                cache_time=30,
                is_personal=True,
                next_offset=str(next_offset) if next_offset else "",
                switch_pm_text=f"📁 Found {total} files" if total > 0 else "🔍 Search Files",
                switch_pm_parameter="start"
            )

        except Exception as e:
            logger.error(f"Error in inline search: {e}", exc_info=True)
            await query.answer(
                results=[],
                cache_time=0,
                switch_pm_text="❌ Search Error",
                switch_pm_parameter="start"
            )

    async def _handle_private_search(
            self,
            client: Client,
            message: Message,
            query: str,
            user_id: int
    ):
        """Handle search in private chat"""
        search_sent = False
        filter_sent = False
        try:
            # Search for files
            page_size = self.bot.config.MAX_BTN_SIZE
            files, next_offset, total, has_access = await self.bot.file_service.search_files_with_access_check(
                user_id=user_id,
                query=query,
                chat_id=user_id,
                offset=0,
                limit=page_size
            )

            if has_access and files:
                # Send search results
                search_sent = await self._send_search_results(
                    client, message, files, query, total, page_size, user_id, is_private=True
                )

            if not self.bot.config.DISABLE_FILTER:
                active_group = await self.bot.connection_service.get_active_connection(user_id)
                if active_group:
                    # Check filters from the active connection
                    filter_sent = await self._check_and_send_filter(
                        client, message, query, str(active_group), user_id, is_private=True
                    )

            if not search_sent and not filter_sent:
                no_results_buttons = []
                if self.bot.config.SUPPORT_GROUP_URL and self.bot.config.SUPPORT_GROUP_NAME:
                    no_results_buttons.append([
                        InlineKeyboardButton(
                            f"💬 {self.bot.config.SUPPORT_GROUP_NAME}",
                            url=self.bot.config.SUPPORT_GROUP_URL
                        )
                    ])

                await message.reply_text(
                    f"❌ No results found for **{query}**\n\n"
                    "Try using different keywords or check spelling.",
                    reply_markup=InlineKeyboardMarkup(no_results_buttons) if no_results_buttons else None
                )

        except Exception as e:
            logger.error(f"Error in private search: {e}")
            if not search_sent and not filter_sent:
                await message.reply_text("❌ An error occurred while searching. Please try again.")

    async def _handle_group_search(
            self,
            client: Client,
            message: Message,
            query: str,
            user_id: int
    ):
        """Handle search in group chat - only show results, no 'not found' messages"""

        search_sent = False
        filter_sent = False
        try:
            # Search for files
            page_size = self.bot.config.MAX_BTN_SIZE
            files, next_offset, total, has_access = await self.bot.file_service.search_files_with_access_check(
                user_id=user_id,
                query=query,
                chat_id=message.chat.id,
                offset=0,
                limit=page_size
            )

            if has_access and files:
                # Send search results
                search_sent = await self._send_search_results(
                    client, message, files, query, total, page_size, user_id, is_private=False
                )

            if not self.bot.config.DISABLE_FILTER:
                # Check if this group is someone's active connection
                group_id = str(message.chat.id)
                # For groups, always check filters
                filter_sent = await self._check_and_send_filter(
                    client, message, query, group_id, user_id, is_private=False
                )

        except Exception as e:
            logger.error(f"Error in group search: {e}")
            # Don't send error messages in groups

    async def _send_search_results(
            self,
            client: Client,
            message: Message,
            files: list,
            query: str,
            total: int,
            page_size: int,
            user_id: int,
            is_private: bool
    ) -> bool:
        """Send search results - returns True if sent successfully"""


        try:
            # Generate a unique key for this search result set
            session_id = uuid.uuid4().hex[:8]
            search_key = CacheKeyGenerator.search_session(user_id, session_id)

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
                {'files': files_data, 'query': query, 'user_id': user_id},
                expire=self.bot.cache.ttl_config.SEARCH_SESSION  # 1 hour expiry
            )

            # Calculate pagination info
            current_page = 1
            total_pages = ((total - 1) // page_size) + 1

            # Build file buttons
            buttons = []

            # Add "Send All Files" button as the first button
            if files and is_private:  # Send all only in private
                buttons.append([
                    InlineKeyboardButton(
                        f"📤 Send All Files ({len(files)})",
                        callback_data=f"sendall#{search_key}"
                    )
                ])
            elif files and not is_private:
                buttons.append([
                    InlineKeyboardButton(
                        f"📤 Send All Files ({len(files)})",
                        callback_data=f"sendall#{search_key}#{user_id}"
                    )
                ])

            # Add individual file buttons
            for file in files:
                file_identifier = file.file_unique_id if file.file_unique_id else file.file_ref
                if is_private:
                    callback_data = f"file#{file_identifier}"
                else:
                    callback_data = f"file#{file_identifier}#{user_id}"

                file_button = InlineKeyboardButton(
                    f"📁 {file.file_name[:50]}{'...' if len(file.file_name) > 50 else ''}",
                    callback_data=callback_data
                )
                buttons.append([file_button])

            # Add pagination buttons if there are multiple pages
            if total > page_size:
                nav_buttons = self._build_pagination_buttons(
                    current_page, total_pages, query, 0, total, user_id
                )
                buttons.append(nav_buttons)

            # Build caption
            delete_time = self.bot.config.MESSAGE_DELETE_SECONDS
            delete_minutes = delete_time // 60

            caption = (
                f"🔍 **Search Results for:** {query}\n\n"
                f"📁 Found {total} files\n"
                f"📊 Page {current_page} of {total_pages}"
            )

            if not is_private or delete_time > 0:
                caption += f"\n\n⏱ **Note:** Results will be auto-deleted after {delete_minutes} minutes"

            # Send message with or without photo
            if self.bot.config.PICS:
                sent_msg = await message.reply_photo(
                    photo=random.choice(self.bot.config.PICS),
                    caption=caption,
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            else:
                sent_msg = await message.reply_text(
                    caption,
                    reply_markup=InlineKeyboardMarkup(buttons)
                )

            # Schedule deletion
            if delete_time > 0:
                asyncio.create_task(
                    self._auto_delete_message(sent_msg, delete_time)
                )

                # Also delete the user's search query message in private
                if is_private:
                    asyncio.create_task(
                        self._auto_delete_message(message, delete_time)
                    )

            return True

        except Exception as e:
            logger.error(f"Error sending search results: {e}")
            return False

    async def _check_and_send_filter(
            self,
            client: Client,
            message: Message,
            query: str,
            group_id: str,
            user_id: int,
            is_private: bool
    ) -> bool:
        """Check and send filter if it matches - returns True if filter was sent"""
        if not self.bot.filter_service or self.bot.config.DISABLE_FILTER:
            return False

        try:
            # Create a temporary message object with the query as text for filter checking
            temp_message = type('obj', (object,), {
                'text': query,
                'from_user': message.from_user,
                'chat': type('obj', (object,), {'id': int(group_id), 'type': message.chat.type})(),
                'reply_to_message': None,
                'reply_text': message.reply_text,
                'id': message.id
            })()

            # Check if any filter matches
            keywords = await self.bot.filter_service.get_all_filters(group_id)

            for keyword in reversed(sorted(keywords, key=len)):
                pattern = r"( |^|[^\w])" + re.escape(keyword) + r"( |$|[^\w])"
                if re.search(pattern, query, flags=re.IGNORECASE):
                    # Get filter details
                    reply_text, btn, alert, fileid = await self.bot.filter_service.get_filter(
                        group_id, keyword
                    )

                    if reply_text:
                        reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")

                        # Add a header to distinguish filter results
                        if is_private:
                            filter_header = f"🔍 **Filter Match from Connected Group:**\n\n"
                        else:
                            filter_header = f"🔍 **Filter Match:**\n\n"

                        # Send filter response
                        await self.bot.filter_service.send_filter_response(
                            client,
                            message,
                            filter_header + reply_text,
                            btn,
                            alert,
                            fileid
                        )

                        return True

            return False

        except Exception as e:
            logger.error(f"Error checking filter: {e}")
            return False

    def _build_pagination_buttons(
            self,
            current_page: int,
            total_pages: int,
            query: str,
            offset: int,
            total: int,
            user_id: int
    ) -> list:
        """Build pagination buttons"""
        nav_buttons = []

        # First and Previous buttons
        if offset > 0:
            nav_buttons.append(
                InlineKeyboardButton("⏮ First",
                                     callback_data=f"search#first#{query}#0#{total}#{user_id}")
            )
            nav_buttons.append(
                InlineKeyboardButton("◀️ Prev",
                                     callback_data=f"search#prev#{query}#{offset}#{total}#{user_id}")
            )
        else:
            nav_buttons.append(InlineKeyboardButton("⏮", callback_data=f"noop#{user_id}"))
            nav_buttons.append(InlineKeyboardButton("◀️", callback_data=f"noop#{user_id}"))

        # Current page indicator
        nav_buttons.append(
            InlineKeyboardButton(f"📄 {current_page}/{total_pages}", callback_data=f"noop#{user_id}")
        )

        # Next and Last buttons
        if current_page < total_pages:
            nav_buttons.append(
                InlineKeyboardButton("Next ▶️",
                                     callback_data=f"search#next#{query}#{offset}#{total}#{user_id}")
            )
            nav_buttons.append(
                InlineKeyboardButton("Last ⏭",
                                     callback_data=f"search#last#{query}#{offset}#{total}#{user_id}")
            )
        else:
            nav_buttons.append(InlineKeyboardButton("▶️", callback_data=f"noop#{user_id}"))
            nav_buttons.append(InlineKeyboardButton("⏭", callback_data=f"noop#{user_id}"))

        return nav_buttons

    async def _auto_delete_message(self, message: Message, delay: int):
        """Auto-delete message after delay"""
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except Exception as e:
            logger.debug(f"Failed to delete message: {e}")


