import asyncio
import base64

from pyrogram import Client
from pyrogram.types import Message

from core.utils.caption import CaptionFormatter
from core.utils.error_formatter import ErrorMessageFormatter
from core.utils.logger import get_logger
from core.utils.telegram_api import telegram_api
from handlers.commands_handlers.base import BaseCommandHandler
from handlers.decorators import require_subscription
from repositories.user import UserStatus
from core.utils import validators
from core.utils.validators import UserAccessContext
logger = get_logger(__name__)


class DeepLinkHandler(BaseCommandHandler):
    """Handler for deep link parameters in /start command"""

    async def safe_reply(self, message, text, **kwargs):
        """Safely reply to a message, handling both regular and fake message objects"""
        try:
            if hasattr(message, 'reply'):
                return await message.reply(text, **kwargs)
            elif hasattr(message, 'reply_text'):
                return await message.reply_text(text, **kwargs)
            else:
                logger.warning(f"Cannot reply to message: {text}")
                return None
        except Exception as e:
            logger.error(f"Error replying to message: {e}")
            return None

    async def safe_delete(self, message):
        """Safely delete a message if the object supports it."""
        try:
            if hasattr(message, 'delete'):
                await message.delete()
        except Exception as e:
            logger.debug(f"Could not delete message: {e}")

    async def handle_deep_link_internal(self, client: Client, message: Message, data: str):
        """Internal method for handling deep links (subscription already checked)"""
        user_id = message.from_user.id

        # Handle special parameters first
        if data == "inline_disabled":
            # Explain why inline mode is disabled
            await message.reply_text(
                "🔒 <b>Inline Mode Disabled</b>\n\n"
                "Inline mode is currently unavailable because premium features are enabled.\n\n"
                "<b>Why?</b>\n"
                "• Inline mode sends files directly from Telegram servers\n"
                "• We cannot track file usage in inline mode\n"
                "• Daily limits cannot be enforced for inline results\n\n"
                "<b>Alternatives:</b>\n"
                "• Use the search feature in groups or private chat\n"
                "• Request files using #request in support group\n"
                "• Upgrade to premium for unlimited access\n\n"
                "Thank you for understanding! 🙏"
                , parse_mode=CaptionFormatter.get_parse_mode()
            )
            return

        # Handle different deep link types
        if data.startswith("batch_"):
            # Batch file request
            batch_id = data[6:]  # Remove 'batch_' prefix
            await self._send_batch(client, message, batch_id)

        elif data.startswith("DSTORE-"):
            # Direct store request
            await self._send_dstore_files(client, message, data[7:])
            
        elif data.startswith("PBLINK-"):
            # Premium batch link request
            batch_id = data[7:]  # Remove 'PBLINK-' prefix
            await self._send_premium_batch(client, message, batch_id)

        elif data.startswith("sendall_"):
            # Send all files from search
            search_key = data[8:]  # Remove 'sendall_' prefix
            await self._send_all_from_search(client, message, search_key)

        elif data.startswith("all_"):
            # Send all files from search
            parts = data.split("_", 2)
            if len(parts) >= 3:
                _, key, file_type = parts
                await self._send_all_files(client, message, key, file_type)
        else:
            # Default to single file request (handles encoded links)
            await self._send_filestore_file(client, message, data)

    # Keep the original decorated method for when it's called as a handler
    @require_subscription()
    async def handle_deep_link(self, client: Client, message: Message, data: str):
        """Handle deep link parameters with subscription check"""
        await self.handle_deep_link_internal(client, message, data)
    async def _send_filestore_file(self, client: Client, message: Message, encoded: str):
        """Send a file from filestore link - subscription already checked by decorator"""
        user_id = message.from_user.id
        owner_id = self.bot.config.ADMINS[0] if self.bot.config.ADMINS else None

        # Decode file identifier
        file_identifier, protect = self.bot.filestore_service.decode_file_identifier(encoded)

        if not file_identifier:
            await self.safe_reply(message, ErrorMessageFormatter.format_invalid("link format"))
            return

        # Check user access using unified lookup
        can_access, reason, file = await self.bot.file_service.check_and_grant_access(
            user_id,
            file_identifier,
            increment=True,
            owner_id=owner_id
        )

        if not can_access:
            logger.warning(f"Access denied for user {user_id}: {reason}")
            await message.reply_text(ErrorMessageFormatter.format_access_denied(reason))
            return

        if not file:
            logger.error(f"File not found for identifier: {file_identifier}")
            await message.reply_text(ErrorMessageFormatter.format_not_found("File"))
            return

        # Send file directly using file_id
        try:
            delete_time = self.bot.config.MESSAGE_DELETE_SECONDS
            delete_minutes = delete_time // 60
            caption = CaptionFormatter.format_file_caption(
                file=file,
                custom_caption=self.bot.config.CUSTOM_FILE_CAPTION,
                batch_caption=self.bot.config.BATCH_FILE_CAPTION,
                keep_original=self.bot.config.KEEP_ORIGINAL_CAPTION,
                is_batch=False,
                auto_delete_minutes=delete_minutes,
                auto_delete_message=self.bot.config.AUTO_DELETE_MESSAGE
            )

            logger.info(f"Sending file - ID: {file.file_id}, Name: {file.file_name}")

            # Use telegram_api for concurrency control
            sent_msg = await telegram_api.call_api(
                client.send_cached_media,
                user_id,
                file.file_id,
                caption=caption,
                protect_content=protect,
                parse_mode=CaptionFormatter.get_parse_mode(),
                chat_id=user_id
            )

            logger.info(f"File sent successfully to user {user_id}")

            asyncio.create_task(
                self._auto_delete_message(sent_msg, delete_time)
            )

            # Delete the command message after successful send (safe for fake messages)
            await self.safe_delete(message)

        except Exception as e:
            logger.error(f"Error sending file to user {user_id}: {e}", exc_info=True)
            await message.reply_text(ErrorMessageFormatter.format_failed("Please try again", action="to send file"))

    async def _send_dstore_files(self, client: Client, message: Message, encoded: str):
        """Send files directly from channel"""
        user_id = message.from_user.id

        # Decode DSTORE data
        try:
            decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("ascii")
            parts = decoded.split("_", 3)

            if len(parts) < 3:
                raise ValueError("Invalid format")

            f_msg_id = int(parts[0])
            l_msg_id = int(parts[1])
            chat_id = int(parts[2])
            protect = parts[3] == "pbatch" if len(parts) > 3 else False

        except Exception as e:
            logger.error(f"Failed to decode identifier: {encoded} Error: {e}")
            await self.safe_reply(message, ErrorMessageFormatter.format_invalid("link format"))
            return

        # Check access
        owner_id = self.bot.config.ADMINS[0] if self.bot.config.ADMINS else None
        can_access, reason = await self.bot.user_repo.can_retrieve_file(user_id, owner_id)

        if not can_access:
            await message.reply_text(ErrorMessageFormatter.format_access_denied(reason))
            return

        sts = await message.reply("<b>Processing files...</b>")

        # Send files - pass self.bot instead of client

        success_count, total_count = await self.bot.filestore_service.send_channel_files(
            self.bot,  # Changed from client to self.bot
            user_id,
            chat_id,
            f_msg_id,
            l_msg_id,
            protect=protect
        )

        await sts.delete()

        if success_count > 0:
            transfer_msg = await message.reply_text(
                ErrorMessageFormatter.format_success("Transfer completed!") + "\n"
                f"Files sent: {success_count}/{total_count}"
            )
            # Schedule auto-delete for transfer complete message
            if self.bot.config.MESSAGE_DELETE_SECONDS > 0 and transfer_msg:
                asyncio.create_task(
                    self._auto_delete_message(transfer_msg, self.bot.config.MESSAGE_DELETE_SECONDS)
                )
        else:
            failed_msg = await message.reply_text(ErrorMessageFormatter.format_failed("to send files"))
            # Schedule auto-delete for error message
            if self.bot.config.MESSAGE_DELETE_SECONDS > 0 and failed_msg:
                asyncio.create_task(
                    self._auto_delete_message(failed_msg, self.bot.config.MESSAGE_DELETE_SECONDS)
                )


    async def _send_all_from_search(self, client: Client, message: Message, search_key: str):
        """Send all files from search key"""
        user_id = message.from_user.id

        # Get cached search results with debug logging
        cached_data = await self.bot.cache.get(search_key)
        logger.debug(f"Deep link sendall - search key: {search_key}, data found: {cached_data is not None}")

        if not cached_data:
            logger.warning(f"Deep link sendall - search results expired or not found for key: {search_key}")
            await message.reply_text(ErrorMessageFormatter.format_error("Search results expired. Please search again."))
            return

        files_data = cached_data.get('files', [])

        if not files_data:
            await message.reply_text(ErrorMessageFormatter.format_not_found("Files"))
            return

        # Check access for bulk send
        owner_id = self.bot.config.ADMINS[0] if self.bot.config.ADMINS else None
        can_access, reason = await self.bot.user_repo.can_retrieve_file(user_id, owner_id)

        if not can_access:
            await message.reply_text(ErrorMessageFormatter.format_access_denied(reason))
            return

        # Check quota for non-premium users
        # Force fresh fetch from DB, not cache, to get accurate count
        await self.bot.user_repo.cache_invalidator.invalidate_user_data(user_id)
        user = await self.bot.user_repo.get_user(user_id)

        # Build access context for permission checks
        access_ctx = UserAccessContext.from_config(user_id, user, self.bot.config)

        # Only check quota for users who should be tracked (non-premium, non-admin, non-owner)
        if access_ctx.should_track_retrieval:
            remaining = self.bot.config.NON_PREMIUM_DAILY_LIMIT - user.daily_retrieval_count
            if remaining < len(files_data):
                await message.reply_text(
                    ErrorMessageFormatter.format_error(
                        f"You can only retrieve {remaining} more files today. "
                        f"Upgrade to premium for unlimited access!"
                    )
                )
                return

        # Send files without progress updates (simplified)
        sending_file_msg = await message.reply_text(f"📤 Sending {len(files_data)} files...")

        # Batch fetch all files in one query instead of N individual queries
        file_unique_ids = [f['file_unique_id'] for f in files_data]
        files_map = await self.bot.media_repo.find_files_batch(file_unique_ids)

        success_count = 0
        for file_data in files_data:
            try:
                file_unique_id = file_data['file_unique_id']
                file = files_map.get(file_unique_id)

                if not file:
                    logger.warning(f"File {file_unique_id} not found.")
                    continue

                caption = CaptionFormatter.format_file_caption(
                    file=file,
                    custom_caption=self.bot.config.CUSTOM_FILE_CAPTION,
                    batch_caption=self.bot.config.BATCH_FILE_CAPTION,
                    keep_original=self.bot.config.KEEP_ORIGINAL_CAPTION,
                    is_batch=False,  # These are NOT batch files, they're from search
                    auto_delete_minutes=self.bot.config.MESSAGE_DELETE_SECONDS // 60 if self.bot.config.MESSAGE_DELETE_SECONDS > 0 else None,
                    auto_delete_message=self.bot.config.AUTO_DELETE_MESSAGE
                )
                # Use telegram_api for concurrency control
                sent_msg = await telegram_api.call_api(
                    client.send_cached_media,
                    user_id,
                    file.file_id,
                    caption=caption,
                    parse_mode=CaptionFormatter.get_parse_mode(),
                    chat_id=user_id
                )

                # Schedule auto-deletion if enabled
                if self.bot.config.MESSAGE_DELETE_SECONDS > 0:
                    asyncio.create_task(self._auto_delete_message(sent_msg, self.bot.config.MESSAGE_DELETE_SECONDS))
                success_count += 1

                # Note: We'll increment all at once after the loop to avoid race conditions

                await asyncio.sleep(1)  # Avoid flooding

            except Exception as e:
                logger.error(f"Error sending file: {e}")
                continue

        # Increment retrieval count for all successfully sent files at once (batch operation)
        if success_count > 0 and access_ctx.should_track_retrieval:
            await self.bot.user_repo.increment_retrieval_count_batch(user_id, success_count)

        sent_msg = await message.reply_text(ErrorMessageFormatter.format_success(f"Sent {success_count}/{len(files_data)} files!"))
        # Schedule auto-delete for completion message
        if self.bot.config.MESSAGE_DELETE_SECONDS > 0 and sent_msg:
            asyncio.create_task(
                self._auto_delete_message(sent_msg, self.bot.config.MESSAGE_DELETE_SECONDS)
            )
        await telegram_api.call_api(
            client.delete_messages,
            sending_file_msg.chat.id,
            sending_file_msg.id,
            chat_id=sending_file_msg.chat.id
        )

        # Delete the command message
        await self.safe_delete(message)

    async def _send_batch(self, client: Client, message: Message, batch_id: str):
        """Send batch files from a batch ID"""
        user_id = message.from_user.id

        # Get batch data from filestore service
        batch_data = await self.bot.filestore_service.get_batch_data(client, batch_id)

        if not batch_data:
            await message.reply_text(ErrorMessageFormatter.format_not_found("Batch") + " or expired")
            return

        # Check access
        owner_id = self.bot.config.ADMINS[0] if self.bot.config.ADMINS else None
        can_access, reason = await self.bot.user_repo.can_retrieve_file(user_id, owner_id)

        if not can_access:
            await message.reply_text(ErrorMessageFormatter.format_access_denied(reason))
            return

        # Send batch files
        success_count, total_count = await self.bot.filestore_service.send_batch_files(
            client,
            user_id,
            batch_data
        )

        if success_count > 0:
            batch_msg = await message.reply_text(
                f"✅ Batch transfer completed!\n"
                f"Files sent: {success_count}/{total_count}"
            )
            # Schedule auto-delete for batch transfer complete message
            if self.bot.config.MESSAGE_DELETE_SECONDS > 0 and batch_msg:
                asyncio.create_task(
                    self._auto_delete_message(batch_msg, self.bot.config.MESSAGE_DELETE_SECONDS)
                )
        else:
            failed_msg = await message.reply_text(ErrorMessageFormatter.format_failed("to send batch files"))
            # Schedule auto-delete for error message
            if self.bot.config.MESSAGE_DELETE_SECONDS > 0 and failed_msg:
                asyncio.create_task(
                    self._auto_delete_message(failed_msg, self.bot.config.MESSAGE_DELETE_SECONDS)
                )

    async def _send_all_files(self, client: Client, message: Message, key: str, file_type: str):
        """Send all files of a specific type"""
        user_id = message.from_user.id

        # Reconstruct and sanitize search query from key
        search_query = validators.sanitize_search_query(key.replace('_', ' '))

        # Check access
        owner_id = self.bot.config.ADMINS[0] if self.bot.config.ADMINS else None
        can_access, reason = await self.bot.user_repo.can_retrieve_file(user_id, owner_id)

        if not can_access:
            await message.reply_text(ErrorMessageFormatter.format_access_denied(reason))
            return

        # Validate file type if specified
        from repositories.media import FileType
        from core.utils.file_type import get_file_type_from_value
        if file_type:
            validated_type = get_file_type_from_value(file_type)
            if not validated_type:
                await message.reply_text(ErrorMessageFormatter.format_invalid("file type"))
                return

        # Get all files (using a higher limit)
        files, _, total, has_access, access_reason = await self.bot.file_service.search_files_with_access_check(
            user_id=user_id,
            query=search_query,
            chat_id=user_id,
            file_type=file_type.lower() if file_type else None,
            offset=0,
            limit=100  # Adjust based on your needs
        )

        if not has_access:
            await message.reply_text(ErrorMessageFormatter.format_access_denied())
            return

        if not files:
            await message.reply_text(ErrorMessageFormatter.format_not_found("Files"))
            return

        # Send files
        await message.reply_text(f"📤 Sending {len(files)} {file_type or 'all'} files...")

        # Pre-compute user info and access context (avoid repeated lookups in loop)
        user = await self.bot.user_repo.get_user(user_id)
        access_ctx = UserAccessContext.from_config(user_id, user, self.bot.config)

        success_count = 0
        for file in files:
            try:
                caption = CaptionFormatter.format_file_caption(
                    file=file,
                    custom_caption=self.bot.config.CUSTOM_FILE_CAPTION,
                    batch_caption=self.bot.config.BATCH_FILE_CAPTION,
                    keep_original=self.bot.config.KEEP_ORIGINAL_CAPTION,
                    is_batch=False,
                    auto_delete_minutes=self.bot.config.MESSAGE_DELETE_SECONDS // 60 if self.bot.config.MESSAGE_DELETE_SECONDS > 0 else None,
                    auto_delete_message=self.bot.config.AUTO_DELETE_MESSAGE
                )

                # Use telegram_api for concurrency control
                sent_msg = await telegram_api.call_api(
                    client.send_cached_media,
                    user_id,
                    file.file_id,
                    caption=caption,
                    parse_mode=CaptionFormatter.get_parse_mode(),
                    chat_id=user_id
                )

                # Schedule auto-deletion if enabled
                if self.bot.config.MESSAGE_DELETE_SECONDS > 0:
                    asyncio.create_task(self._auto_delete_message(sent_msg, self.bot.config.MESSAGE_DELETE_SECONDS))
                success_count += 1

                await asyncio.sleep(1)  # Avoid flooding

            except Exception as e:
                logger.error(f"Error sending file: {e}")
                continue

        # Batch increment retrieval count after loop (more efficient than per-file)
        if access_ctx.should_track_retrieval and success_count > 0:
            await self.bot.user_repo.increment_retrieval_count_batch(user_id, success_count)

        sent_msg = await message.reply_text(ErrorMessageFormatter.format_success(f"Sent {success_count}/{len(files)} files!"))
        # Schedule auto-delete for completion message
        if self.bot.config.MESSAGE_DELETE_SECONDS > 0 and sent_msg:
            asyncio.create_task(
                self._auto_delete_message(sent_msg, self.bot.config.MESSAGE_DELETE_SECONDS)
            )

        # Delete the command message
        await self.safe_delete(message)

    async def _send_premium_batch(self, client: Client, message: Message, batch_id: str):
        """Send premium batch files with access control"""
        user_id = message.from_user.id
        
        # Get batch link details
        batch_link = await self.bot.filestore_service.get_premium_batch_link(batch_id)
        if not batch_link:
            await message.reply_text(ErrorMessageFormatter.format_not_found("Batch link") + " or expired")
            return

        # Get user details
        user = await self.bot.user_repo.get_user(user_id)
        if not user:
            await message.reply_text(ErrorMessageFormatter.format_not_found("User") + ". Please start the bot again.")
            return

        # Check premium access with precedence rules
        global_premium_enabled = not self.bot.config.DISABLE_PREMIUM
        can_access, reason = await self.bot.filestore_service.check_premium_batch_access(
            batch_link, 
            user_id, 
            user.is_premium, 
            global_premium_enabled
        )

        if not can_access:
            await message.reply_text(reason)
            return

        # Check general user status (banned, etc.) but bypass premium checks for premium batch links
        # Premium batch links have their own access control logic above
        if user.status == UserStatus.BANNED:
            await message.reply_text(ErrorMessageFormatter.format_access_denied(user.ban_reason or 'User banned'))
            return

        sts = await message.reply("📦 <b>Processing premium batch files...</b>")

        # Send files from the batch link
        success_count, total_count = await self.bot.filestore_service.send_channel_files(
            self.bot,
            user_id,
            batch_link.source_chat_id,
            batch_link.from_msg_id,
            batch_link.to_msg_id,
            protect=batch_link.protected
        )

        await sts.delete()

        if success_count > 0:
            batch_type = "protected premium" if batch_link.protected else "premium"
            premium_msg = await message.reply_text(
                ErrorMessageFormatter.format_success("Premium Batch Transfer Completed!", title="Premium Batch Transfer Completed") + "\n"
                f"📦 Batch Type: {batch_type.title()}\n"
                f"📊 Files sent: <b>{success_count}</b>/<b>{total_count}</b>\n"
                f"💎 Premium access verified"
            )
            # Schedule auto-delete for premium batch transfer complete message
            if self.bot.config.MESSAGE_DELETE_SECONDS > 0 and premium_msg:
                asyncio.create_task(
                    self._auto_delete_message(premium_msg, self.bot.config.MESSAGE_DELETE_SECONDS)
                )
        else:
            failed_msg = await message.reply_text(ErrorMessageFormatter.format_failed("Please try again", action="to send batch files"))
            # Schedule auto-delete for error message
            if self.bot.config.MESSAGE_DELETE_SECONDS > 0 and failed_msg:
                asyncio.create_task(
                    self._auto_delete_message(failed_msg, self.bot.config.MESSAGE_DELETE_SECONDS)
                )

        # Delete the command message
        await self.safe_delete(message)
