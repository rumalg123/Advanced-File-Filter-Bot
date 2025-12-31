import random
import re
import uuid
from datetime import datetime
from typing import Optional, List

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import UserIsBlocked, InputUserDeactivated, PeerIdInvalid

from core.cache.config import CacheKeyGenerator, CacheTTLConfig
from core.utils.file_emoji import get_file_emoji
from core.utils.logger import get_logger
from core.utils.pagination import PaginationBuilder
from handlers.base import BaseHandler

logger = get_logger(__name__)


class RequestHandler(BaseHandler):
    """Handler for #request feature in support group"""

    def __init__(self, bot):
        super().__init__(bot)
        self.background_tasks: List = []  # Track any background tasks
        self.register_handlers()

    def register_handlers(self) -> None:
        """Register request handlers"""
        if not self.bot.config.SUPPORT_GROUP_ID:
            logger.info("Support group not configured, skipping request handler")
            return

        # Handle #request messages in support group
        self._register_message_handlers([
            (self.handle_request_message,
             filters.chat(self.bot.config.SUPPORT_GROUP_ID) & filters.text & filters.regex(r"^#request\s+"))
        ])

        # Handle request action callbacks
        self._register_callback_handlers([
            (self.handle_request_callback, filters.regex(r"^req_action#"))
        ])

        logger.info(f"RequestHandler registered {len(self._handlers)} handlers")

    # cleanup() method is inherited from BaseHandler, with background_tasks cleanup added
    async def cleanup(self) -> None:
        """Clean up handler resources including background tasks"""
        # Cancel any background tasks specific to this handler
        for task in self.background_tasks:
            if not task.done():
                task.cancel()

        if self.background_tasks:
            import asyncio
            await asyncio.gather(*self.background_tasks, return_exceptions=True)

        self.background_tasks.clear()

        # Call parent cleanup
        await super().cleanup()

    # _create_auto_delete_task, _schedule_auto_delete, and _auto_delete_message
    # are all inherited from BaseHandler

    async def handle_request_message(self, client: Client, message: Message):
        """Handle #request messages in support group"""
        if not message.text or not message.from_user:
            return

        if self._shutdown.is_set():
            logger.debug("Ignoring request message during shutdown")
            return

        # Extract keyword after #request
        match = re.match(r"^#request\s+(.+)", message.text, re.IGNORECASE)
        if not match:
            return

        keyword = match.group(1).strip()
        user_id = message.from_user.id

        # Check request limits
        is_allowed, limit_message, should_ban = await self.bot.user_repo.track_request(user_id)

        if should_ban:
            # Auto-ban the user
            success, banned_user = await self.bot.user_repo.auto_ban_for_request_abuse(user_id)

            if success:
                # Notify user about ban
                ban_msg = (
                    "🚫 <b>You have been banned from using this bot</b>\n"
                    f"<b>Reason:</b> Over request warning limit\n"
                    f"<b>Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    "You exceeded the maximum number of request warnings.\n"
                    "Please contact the bot administrator to appeal."
                )

                await message.reply_text(ban_msg)

                # Try to send PM notification
                try:
                    await client.send_message(user_id, ban_msg)
                except Exception:
                    pass

                # Log to admin channel
                if self.bot.config.LOG_CHANNEL:
                    log_text = (
                        f"#AutoBan #RequestAbuse\n"
                        f"<b>User:</b> <code>{user_id}</code> ({banned_user.name if banned_user else 'Unknown'})\n"
                        f"<b>Reason:</b> Over request warning limit\n"
                        f"<b>Total Requests:</b> {banned_user.total_requests if banned_user else 'N/A'}\n"
                        f"<b>Warnings:</b> {banned_user.warning_count if banned_user else 'N/A'}\n"
                        f"<b>Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    await client.send_message(self.bot.config.LOG_CHANNEL, log_text)
                return

        if not is_allowed:
            # Send warning message
            await message.reply_text(limit_message)

            # Log warning to admin channel
            if self.bot.config.LOG_CHANNEL:
                user = message.from_user
                warning_text = (
                    f"#RequestWarning\n"
                    f"👤 <b>User:</b> {user.mention} [<code>{user_id}</code>]\n"
                    f"📝 <b>Username:</b> @{user.username if user.username else 'N/A'}\n"
                    f"🔍 <b>Keyword:</b> <code>{keyword}</code>\n"
                    f"⚠️ <b>Message:</b> {limit_message}\n"
                    f"📅 <b>Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                await client.send_message(self.bot.config.LOG_CHANNEL, warning_text)
            return

        # Normal request processing continues here
        search_results = await self._search_for_request(client, message, keyword, user_id)

        if search_results:
            logger.debug(f"Search results found for request: {keyword}")
        else:
            # No results, forward to admins
            await message.reply_text(
                f"📋 Your request has been noted. {limit_message}\n"
                "Admins will process it as soon as possible."
            )
            await self._forward_request_to_admins(client, message, keyword)

    async def _search_for_request(self, client: Client, message: Message, keyword: str, user_id: int) -> Optional[bool]:
        """Search for files matching the request"""
        try:
            # Don't search if shutting down
            if self._shutdown.is_set():
                return False

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
            if self._shutdown.is_set():
                return False
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
                {'files': files_data, 'query': query, 'user_id': user_id},
                expire=CacheTTLConfig.SEARCH_SESSION  # 1 hour expiry
            )

            # Create pagination builder
            pagination = PaginationBuilder(
                total_items=total,
                page_size=page_size,
                current_offset=0,  # Initial search starts at offset 0
                query=query,
                user_id=user_id,
                callback_prefix="search"
            )

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

                file_emoji = get_file_emoji(file.file_type, file.file_name, file.mime_type)
                file_button = InlineKeyboardButton(
                    f"{file_emoji} {file.file_name[:50]}{'...' if len(file.file_name) > 50 else ''}",
                    callback_data=callback_data
                )
                buttons.append([file_button])

            # Add smart pagination buttons if there are multiple pages
            if total > page_size:
                pagination_buttons = pagination.build_pagination_buttons()
                buttons.extend(pagination_buttons)

            # Build caption
            delete_time = self.bot.config.MESSAGE_DELETE_SECONDS
            delete_minutes = delete_time // 60

            caption = (
                f"🔍 <b>Search Results for:</b> {query}\n"
                f"📁 Found {total} files\n"
                f"📊 Page {pagination.current_page} of {pagination.total_pages}"
            )

            if not is_private or delete_time > 0:
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

            # Schedule deletion using proper task tracking
            if delete_time > 0:
                self._create_auto_delete_task(
                    self._auto_delete_message(sent_msg, delete_time)
                )

                # Also delete the user's search query message in private
                if is_private:
                    self._create_auto_delete_task(
                        self._auto_delete_message(message, delete_time)
                    )

            return True

        except Exception as e:
            logger.error(f"Error sending search results: {e}")
            return False

    async def _forward_request_to_admins(self, client: Client, message: Message, keyword: str):
        """Forward request to admin channel"""
        if self._shutdown.is_set():
            return False
        user = message.from_user

        # Build request info
        request_text = (
            f"📮 <b>New Content Request</b>\n"
            f"👤 <b>User:</b> {user.mention} [<code>{user.id}</code>]\n"
            f"📝 <b>Username:</b> @{user.username if user.username else 'N/A'}\n"
            f"📅 <b>Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🔍 <b>Keyword:</b> <code>{keyword}</code>\n"
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
        if self._shutdown.is_set():
            await query.answer("Bot is shutting down", show_alert=True)
            return
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
                    f"{user.mention}, due to bot being blocked, here's your request update:\n"
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
            query.message.text + f"\n✅ <b>Action Taken:</b> {action.title()}"
        )

        await query.answer(f"✅ User notified: {action.title()}")


