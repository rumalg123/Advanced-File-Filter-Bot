import asyncio
import io
import random
import re
import uuid
from datetime import datetime

import aiohttp
from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import UserIsBlocked, InputUserDeactivated, PeerIdInvalid

from core.cache.config import CacheKeyGenerator
from core.utils.logger import get_logger

logger = get_logger(__name__)


class RequestHandler:
    """Handler for #request feature in support group"""

    def __init__(self, bot):
        self.bot = bot
        self.register_handlers()

    def register_handlers(self):
        """Register request handlers"""
        if not self.bot.config.SUPPORT_GROUP_ID:
            logger.info("Support group not configured, skipping request handler")
            return

        # Handle #request messages in support group
        self.bot.add_handler(
            MessageHandler(
                self.handle_request_message,
                filters.chat(self.bot.config.SUPPORT_GROUP_ID) & filters.text & filters.regex(r"^#request\s+")
            )
        )

        # Handle request action callbacks
        self.bot.add_handler(
            CallbackQueryHandler(
                self.handle_request_callback,
                filters.regex(r"^req_action#")
            )
        )

    async def handle_request_message(self, client: Client, message: Message):
        """Handle #request messages in support group"""
        if not message.text or not message.from_user:
            return

        # Extract keyword after #request
        match = re.match(r"^#request\s+(.+)", message.text, re.IGNORECASE)
        if not match:
            return

        keyword = match.group(1).strip()
        user_id = message.from_user.id

        # First try to search
        search_results = await self._search_for_request(client,message,keyword, user_id)

        if search_results:
            # Found results, show them
            logger.debug(f"Search results: {search_results}")
        else:
            # No results, forward to admins
            await message.reply_text(
                "📋 Your request has been noted.\n"
                "Admins will process it as soon as possible."
            )

            await self._forward_request_to_admins(client, message, keyword)

    async def _search_for_request(self, client: Client,message: Message,keyword: str, user_id: int) -> bool | None:
        """Search for files matching the request"""
        try:
            # Search for files
            page_size = self.bot.config.MAX_BTN_SIZE
            files, next_offset, total, has_access = await self.bot.file_service.search_files_with_access_check(
                user_id=user_id,
                query=keyword,
                chat_id=user_id,
                offset=0,
                limit=page_size
            )

            if has_access and files:
                # Send search results
                search_sent = await self._send_search_results(
                    client, message, files, keyword, total, page_size, user_id, is_private=True
                )
                if search_sent:
                    return search_sent
                else:
                    return False
            return False
        except Exception as e:
            logger.error(f"Error searching for request: {e}")

        return False

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

    async def _forward_request_to_admins(self, client: Client, message: Message, keyword: str):
        """Forward request to admin channel"""
        user = message.from_user

        # Build request info
        request_text = (
            f"📮 **New Content Request**\n\n"
            f"👤 **User:** {user.mention} [`{user.id}`]\n"
            f"📝 **Username:** @{user.username if user.username else 'N/A'}\n"
            f"📅 **Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🔍 **Keyword:** `{keyword}`\n"
        )

        # Build buttons
        message_link = f"https://t.me/c/{str(self.bot.config.SUPPORT_GROUP_ID)[4:]}/{message.id}"

        buttons = [
            [InlineKeyboardButton("📩 View Message", url=message_link)],
            [
                InlineKeyboardButton("❌ Unavailable", callback_data=f"req_action#unavail#{user.id}#{message.id}"),
                InlineKeyboardButton("✅ Already Available", callback_data=f"req_action#avail#{user.id}#{message.id}")
            ],
            [
                InlineKeyboardButton("📤 Upload Complete", callback_data=f"req_action#done#{user.id}#{message.id}"),
                InlineKeyboardButton("🚫 Reject Request", callback_data=f"req_action#reject#{user.id}#{message.id}")
            ]
        ]

        # Send to REQ_CHANNEL or LOG_CHANNEL
        target_channel = self.bot.config.REQ_CHANNEL or self.bot.config.LOG_CHANNEL

        try:
            await client.send_message(
                target_channel,
                request_text,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        except Exception as e:
            logger.error(f"Failed to forward request: {e}")

    async def handle_request_callback(self, client: Client, query: CallbackQuery):
        """Handle request action callbacks"""
        data = query.data.split("#")
        if len(data) < 4:
            return await query.answer("Invalid data", show_alert=True)

        _, action, user_id, msg_id = data
        user_id = int(user_id)
        msg_id = int(msg_id)

        # Map actions to messages
        action_messages = {
            'unavail': "❌ Your requested content is currently unavailable.",
            'avail': "✅ Your requested content is already available! Please search for it.",
            'done': "📤 Your requested content has been uploaded! You can now search for it.",
            'reject': "🚫 Your request has been rejected by admins."
        }

        response_msg = action_messages.get(action, "Your request has been processed.")

        # Try to send PM first
        pm_sent = False
        try:
            await client.send_message(user_id, response_msg)
            pm_sent = True
        except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid):
            pass
        except Exception as e:
            logger.error(f"Failed to send PM: {e}")

        # If PM failed and we have support group, try there
        if not pm_sent and self.bot.config.SUPPORT_GROUP_ID:
            try:
                user = await client.get_users(user_id)
                mention_msg = (
                    f"{user.mention}, due to bot being blocked, here's your request update:\n\n"
                    f"{response_msg}"
                )

                await client.send_message(
                    self.bot.config.SUPPORT_GROUP_ID,
                    mention_msg,
                    reply_to_message_id=msg_id
                )
            except Exception as e:
                logger.error(f"Failed to send to group: {e}")

        # Update admin message
        await query.message.edit_reply_markup(None)
        await query.message.edit_text(
            query.message.text + f"\n\n✅ **Action Taken:** {action.title()}"
        )

        await query.answer(f"✅ User notified: {action.title()}")


