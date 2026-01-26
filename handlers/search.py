import asyncio
import random
import re
import uuid
from weakref import WeakSet

from pyrogram import Client, filters, enums
from pyrogram.errors import QueryIdInvalid
from pyrogram.handlers import MessageHandler, InlineQueryHandler
from pyrogram.types import Message, InlineQuery, InlineQueryResultCachedDocument, InlineKeyboardButton, \
    InlineKeyboardMarkup

from core.cache.config import CacheKeyGenerator, CacheTTLConfig
from core.session.manager import SessionType
from core.services.search_results import SearchResultsService
from core.utils.button_builder import ButtonBuilder
from core.utils.caption import CaptionFormatter
from core.utils.error_formatter import ErrorMessageFormatter
from core.utils.file_emoji import get_file_emoji, get_file_type_display_name
from core.utils.helpers import format_file_size
from core.utils.messages import MessageHelper
from handlers.decorators import require_subscription, check_ban

from core.utils.logger import get_logger
from core.utils.validators import (
    sanitize_search_query, extract_user_id, is_admin, is_auth_user,
    is_bot_user, get_special_channels, is_special_channel
)
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
        
        # Initialize search results service
        self.search_results_service = SearchResultsService(
            cache_manager=bot.cache,
            config=bot.config
        )
        
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
        # Skip special channels using validators
        special_channels = get_special_channels(self.bot.config)
        if is_special_channel(message.chat.id, special_channels):
            return

        # Skip if message is from a bot
        if is_bot_user(message):
            return

        user_id = extract_user_id(message)
        if not user_id:
            return

        # Check for active edit sessions using unified session manager
        if self.session_manager:
            # Check for active edit session
            if await self.session_manager.has_active_session(user_id, SessionType.EDIT):
                logger.info(f"[SEARCH_BLOCKED] User {user_id} has active edit session - blocking search for: '{message.text}'")
                return
        
        # Check for recent edit flag (blocks search during settings edit)
        recent_edit_key = CacheKeyGenerator.recent_settings_edit(user_id)
        if await self.bot.cache.exists(recent_edit_key):
            logger.info(f"[SEARCH_BLOCKED] User {user_id} has recent edit activity - blocking search")
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

    @require_subscription(custom_message=None)  # Will use MessageHelper.get_force_sub_message() in decorator
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
        user_id = extract_user_id(query)
        if not user_id:
            try:
                await query.answer(
                    results=[],
                    cache_time=0,
                    switch_pm_text=ErrorMessageFormatter.format_error("Authentication Error", include_prefix=False),
                    switch_pm_parameter="start"
                )
            except QueryIdInvalid:
                logger.warning(f"Inline query expired for unknown user")
            except Exception as e:
                logger.error(f"Error answering inline query: {e}")
            return

        # Check if user is banned using validators
        if not is_admin(user_id, self.bot.config.ADMINS):
            user = await self.bot.user_repo.get_user(user_id)
            if user and user.status == UserStatus.BANNED:
                # Get ban message from bot config or default (shortened for inline query)
                ban_msg_template = MessageHelper.get_ban_message(self.bot.config)
                # Format with user's ban info
                ban_text = ban_msg_template.format(
                    reason=user.ban_reason or 'No reason provided',
                    date=user.updated_at.strftime('%Y-%m-%d') if user.updated_at else 'Unknown'
                )
                # Use shortened version for inline query switch_pm_text
                switch_text = "🚫 You are banned"
                try:
                    await query.answer(
                        results=[],
                        cache_time=0,
                        switch_pm_text=switch_text,
                        switch_pm_parameter="banned"
                    )
                except QueryIdInvalid:
                    logger.warning(f"Inline query expired for banned user")
                except Exception as e:
                    logger.error(f"Error answering inline query: {e}")
                return

        # Check if premium mode is enabled - disable inline mode when premium is active
        if not self.bot.config.DISABLE_PREMIUM:
            # Allow admins to use inline mode even when premium is enabled
            if not is_admin(user_id, self.bot.config.ADMINS):
                try:
                    await query.answer(
                        results=[],
                        cache_time=0,
                        switch_pm_text=ErrorMessageFormatter.format_warning("Inline mode disabled (Premium mode active)", include_prefix=False),
                        switch_pm_parameter="inline_disabled"
                    )
                except QueryIdInvalid:
                    logger.warning(f"Inline query expired for user {user_id} (premium check)")
                except Exception as e:
                    logger.error(f"Error answering inline query: {e}")
                return


        # Manual subscription check for inline queries using validators
        auth_users = getattr(self.bot.config, 'AUTH_USERS', [])
        if not (is_admin(user_id, self.bot.config.ADMINS) or is_auth_user(user_id, auth_users)):

            # If auth requirements exist, check subscription
            if self.bot.config.AUTH_CHANNEL or getattr(self.bot.config, 'AUTH_GROUPS', []):
                is_subscribed = await self.bot.subscription_manager.is_subscribed(
                    client, user_id
                )

                if not is_subscribed:
                    try:
                        await query.answer(
                            results=[],
                            cache_time=0,
                            switch_pm_text="🔒 Join channel to use bot",
                            switch_pm_parameter="subscribe"
                        )
                    except QueryIdInvalid:
                        logger.warning(f"Inline query expired for user {user_id} (subscription check)")
                    except Exception as e:
                        logger.error(f"Error answering inline query: {e}")
                    return

        # Get and sanitize search query
        search_query = sanitize_search_query(query.query)

        # Parse query for file type filter
        file_type = None
        if '|' in search_query:
            parts = search_query.split('|', maxsplit=1)
            search_query = sanitize_search_query(parts[0])
            # file_type_str = parts[1].strip().lower()
            # Add file type parsing if needed

        if not search_query or len(search_query) < 2:
            try:
                await query.answer(
                    results=[],
                    cache_time=0,
                    switch_pm_text="🔍 Type to search...",
                    switch_pm_parameter="start"
                )
            except QueryIdInvalid:
                logger.warning(f"Inline query expired for user {user_id} (empty search)")
            except Exception as e:
                logger.error(f"Error answering inline query: {e}")
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
                try:
                    await query.answer(
                        results=[],
                        cache_time=0,
                        switch_pm_text=ErrorMessageFormatter.format_access_denied(include_prefix=False),
                        switch_pm_parameter="premium"
                    )
                except QueryIdInvalid:
                    logger.warning(f"Inline query expired for user {user_id} (access denied)")
                except Exception as e:
                    logger.error(f"Error answering inline query for access denied: {e}")
                return

            if not files:
                try:
                    await query.answer(
                        results=[],
                        cache_time=10,
                        switch_pm_text=ErrorMessageFormatter.format_not_found("Results", include_prefix=False),
                        switch_pm_parameter="start"
                    )
                except QueryIdInvalid:
                    logger.warning(f"Inline query expired for user {user_id} (no results)")
                except Exception as e:
                    logger.error(f"Error answering inline query for no results: {e}")
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
                    description=f"📊 {format_file_size(file.file_size)} • {get_file_type_display_name(file.file_type)}",
                    caption=caption,
                    parse_mode=CaptionFormatter.get_parse_mode()
                )
                results.append(result)

            # Answer the inline query
            try:
                await query.answer(
                    results=results,
                    cache_time=30,
                    is_personal=True,
                    next_offset=str(next_offset) if next_offset else "",
                    switch_pm_text=f"📁 Found {total} files" if total > 0 else "🔍 Search Files",
                    switch_pm_parameter="start"
                )
            except QueryIdInvalid:
                logger.warning(f"Inline query expired for user {user_id} while sending results")
            except Exception as e:
                logger.error(f"Error answering inline query with results for user {user_id}: {e}")

        except Exception as e:
            logger.error(f"Error in inline search: {e}", exc_info=True)
            await query.answer(
                results=[],
                cache_time=0,
                switch_pm_text=ErrorMessageFormatter.format_error("Search Error", include_prefix=False),
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
                # Send search results using centralized service
                search_sent = await self.search_results_service.send_results(
                    client=client,
                    message=message,
                    files=files,
                    query=query,
                    total=total,
                    page_size=page_size,
                    user_id=user_id,
                    is_private=True,
                    auto_delete_callback=self._schedule_auto_delete
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
                        ButtonBuilder.action_button(
                            f"💬 {self.bot.config.SUPPORT_GROUP_NAME}",
                            url=self.bot.config.SUPPORT_GROUP_URL
                        )
                    ])

                # Get no results message from bot config or default
                no_results_template = MessageHelper.get_no_results_message(self.bot.config)
                no_results_text = no_results_template.format(query=query)
                
                await message.reply_text(
                    no_results_text,
                    reply_markup=InlineKeyboardMarkup(no_results_buttons) if no_results_buttons else None
                )

        except Exception as e:
            logger.error(f"Error in private search: {e}", exc_info=True)
            if not search_sent and not filter_sent:
                await message.reply_text(ErrorMessageFormatter.format_error("An error occurred while searching. Please try again."))

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
                # Send search results using centralized service
                await self.search_results_service.send_results(
                    client=client,
                    message=message,
                    files=files,
                    query=query,
                    total=total,
                    page_size=page_size,
                    user_id=user_id,
                    is_private=False,
                    auto_delete_callback=self._schedule_auto_delete
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