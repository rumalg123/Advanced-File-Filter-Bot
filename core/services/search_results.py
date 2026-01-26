# core/services/search_results.py
"""Service for sending search results with pagination and buttons"""
import random
import uuid
from typing import List, Optional, Callable, Any

from pyrogram import Client
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup

from core.cache.config import CacheKeyGenerator, CacheTTLConfig
from core.utils.button_builder import ButtonBuilder
from core.utils.caption import CaptionFormatter
from core.utils.error_formatter import ErrorMessageFormatter
from core.utils.logger import get_logger
from core.utils.pagination import PaginationBuilder
from repositories.media import MediaFile

logger = get_logger(__name__)


class SearchResultsService:
    """Service for sending search results with unified formatting and pagination"""

    def __init__(self, cache_manager, config, recommendation_service=None):
        """
        Initialize SearchResultsService
        
        Args:
            cache_manager: Cache manager instance for storing search sessions
            config: Bot configuration object
            recommendation_service: Optional recommendation service for tracking
        """
        self.cache = cache_manager
        self.config = config
        self.ttl = CacheTTLConfig()
        self.recommendation_service = recommendation_service

    async def send_results(
        self,
        client: Client,
        message: Message,
        files: List[MediaFile],
        query: str,
        total: int,
        page_size: int,
        user_id: int,
        is_private: bool,
        current_offset: int = 0,
        callback_prefix: str = "search",
        auto_delete_callback: Optional[Callable[[Message, int], Any]] = None,
        shutdown_check: Optional[Callable[[], bool]] = None
    ) -> bool:
        """
        Send search results with pagination and buttons.
        
        This method handles:
        - Session ID generation and cache storage
        - Pagination building
        - Button creation (Send All + individual files + pagination)
        - Caption formatting
        - Message sending (with or without photo)
        - Auto-deletion scheduling (via callback)
        
        Args:
            client: Pyrogram Client instance
            message: Message to reply to
            files: List of MediaFile objects to display
            query: Search query string
            total: Total number of files matching the query
            page_size: Number of files per page
            user_id: User ID for access control
            is_private: Whether this is a private chat
            current_offset: Current offset in results (default: 0)
            callback_prefix: Prefix for callback data (default: "search")
            auto_delete_callback: Optional callback for scheduling auto-delete.
                                 Signature: (message: Message, delay: int) -> Any
            shutdown_check: Optional callback to check if shutdown is in progress.
                           Returns True if should abort.
        
        Returns:
            True if sent successfully, False otherwise
        """
        try:
            # Check for shutdown if callback provided
            if shutdown_check and shutdown_check():
                return False

            # Generate unique session ID
            session_id = uuid.uuid4().hex[:8]
            search_key = CacheKeyGenerator.search_session(user_id, session_id)

            # Prepare files data for cache
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

            # Store search results in cache
            search_data = {'files': files_data, 'query': query, 'user_id': user_id}
            await self.cache.set(
                search_key,
                search_data,
                expire=self.ttl.SEARCH_SESSION
            )
            
            # Store user's last search for recommendation tracking
            recent_search_key = CacheKeyGenerator.user_last_search(user_id)
            await self.cache.set(
                recent_search_key,
                {'query': query, 'search_key': search_key},
                expire=self.ttl.USER_LAST_SEARCH
            )
            
            # Track files shown for this query (for recommendations)
            if hasattr(self, 'recommendation_service') and self.recommendation_service:
                try:
                    file_unique_ids = [f.file_unique_id for f in files]
                    await self.recommendation_service.track_files_from_query(query, file_unique_ids)
                except Exception as e:
                    logger.debug(f"Error tracking files for recommendations: {e}")

            logger.debug(
                f"Stored search results for key: {search_key}, "
                f"TTL: {self.ttl.SEARCH_SESSION}s, files count: {len(files_data)}"
            )

            # Create pagination builder
            pagination = PaginationBuilder(
                total_items=total,
                page_size=page_size,
                current_offset=current_offset,
                query=query,
                user_id=user_id,
                callback_prefix=callback_prefix
            )

            # Build buttons
            buttons = self._build_buttons(
                files=files,
                search_key=search_key,
                user_id=user_id,
                is_private=is_private,
                pagination=pagination,
                total=total,
                page_size=page_size
            )

            # Build caption using centralized formatter
            caption = CaptionFormatter.format_search_results_caption(
                query=query,
                total=total,
                pagination=pagination,
                delete_time=self.config.MESSAGE_DELETE_SECONDS,
                is_private=is_private
            )

            # Send message with or without photo
            sent_msg = await self._send_message(
                client=client,
                message=message,
                caption=caption,
                buttons=buttons
            )

            # Schedule auto-deletion if enabled and callback provided
            delete_time = self.config.MESSAGE_DELETE_SECONDS
            if delete_time > 0 and auto_delete_callback:
                auto_delete_callback(sent_msg, delete_time)
                
                # Also delete the user's search query message in private
                if is_private:
                    auto_delete_callback(message, delete_time)
            
            # Show recommendations after search results (non-blocking, async)
            if self.recommendation_service and is_private:
                try:
                    # Get recommendations based on current query
                    recommended_file_ids = await self.recommendation_service.get_recommended_files_from_query(
                        query, limit=3
                    )
                    
                    # Get similar queries
                    similar_queries = await self.recommendation_service.get_similar_queries(query, limit=3)
                    
                    # Only show if we have recommendations
                    if recommended_file_ids or similar_queries:
                        # This will be sent as a separate message (non-blocking)
                        # We'll create a background task for this
                        import asyncio
                        asyncio.create_task(
                            self._send_recommendations(
                                client, message, query, recommended_file_ids, similar_queries, user_id
                            )
                        )
                except Exception as e:
                    logger.debug(f"Error showing recommendations: {e}")

            return True

        except Exception as e:
            logger.error(f"Error sending search results: {e}", exc_info=True)
            return False

    def _build_buttons(
        self,
        files: List[MediaFile],
        search_key: str,
        user_id: int,
        is_private: bool,
        pagination: PaginationBuilder,
        total: int,
        page_size: int
    ) -> List[List[InlineKeyboardButton]]:
        """Build inline keyboard buttons for search results"""
        buttons = []

        # Add "Send All Files" button
        if files:
            send_all_button = ButtonBuilder.send_all_button(
                file_count=len(files),
                search_key=search_key,
                user_id=user_id,
                is_private=is_private
            )
            buttons.append([send_all_button])

        # Add individual file buttons
        file_buttons = ButtonBuilder.file_buttons_row(
            files=files,
            user_id=user_id,
            is_private=is_private
        )
        buttons.extend(file_buttons)

        # Add pagination buttons if needed
        if total > page_size:
            pagination_buttons = pagination.build_pagination_buttons()
            buttons.extend(pagination_buttons)

        return buttons
    
    async def _send_recommendations(
        self,
        client: Client,
        message: Message,
        query: str,
        recommended_file_ids: List[str],
        similar_queries: List[str],
        user_id: int
    ):
        """Send recommendations as a separate message (non-blocking)"""
        try:
            from core.utils.error_formatter import ErrorMessageFormatter
            from core.utils.button_builder import ButtonBuilder
            
            text_parts = []
            buttons = []
            
            # Add similar queries as buttons
            if similar_queries:
                text_parts.append("💡 <b>Similar Searches:</b>")
                query_buttons = []
                for similar_query in similar_queries[:3]:
                    query_buttons.append(
                        ButtonBuilder.action_button(
                            f"🔍 {similar_query[:20]}...",
                            callback_data=f"search#page#{similar_query}#0#0#{user_id}"
                        )
                    )
                if query_buttons:
                    buttons.append(query_buttons)
            
            # Note: File recommendations would require fetching files from DB
            # For now, we'll just show query recommendations
            # File recommendations can be added later when files are fetched
            
            if buttons:
                text = "\n".join(text_parts) if text_parts else "💡 <b>Recommendations</b>"
                await message.reply_text(
                    text,
                    reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
                )
        except Exception as e:
            logger.debug(f"Error sending recommendations: {e}")

    async def _send_message(
        self,
        client: Client,
        message: Message,
        caption: str,
        buttons: List[List[InlineKeyboardButton]]
    ) -> Message:
        """Send message with or without photo"""
        reply_markup = InlineKeyboardMarkup(buttons)

        if self.config.PICS:
            return await message.reply_photo(
                photo=random.choice(self.config.PICS),
                caption=caption,
                reply_markup=reply_markup
            )
        else:
            return await message.reply_text(
                caption,
                reply_markup=reply_markup
            )
