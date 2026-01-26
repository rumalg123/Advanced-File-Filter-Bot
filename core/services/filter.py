import json
import re
from typing import Optional, List, Tuple, Union

from pyrogram import Client
from pyrogram.enums import ChatType
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from core.cache.redis_cache import CacheManager
from core.services.connection import ConnectionService
from core.utils.button_builder import ButtonBuilder
from core.utils.logger import get_logger
from core.utils.telegram_api import telegram_api
from core.utils.validators import extract_user_id, is_private_chat
from repositories.filter import FilterRepository

logger = get_logger(__name__)


class FilterService:
    """Enhanced service for managing filters with connection support"""

    def __init__(self,
                 filter_repo: FilterRepository,
                 cache_manager: CacheManager,
                 connection_service: ConnectionService,
                 config):
        self.filter_repo = filter_repo
        self.cache = cache_manager
        self.connection_service = connection_service
        self.config = config

        # Regex for parsing button URLs
        self.BTN_URL_REGEX = re.compile(
            r"(\[([^\[]+?)]\((buttonurl|buttonalert):/{0,2}(.+?)(:same)?\))"
        )

    async def get_active_group_id(self, client:Client,message: Message) -> Tuple[Optional[int], Optional[str]]:
        """Get the active group ID based on chat type and connections"""
        user_id = extract_user_id(message)
        if not user_id:
            return None, None

        if is_private_chat(message):
            # Get active connection in private chat
            group_id = await self.connection_service.get_active_connection(user_id)
            if not group_id:
                return None, "not_connected"

            # Get group title
            try:
                chat = await telegram_api.call_api(
                    client.get_chat,
                    group_id,
                    chat_id=group_id
                )
                return int(group_id), chat.title
            except Exception:
                return int(group_id), f"Group {group_id}"
        else:
            # Use current chat in groups
            return message.chat.id, message.chat.title

    def parse_filter_text(self, text: str, keyword: str) -> Tuple[str, List, List]:
        """Parse filter text for buttons and alerts"""
        if "buttonalert" in text:
            text = text.replace("\n", "\\n").replace("\t", "\\t")

        buttons = []
        note_data = ""
        prev = 0
        i = 0
        alerts = []

        for match in self.BTN_URL_REGEX.finditer(text):
            # Check if btnurl is escaped
            n_escapes = 0
            to_check = match.start(1) - 1
            while to_check > 0 and text[to_check] == "\\":
                n_escapes += 1
                to_check -= 1

            # if even, not escaped -> create button
            if n_escapes % 2 == 0:
                note_data += text[prev:match.start(1)]
                prev = match.end(1)

                if match.group(3) == "buttonalert":
                    button = ButtonBuilder.action_button(
                        text=match.group(2),
                        callback_data=f"alertmessage:{i}:{keyword}"
                    )
                    if bool(match.group(5)) and buttons:
                        buttons[-1].append(button)
                    else:
                        buttons.append([button])
                    i += 1
                    alerts.append(match.group(4))
                else:
                    button = ButtonBuilder.action_button(
                        text=match.group(2),
                        url=match.group(4).replace(" ", "")
                    )
                    if bool(match.group(5)) and buttons:
                        buttons[-1].append(button)
                    else:
                        buttons.append([button])
            else:
                note_data += text[prev:to_check]
                prev = match.start(1) - 1
        else:
            note_data += text[prev:]

        return note_data, buttons, alerts

    async def add_filter(self, group_id: str, keyword: str,
                         reply_text: str, buttons: str = "[]",
                         file_id: str = None, alert: str = None) -> bool:
        """Add a new filter"""
        return await self.filter_repo.add_filter(
            group_id, keyword, reply_text, buttons,
            file_id or "None", alert
        )

    async def get_filter(self, group_id: str, keyword: str) -> Tuple[str, str, str, str]:
        """Get a filter by keyword"""
        return await self.filter_repo.find_filter(group_id, keyword)

    async def delete_filter(self, group_id: Optional[Union[str, int]], keyword: str) -> int:
        """Delete a filter"""
        if group_id is None:
            logger.warning("Attempted to delete filter with None group_id")
            return 0
        return await self.filter_repo.delete_filter(str(group_id), keyword)

    async def get_all_filters(self, group_id: str) -> List[str]:
        """Get all filters for a group"""
        return await self.filter_repo.get_filters(group_id)

    async def delete_all_filters(self, group_id: str) -> bool:
        """Delete all filters for a group"""
        return await self.filter_repo.delete_all_filters(group_id)

    async def count_filters(self, group_id: str) -> int:
        """Count filters for a group"""
        return await self.filter_repo.count_filters(group_id)

    async def check_filters(self, client: Client, message: Message) -> bool:
        """Check if message matches any filter and respond"""
        if not message.text:
            return False

        text = message.text

        # Check group-specific filters using validator
        if not is_private_chat(message):
            group_id = str(message.chat.id)
            group_result = await self._check_filter_match(
                client, message, text, group_id
            )
            if group_result:
                return True
        else:
            # In private chat, check filters from active connection
            user_id = extract_user_id(message)
            if user_id:
                active_group = await self.connection_service.get_active_connection(user_id)
                if active_group:
                    group_result = await self._check_filter_match(
                        client, message, text, str(active_group)
                    )
                    if group_result:
                        return True

        return False

    async def _check_filter_match(self, client: Client, message: Message,
                                  text: str, group_id: str) -> bool:
        """
        Check if text matches any filter and send response.
        Uses exact matching first, then fuzzy matching as fallback for typos.
        """
        keywords = await self.get_all_filters(group_id)
        text_lower = text.lower()

        # First, try exact matching (faster and more accurate)
        for keyword in sorted(keywords, key=len, reverse=True):
            pattern = r"( |^|[^\w])" + re.escape(keyword) + r"( |$|[^\w])"
            if re.search(pattern, text, flags=re.IGNORECASE):
                reply_text, btn, alert, fileid = await self.get_filter(
                    group_id, keyword
                )

                if reply_text:
                    reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")

                if btn is not None:
                    await self.send_filter_response(
                        client, message, reply_text, btn, alert, fileid
                    )
                    return True

        # If no exact match, try fuzzy matching for typos (only for short keywords to avoid false positives)
        # Only use fuzzy matching for keywords <= 10 chars to avoid performance issues
        short_keywords = [k for k in keywords if len(k) <= 10]
        if short_keywords:
            try:
                from core.utils.helpers import find_similar_queries
                
                # Check if any word in the text matches a filter keyword with high similarity
                text_words = text_lower.split()
                for word in text_words:
                    if len(word) >= 3:  # Only check words with at least 3 chars
                        similar = find_similar_queries(
                            word,
                            [k.lower() for k in short_keywords],
                            threshold=85.0,  # High threshold to avoid false positives
                            max_results=1
                        )
                        
                        if similar:
                            matched_keyword = similar[0][0]
                            # Find the original keyword (case-insensitive)
                            original_keyword = next((k for k in short_keywords if k.lower() == matched_keyword), None)
                            if original_keyword:
                                reply_text, btn, alert, fileid = await self.get_filter(
                                    group_id, original_keyword
                                )

                                if reply_text:
                                    reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")

                                if btn is not None:
                                    await self.send_filter_response(
                                        client, message, reply_text, btn, alert, fileid
                                    )
                                    return True
            except Exception as e:
                logger.debug(f"Error in fuzzy filter matching: {e}")

        return False

    async def send_filter_response(self, client: Client, message: Message,
                                   reply_text: str, btn: str, alert: str,
                                   fileid: str) -> None:
        """Send the filter response with concurrency control"""
        reply_id = message.reply_to_message.id if message.reply_to_message else message.id
        chat_id = message.chat.id

        if is_private_chat(message):
            try:
                if fileid == "None":
                    # Text-only response
                    if btn == "[]":
                        await telegram_api.call_api(
                            client.send_message,
                            chat_id,
                            reply_text,
                            disable_web_page_preview=True,
                            protect_content=False,
                            reply_to_message_id=reply_id,
                            chat_id=chat_id
                        )
                    else:
                        # Text with buttons
                        button = json.loads(btn)
                        await telegram_api.call_api(
                            client.send_message,
                            chat_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_markup=InlineKeyboardMarkup(button),
                            protect_content=False,
                            reply_to_message_id=reply_id,
                            chat_id=chat_id
                        )
                else:
                    # Media response
                    if btn == "[]":
                        await telegram_api.call_api(
                            client.send_cached_media,
                            chat_id,
                            fileid,
                            caption=reply_text or "",
                            protect_content=False,
                            reply_to_message_id=reply_id,
                            chat_id=chat_id
                        )
                    else:
                        button = json.loads(btn)
                        await telegram_api.call_api(
                            client.send_cached_media,
                            chat_id,
                            fileid,
                            caption=reply_text or "",
                            reply_markup=InlineKeyboardMarkup(button),
                            protect_content=False,
                            reply_to_message_id=reply_id,
                            chat_id=chat_id
                        )
            except Exception as e:
                logger.error(f"Error sending filter response in private chat: {e}")
        else:
            # Group chat response
            try:
                if fileid == "None":
                    # Text-only response
                    if btn == "[]":
                        await telegram_api.call_api(
                            client.send_message,
                            chat_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_to_message_id=reply_id,
                            chat_id=chat_id
                        )
                    else:
                        # Text with buttons
                        button = json.loads(btn)
                        await telegram_api.call_api(
                            client.send_message,
                            chat_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_markup=InlineKeyboardMarkup(button),
                            reply_to_message_id=reply_id,
                            chat_id=chat_id
                        )
                else:
                    # Media response
                    if btn == "[]":
                        await telegram_api.call_api(
                            client.send_cached_media,
                            chat_id,
                            fileid,
                            caption=reply_text or "",
                            reply_to_message_id=reply_id,
                            chat_id=chat_id
                        )
                    else:
                        button = json.loads(btn)
                        await telegram_api.call_api(
                            client.send_cached_media,
                            chat_id,
                            fileid,
                            caption=reply_text or "",
                            reply_markup=InlineKeyboardMarkup(button),
                            reply_to_message_id=reply_id,
                            chat_id=chat_id
                        )
            except Exception as e:
                logger.error(f"Error sending filter response in group chat: {e}")