import re
from datetime import datetime
from typing import Optional, List

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import UserIsBlocked, InputUserDeactivated, PeerIdInvalid

from core.utils.logger import get_logger
from core.utils.search_results import SearchResultsBuilder
from core.utils.telegram_api import telegram_api
from core.utils.validators import validate_callback_data
from handlers.base import BaseHandler

logger = get_logger(__name__)


class RequestHandler(BaseHandler):
    """Handler for #request feature in support group"""

    def __init__(self, bot):
        super().__init__(bot)
        self.background_tasks: List = []  # Track any background tasks
        self.results_builder = SearchResultsBuilder(bot.cache, bot.config)
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
        is_allowed, limit_message, should_ban, should_log_warning = await self.bot.user_repo.track_request(user_id,message.from_user.first_name)

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
                    await telegram_api.call_api(
                        client.send_message,
                        user_id,
                        ban_msg,
                        chat_id=user_id
                    )
                except Exception as e:
                    logger.error(f"error sending ban_msg in request handler: {e}")
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
                    await telegram_api.call_api(
                        client.send_message,
                        self.bot.config.LOG_CHANNEL,
                        log_text,
                        chat_id=self.bot.config.LOG_CHANNEL
                    )
                return

        if not is_allowed:
            # Send message to user
            await message.reply_text(limit_message)

            # Only log warning to admin channel for actual abuse (not premium denial)
            if should_log_warning and self.bot.config.LOG_CHANNEL:
                user = message.from_user
                warning_text = (
                    f"#RequestWarning\n"
                    f"👤 <b>User:</b> {user.mention} [<code>{user_id}</code>]\n"
                    f"📝 <b>Username:</b> @{user.username if user.username else 'N/A'}\n"
                    f"🔍 <b>Keyword:</b> <code>{keyword}</code>\n"
                    f"⚠️ <b>Message:</b> {limit_message}\n"
                    f"📅 <b>Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                await telegram_api.call_api(
                    client.send_message,
                    self.bot.config.LOG_CHANNEL,
                    warning_text,
                    chat_id=self.bot.config.LOG_CHANNEL
                )
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
                    client, message, files, keyword, total, page_size, user_id, is_private=False
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
        """Send search results using the shared builder"""
        if self._shutdown.is_set():
            return False

        success, sent_msg = await self.results_builder.send_search_results(
            message=message,
            files=files,
            query=query,
            total=total,
            page_size=page_size,
            user_id=user_id,
            is_private=is_private,
            callback_prefix="search"
        )

        if success and sent_msg:
            # Schedule auto-deletion if configured
            delete_time = self.bot.config.MESSAGE_DELETE_SECONDS
            if delete_time > 0:
                self._create_auto_delete_task(
                    self._auto_delete_message(sent_msg, delete_time)
                )
                if is_private:
                    self._create_auto_delete_task(
                        self._auto_delete_message(message, delete_time)
                    )

        return success

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
            # telegram_api.call_api already uses semaphore_manager internally
            await telegram_api.call_api(
                client.send_message,
                target_channel,
                request_text,
                reply_markup=InlineKeyboardMarkup(buttons),
                chat_id=target_channel
            )
        except Exception as e:
            logger.error(f"Failed to forward request: {e}")

    async def handle_request_callback(self, client: Client, query: CallbackQuery):
        """Handle request action callbacks"""
        if self._shutdown.is_set():
            await query.answer("Bot is shutting down", show_alert=True)
            return

        # Validate callback data using validator
        is_valid, data = validate_callback_data(query, expected_parts=4)
        if not is_valid:
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
            await telegram_api.call_api(
                client.send_message,
                user_id,
                response_msg,
                chat_id=user_id
            )
            pm_sent = True
        except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid):
            pass
        except Exception as e:
            logger.error(f"Failed to send PM: {e}")

        # If PM failed and we have support group, try there
        if not pm_sent and self.bot.config.SUPPORT_GROUP_ID:
            try:
                user = await telegram_api.call_api(
                    client.get_users,
                    user_id
                )
                mention_msg = (
                    f"{user.mention}, due to bot being blocked, here's your request update:\n"
                    f"{response_msg}"
                )

                await telegram_api.call_api(
                    client.send_message,
                    self.bot.config.SUPPORT_GROUP_ID,
                    mention_msg,
                    reply_to_message_id=msg_id,
                    chat_id=self.bot.config.SUPPORT_GROUP_ID
                )
            except Exception as e:
                logger.error(f"Failed to send to group: {e}")

        # Update admin message
        await query.message.edit_reply_markup(None)
        await query.message.edit_text(
            query.message.text + f"\n✅ <b>Action Taken:</b> {action.title()}"
        )

        await query.answer(f"✅ User notified: {action.title()}")


