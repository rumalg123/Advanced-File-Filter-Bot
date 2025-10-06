import asyncio
import random
import re
import uuid
from weakref import WeakSet

from pyrogram import Client, filters, enums
from pyrogram.handlers import MessageHandler, InlineQueryHandler
from pyrogram.types import Message, InlineQuery, InlineQueryResultCachedDocument, InlineKeyboardButton, \
    InlineKeyboardMarkup

from core.cache.config import CacheKeyGenerator, CacheTTLConfig
from core.session.manager import SessionType
from core.utils.caption import CaptionFormatter
from core.utils.file_emoji import get_file_emoji
from core.utils.helpers import format_file_size
from handlers.decorators import require_subscription, check_ban

from core.utils.logger import get_logger
from repositories.user import UserStatus
from core.utils.pagination import PaginationBuilder

logger = get_logger(__name__)


class SearchHandler:
    """Handler for search functionality with subscription checks"""

    def __init__(self, bot):
        self.bot = bot
        self.ttl = CacheTTLConfig()
        self.auto_delete_tasks = WeakSet()  # Use WeakSet for automatic cleanup
        self._handlers = []  # Track handlers for cleanup
        self._shutdown = asyncio.Event()  # Add shutdown signaling
        
        # Use unified session manager
        self.session_manager = getattr(bot, 'session_manager', None)
        
        self.register_handlers()

    def register_handlers(self):
        """Register search handlers"""
        # Text message search in groups and private chats
        excluded_commands = [
            'start', 'help', 'about', 'stats', 'plans',
            'broadcast', 'users', 'ban', 'unban', 'addpremium', 'removepremium',
            'add_channel', 'remove_channel', 'list_channels', 'toggle_channel',
            'connect', 'disconnect', 'connections', 'setskip',
            'delete', 'deleteall', 'link', 'plink', 'batch', 'pbatch',
            'viewfilters', 'filters', 'del', 'delall', 'delallf', 'deleteallf',
            'delf', 'deletef', 'add', 'filter', 'bsetting', 'restart', 'shell',
            'cache_stats', 'cache_analyze', 'cache_cleanup', 'log', 'performance', 'cancel', 'dbstats',
            'dbinfo', 'dbswitch'
        ]

        # Register text search handler
        text_handler = MessageHandler(
            self.handle_text_search,
            filters.text & filters.incoming & ~filters.command(excluded_commands)
        )

        # Use handler_manager if available - register with lower priority (higher group number)
        if hasattr(self.bot, 'handler_manager') and self.bot.handler_manager:
            self.bot.handler_manager.add_handler(text_handler)  # Handler manager doesn't support group parameter
        else:
            self.bot.add_handler(text_handler, group=10)  # Lower priority than command handlers
        self._handlers.append(text_handler)

        # Register inline query handler
        inline_handler = InlineQueryHandler(self.handle_inline_query)

        # Use handler_manager if available
        if hasattr(self.bot, 'handler_manager') and self.bot.handler_manager:
            self.bot.handler_manager.add_handler(inline_handler)
        else:
            self.bot.add_handler(inline_handler)
        self._handlers.append(inline_handler)

        logger.info(f"SearchHandler registered {len(self._handlers)} handlers")

    def _create_auto_delete_task(self, coro):
        """Create an auto-delete task that's automatically tracked

        Args:
            coro: A coroutine object (not a coroutine function)
        """
        if self._shutdown.is_set():
            logger.debug("Shutdown in progress, not creating new auto-delete task")
            # Close the coroutine to prevent warning
            coro.close()
            return None

        # Use handler_manager if available
        if hasattr(self.bot, 'handler_manager') and self.bot.handler_manager:
            return self.bot.handler_manager.create_auto_delete_task(coro)
        else:
            # Fallback to local tracking
            task = asyncio.create_task(coro)
            self.auto_delete_tasks.add(task)
            return task

    def _schedule_auto_delete(self, message: Message, delay: int):
        """Schedule auto-deletion of a message

        This wrapper method makes the intent clearer and avoids PyCharm warnings
        """
        if delay <= 0 or self._shutdown.is_set():
            return None

        # Create the coroutine and pass it to task creator
        coro = self._auto_delete_message(message, delay)
        return self._create_auto_delete_task(coro)

    async def cleanup(self):
        """Clean up resources"""
        logger.info("Cleaning up SearchHandler...")
        logger.info(f"Active auto-delete tasks: {len(self.auto_delete_tasks)}")

        # Signal shutdown
        self._shutdown.set()

        # If handler_manager is available, let it handle everything
        if hasattr(self.bot, 'handler_manager') and self.bot.handler_manager:
            logger.info("HandlerManager will handle cleanup")
            # Mark our handlers as removed in the manager
            for handler in self._handlers:
                handler_id = id(handler)
                self.bot.handler_manager.removed_handlers.add(handler_id)
            self._handlers.clear()
            logger.info("SearchHandler cleanup complete")
            return

        # Manual cleanup only if no handler_manager
        # Cancel remaining auto-delete tasks
        active_tasks = list(self.auto_delete_tasks)
        cancelled_count = 0

        for task in active_tasks:
            if not task.done():
                task.cancel()
                cancelled_count += 1

        # Wait for tasks to complete
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)

        logger.info(f"Cancelled {cancelled_count} of {len(active_tasks)} auto-delete tasks")

        # Remove handlers from bot
        for handler in self._handlers:
            try:
                self.bot.remove_handler(handler)
            except ValueError as e:
                if "x not in list" in str(e):
                    logger.debug(f"Handler already removed")
                else:
                    logger.error(f"Error removing handler: {e}")
            except Exception as e:
                logger.error(f"Error removing handler: {e}")

        self._handlers.clear()
        logger.info("SearchHandler cleanup complete")


    async def _auto_delete_message(self, message: Message, delay: int):
        """Auto-delete message after delay"""
        try:
            await asyncio.sleep(delay)
            if not self._shutdown.is_set():  # Only delete if not shutting down
                await message.delete()
        except asyncio.CancelledError:
            logger.debug("Auto-delete task cancelled")
            pass  # Task cancelled, exit cleanly
        except Exception as e:
            logger.debug(f"Failed to delete message: {e}")

    @check_ban()
    async def handle_text_search(self, client: Client, message: Message):
        """Handle text search in groups and private chats"""
        # Skip special channels
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

        # Skip if message is from a bot
        if message.from_user and message.from_user.is_bot:
            return

        user_id = message.from_user.id if message.from_user else None
        if not user_id:
            return

        # Check for active edit sessions using unified session manager
        if self.session_manager:
            # Check for active edit session
            if await self.session_manager.has_active_session(user_id, SessionType.EDIT):
                logger.info(f"[SEARCH_BLOCKED] User {user_id} has active edit session - blocking search for: '{message.text}'")
                return
        
        # Legacy check for recent edit flag
        recent_edit_key = CacheKeyGenerator.recent_settings_edit(user_id)
        if await self.bot.cache.exists(recent_edit_key):
            logger.info(f"[SEARCH_BLOCKED] User {user_id} has recent edit activity - blocking search")
            return

        # Check for recent settings edit flag
        cache_key = CacheKeyGenerator.recent_settings_edit(user_id)
        if await self.bot.cache.exists(cache_key):
            logger.debug(f"User {user_id} recently edited settings, skipping search")
            return

        # Get search query
        query = message.text.strip()
        if not query or len(query) < 2:
            return

        # Route to appropriate handler based on chat type
        if message.chat.type == enums.ChatType.PRIVATE:
            await self._handle_private_search_with_subscription(client, message, query, user_id)
        elif message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            await self._handle_group_search_no_subscription(client, message, query, user_id)

    @require_subscription(custom_message=(
            "🔒 <b>Subscription Required</b>\n"
            "To search for files, you need to join our channel(s) first.\n"
            "👇 Click the button(s) below to join, then try your search again."
    ))
    async def _handle_private_search_with_subscription(
            self,
            client: Client,
            message: Message,
            query: str,
            user_id: int
    ):
        """Handle search in private chat WITH subscription check"""
        await self._handle_private_search(client, message, query, user_id)

    async def _handle_group_search_no_subscription(
            self,
            client: Client,
            message: Message,
            query: str,
            user_id: int
    ):
        """Handle search in group chat WITHOUT subscription check - let users see available content"""
        # Just call the group search directly without subscription check
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

        # Check if user is banned
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

        # Check if premium mode is enabled - disable inline mode when premium is active
        if not self.bot.config.DISABLE_PREMIUM:
            # Allow admins to use inline mode even when premium is enabled
            is_admin = user_id in self.bot.config.ADMINS if self.bot.config.ADMINS else False
            if not is_admin:
                await query.answer(
                    results=[],
                    cache_time=0,
                    switch_pm_text="⚠️ Inline mode disabled (Premium mode active)",
                    switch_pm_parameter="inline_disabled"
                )
                return

        # Manual subscription check for inline queries
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
            # file_type_str = parts[1].strip().lower()
            # Add file type parsing if needed

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

            # Build inline results
            results = []
            for i, file in enumerate(files):
                # Create unique ID for each result
                unique_id = f"{offset}_{i}_{file.file_unique_id}"

                caption = CaptionFormatter.format_file_caption(
                    file=file,
                    custom_caption=self.bot.config.CUSTOM_FILE_CAPTION,
                    batch_caption=self.bot.config.BATCH_FILE_CAPTION,
                    keep_original=self.bot.config.KEEP_ORIGINAL_CAPTION,
                    is_batch=False,
                    auto_delete_minutes=None,  # No auto-delete for inline results
                    auto_delete_message=None
                )

                # Create inline result
                file_emoji = get_file_emoji(file.file_type, file.file_name, file.mime_type)
                result = InlineQueryResultCachedDocument(
                    id=unique_id,
                    title=f"{file_emoji} {file.file_name}",
                    document_file_id=file.file_id,
                    description=f"📊 {format_file_size(file.file_size)} • {file.file_type.value.title()}",
                    caption=caption,
                    parse_mode=enums.ParseMode.HTML
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

            # Check filters if enabled
            if not self.bot.config.DISABLE_FILTER:
                active_group = await self.bot.connection_service.get_active_connection(user_id)
                if active_group:
                    # Check filters from the active connection
                    filter_sent = await self._check_and_send_filter(
                        client, message, query, str(active_group), user_id, is_private=True
                    )

            # Send "not found" message only if nothing was sent
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
                    f"❌ No results found for <b>{query}</b>\n"
                    "Try using different keywords or check spelling.",
                    reply_markup=InlineKeyboardMarkup(no_results_buttons) if no_results_buttons else None
                )

        except Exception as e:
            logger.error(f"Error in private search: {e}", exc_info=True)
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
                await self._send_search_results(
                    client, message, files, query, total, page_size, user_id, is_private=False
                )

            # Check filters if enabled
            if not self.bot.config.DISABLE_FILTER:
                group_id = str(message.chat.id)
                # For groups, always check filters
                await self._check_and_send_filter(
                    client, message, query, group_id, user_id, is_private=False
                )

        except Exception as e:
            logger.error(f"Error in group search: {e}")
            # Don't send error messages in groups to avoid spam

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
            # Generate a unique session for search results
            session_id = uuid.uuid4().hex[:8]
            
            # Store file IDs in cache for "Send All" functionality - optimized
            search_key = CacheKeyGenerator.search_session(user_id, session_id)
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

            # Store search results with debug logging
            search_data = {'files': files_data, 'query': query, 'user_id': user_id}
            await self.bot.cache.set(
                search_key,
                search_data,
                expire=self.ttl.SEARCH_SESSION  # 1 hour expiry
            )
            
            logger.debug(f"Stored search results for key: {search_key}, TTL: {self.ttl.SEARCH_SESSION}s, files count: {len(files_data)}")

            # Create pagination builder
            pagination = PaginationBuilder(
                total_items=total,
                page_size=page_size,
                current_offset=0,
                query=query,
                user_id=user_id,
                callback_prefix="search"
            )

            # Build file buttons
            buttons = []

            # Add "Send All Files" button
            if files:
                if is_private:
                    buttons.append([
                        InlineKeyboardButton(
                            f"📤 Send All Files ({len(files)})",
                            callback_data=f"sendall#{search_key}"
                        )
                    ])
                else:
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

                file_emoji = get_file_emoji(file.file_type, file.file_name, file.mime_type)
                file_button = InlineKeyboardButton(
                    f"{file_emoji} {file.file_name[:50]}{'...' if len(file.file_name) > 50 else ''}",
                    callback_data=callback_data
                )
                buttons.append([file_button])

            # Add pagination buttons if needed
            if total > page_size:
                pagination_buttons = pagination.build_pagination_buttons()
                buttons.extend(pagination_buttons)

            # Build caption
            delete_time = self.bot.config.MESSAGE_DELETE_SECONDS
            delete_minutes = delete_time // 60 if delete_time > 0 else 0

            caption = (
                f"🔍 <b>Search Results for:</b> {query}\n"
                f"📁 Found {total} files\n"
                f"📊 Page {pagination.current_page} of {pagination.total_pages}"
            )

            if delete_time > 0:
                caption += f"\n⏱ <b>Note:</b> Results will be auto-deleted after {delete_minutes} minutes"

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
            if delete_time > 0:
                # Schedule deletion of the result message
                _ = self._schedule_auto_delete(sent_msg, delete_time)

                # Also delete the user's search query message in private
                if is_private:
                    _ = self._schedule_auto_delete(message, delete_time)

            return True

        except Exception as e:
            logger.error(f"Error sending search results: {e}", exc_info=True)
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
            # Check if any filter matches
            keywords = await self.bot.filter_service.get_all_filters(group_id)

            for keyword in reversed(sorted(keywords, key=len)):
                pattern = r"( |^|[^\w])" + re.escape(str(keyword)) + r"( |$|[^\w])"
                if re.search(pattern, query, flags=re.IGNORECASE):
                    # Get filter details
                    reply_text, btn, alert, fileid = await self.bot.filter_service.get_filter(
                        group_id, keyword
                    )

                    if reply_text:
                        reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")

                        # Add a header to distinguish filter results
                        if is_private:
                            filter_header = f"🔍 <b>Filter Match from Connected Group:</b>\n"
                        else:
                            filter_header = f"🔍 <b>Filter Match:</b>\n"

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