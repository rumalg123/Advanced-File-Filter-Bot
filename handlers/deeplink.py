import asyncio
import base64

from pyrogram import Client
from pyrogram.types import Message
from sqlalchemy.orm.sync import clear

from core.utils.caption import CaptionFormatter
from core.utils.logger import get_logger
from handlers.commands_handlers.base import BaseCommandHandler
from handlers.decorators import require_subscription

logger = get_logger(__name__)


class DeepLinkHandler(BaseCommandHandler):
    """Handler for deep link parameters in /start command"""

    @require_subscription()
    async def handle_deep_link(self, client: Client, message: Message, data: str):
        """Handle deep link parameters with subscription check"""
        user_id = message.from_user.id

        # Handle different deep link types
        if data.startswith("batch_"):
            # Batch file request
            batch_id = data[6:]  # Remove 'batch_' prefix
            await self._send_batch(client, message, batch_id)

        elif data.startswith("DSTORE-"):
            # Direct store request
            await self._send_dstore_files(client, message, data[7:])

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

    async def _send_filestore_file(self, client: Client, message: Message, encoded: str):
        """Send a file from filestore link - subscription already checked by decorator"""
        user_id = message.from_user.id

        logger.info(f"Processing filestore request - User: {user_id}, Encoded: {encoded}")

        # Decode file identifier
        file_identifier, protect = self.bot.filestore_service.decode_file_identifier(encoded)

        if not file_identifier:
            await message.reply("❌ Invalid link format.")
            return

        logger.info(f"Decoded file_identifier: {file_identifier}, protect: {protect}")

        # Check user access using unified lookup
        can_access, reason, file = await self.bot.file_service.check_and_grant_access(
            user_id,
            file_identifier,
            increment=True,
            owner_id=self.bot.config.ADMINS[0] if self.bot.config.ADMINS else None
        )

        if not can_access:
            logger.warning(f"Access denied for user {user_id}: {reason}")
            await message.reply_text(f"❌ {reason}")
            return

        if not file:
            logger.error(f"File not found for identifier: {file_identifier}")
            await message.reply_text("❌ File not found.")
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
                auto_delete_minutes=delete_minutes
            )

            logger.info(f"Sending file - ID: {file.file_id}, Name: {file.file_name}")

            sent_msg = await client.send_cached_media(
                chat_id=user_id,
                file_id=file.file_id,
                caption=caption,
                protect_content=protect,
                parse_mode=CaptionFormatter.get_parse_mode()
            )

            logger.info(f"File sent successfully to user {user_id}")

            asyncio.create_task(
                self._auto_delete_message(sent_msg, delete_time)
            )

            # Delete the command message after successful send
            await message.delete()

            # Delete the command message after successful send
            await message.delete()

        except Exception as e:
            logger.error(f"Error sending file to user {user_id}: {e}", exc_info=True)
            await message.reply_text("❌ Failed to send file. Please try again.")

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
            logger.debug("Triggered in _send_dstore_files")
            logger.error(f"Failed to decode identifier: {encoded} Error: {e}")
            await message.reply("❌ Invalid link format.")
            return

        # Check access
        can_access, reason = await self.bot.user_repo.can_retrieve_file(
            user_id,
            self.bot.config.ADMINS[0] if self.bot.config.ADMINS else None
        )

        if not can_access:
            await message.reply_text(f"❌ {reason}")
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
            await message.reply_text(
                f"✅ Transfer completed!\n"
                f"Files sent: {success_count}/{total_count}"
            )
        else:
            await message.reply_text("❌ Failed to send files.")


    async def _send_all_from_search(self, client: Client, message: Message, search_key: str):
        """Send all files from search key"""
        user_id = message.from_user.id

        # Get cached search results
        cached_data = await self.bot.cache.get(search_key)
        logger.info(f"{search_key} found: {cached_data}")

        if not cached_data:
            await message.reply_text("❌ Search results expired. Please search again.")
            return

        files_data = cached_data.get('files', [])
        search_query = cached_data.get('query', '')

        if not files_data:
            await message.reply_text("❌ No files found.")
            return

        # Check access for bulk send
        can_access, reason = await self.bot.user_repo.can_retrieve_file(
            user_id,
            self.bot.config.ADMINS[0] if self.bot.config.ADMINS else None
        )

        if not can_access:
            await message.reply_text(f"❌ {reason}")
            return

        # Check quota for non-premium users
        user = await self.bot.user_repo.get_user(user_id)
        if user and not user.is_premium and not self.bot.config.DISABLE_PREMIUM:
            remaining = self.bot.config.NON_PREMIUM_DAILY_LIMIT - user.daily_retrieval_count
            if remaining < len(files_data):
                await message.reply_text(
                    f"❌ You can only retrieve {remaining} more files today. "
                    f"Upgrade to premium for unlimited access!"
                )
                return

        # Send files without progress updates (simplified)
        sending_file_msg =await message.reply_text(f"📤 Sending {len(files_data)} files...")

        success_count = 0
        for file_data in files_data:
            try:
                file_unique_id = file_data['file_unique_id']
                file = await self.bot.media_repo.find_file(file_unique_id)

                if not file:
                    logger.warning(f"File {file_unique_id} not found.")
                    continue

                caption = CaptionFormatter.format_file_caption(
                    file=file,
                    custom_caption=self.bot.config.CUSTOM_FILE_CAPTION,
                    batch_caption=self.bot.config.BATCH_FILE_CAPTION,
                    keep_original=self.bot.config.KEEP_ORIGINAL_CAPTION,
                    is_batch=False,  # These are NOT batch files, they're from search
                    auto_delete_minutes=self.bot.config.MESSAGE_DELETE_SECONDS // 60 if self.bot.config.MESSAGE_DELETE_SECONDS > 0 else None
                )
                await client.send_cached_media(
                    chat_id=user_id,
                    file_id=file.file_id,
                    caption=caption,
                    parse_mode=CaptionFormatter.get_parse_mode()
                )
                success_count += 1

                # Update retrieval count for non-premium
                if not user.is_premium and not self.bot.config.DISABLE_PREMIUM:
                    await self.bot.user_repo.increment_retrieval_count(user_id)

                await asyncio.sleep(1)  # Avoid flooding

            except Exception as e:
                logger.error(f"Error sending file: {e}")
                continue

        await message.reply_text(f"✅ Sent {success_count}/{len(files_data)} files!")
        await client.delete_messages(
            chat_id=sending_file_msg.chat.id,
            message_ids=sending_file_msg.id
        )

        # Delete the command message
        await message.delete()

    async def _send_batch(self, client: Client, message: Message, batch_id: str):
        """Send batch files from a batch ID"""
        user_id = message.from_user.id

        # Get batch data from filestore service
        batch_data = await self.bot.filestore_service.get_batch_data(client, batch_id)

        if not batch_data:
            await message.reply_text("❌ Batch not found or expired.")
            return

        # Check access
        can_access, reason = await self.bot.user_repo.can_retrieve_file(
            user_id,
            self.bot.config.ADMINS[0] if self.bot.config.ADMINS else None
        )

        if not can_access:
            await message.reply_text(f"❌ {reason}")
            return

        # Send batch files
        success_count, total_count = await self.bot.filestore_service.send_batch_files(
            client,
            user_id,
            batch_data
        )

        if success_count > 0:
            await message.reply_text(
                f"✅ Batch transfer completed!\n"
                f"Files sent: {success_count}/{total_count}"
            )
        else:
            await message.reply_text("❌ Failed to send batch files.")

    async def _send_all_files(self, client: Client, message: Message, key: str, file_type: str):
        """Send all files of a specific type"""
        user_id = message.from_user.id

        # Reconstruct search query from key
        search_query = key.replace('_', ' ')

        # Check access
        can_access, reason = await self.bot.user_repo.can_retrieve_file(
            user_id,
            self.bot.config.ADMINS[0] if self.bot.config.ADMINS else None
        )

        if not can_access:
            await message.reply_text(f"❌ {reason}")
            return

        # Search for files with specific type
        from repositories.media import FileType
        file_type_enum = None
        if file_type:
            try:
                file_type_enum = FileType(file_type.lower())
            except ValueError:
                await message.reply_text("❌ Invalid file type.")
                return

        # Get all files (using a higher limit)
        files, _, total, has_access = await self.bot.file_service.search_files_with_access_check(
            user_id=user_id,
            query=search_query,
            chat_id=user_id,
            file_type=file_type,
            offset=0,
            limit=100  # Adjust based on your needs
        )

        if not has_access:
            await message.reply_text("❌ Access denied.")
            return

        if not files:
            await message.reply_text("❌ No files found.")
            return

        # Send files
        await message.reply_text(f"📤 Sending {len(files)} {file_type or 'all'} files...")

        success_count = 0
        for file in files:
            try:
                caption = CaptionFormatter.format_file_caption(
                    file=file,
                    custom_caption=self.bot.config.CUSTOM_FILE_CAPTION,
                    batch_caption=self.bot.config.BATCH_FILE_CAPTION,
                    keep_original=self.bot.config.KEEP_ORIGINAL_CAPTION,
                    is_batch=False,
                    auto_delete_minutes=self.bot.config.MESSAGE_DELETE_SECONDS // 60 if self.bot.config.MESSAGE_DELETE_SECONDS > 0 else None
                )

                await client.send_cached_media(
                    chat_id=user_id,
                    file_id=file.file_id,
                    caption=caption,
                    parse_mode=CaptionFormatter.get_parse_mode()
                )
                success_count += 1

                # Update retrieval count for non-premium
                user = await self.bot.user_repo.get_user(user_id)
                if user and not user.is_premium and not self.bot.config.DISABLE_PREMIUM:
                    await self.bot.user_repo.increment_retrieval_count(user_id)

                await asyncio.sleep(1)  # Avoid flooding

            except Exception as e:
                logger.error(f"Error sending file: {e}")
                continue

        await message.reply_text(f"✅ Sent {success_count}/{len(files)} files!")

        # Delete the command message
        await message.delete()