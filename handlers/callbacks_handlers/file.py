import asyncio
import base64

from pyrogram import Client, enums
from pyrogram.errors import FloodWait, UserIsBlocked
from pyrogram.types import CallbackQuery

from core.utils.caption import CaptionFormatter
from handlers.commands_handlers.base import BaseCommandHandler
from handlers.decorators import require_subscription, check_ban

from core.utils.logger import get_logger
logger = get_logger(__name__)


class FileCallbackHandler(BaseCommandHandler):
    """Handler for file-related callbacks"""


    def encode_file_identifier(self, file_identifier: str, protect: bool = False) -> str:
        """
        Encode file identifier (file_ref) to shareable string
        Now uses file_ref for consistency
        """
        prefix = 'filep_' if protect else 'file_'
        string = prefix + file_identifier
        return base64.urlsafe_b64encode(string.encode("ascii")).decode().strip("=")
    @check_ban()
    @require_subscription()
    async def handle_file_callback(self, client: Client, query: CallbackQuery):
        """Handle file request callbacks - always send to PM"""
        callback_user_id = query.from_user.id

        # Extract file identifier and original user_id
        parts = query.data.split('#', 2)
        if len(parts) < 3:
            _, file_identifier = parts
            original_user_id = callback_user_id  # Assume current user
        else:
            _, file_identifier, original_user_id = parts
            original_user_id = int(original_user_id)

        # Check if the callback user is the original requester
        if original_user_id and callback_user_id != original_user_id:
            await query.answer("❌ You cannot interact with this message!", show_alert=True)
            return

        if query.message.chat.type != enums.ChatType.PRIVATE:
            bot_username = self.bot.bot_username
            pm_link = f"https://t.me/{bot_username}?start={self.encode_file_identifier(file_identifier)}"

            await query.answer(
                url=pm_link
            )
            return

        # Check if user has started the bot
        try:
            # Try to get user info to check if bot is started
            await client.get_chat(callback_user_id)
        except UserIsBlocked:
            await query.answer(
                "❌ Please start the bot first!\n"
                f"Click here: @{self.bot.bot_username}",
                show_alert=True
            )
            return
        except Exception:
            pass

        # Check access
        can_access, reason, file = await self.bot.file_service.check_and_grant_access(
            callback_user_id,
            file_identifier,
            increment=True,
            owner_id=self.bot.config.ADMINS[0] if self.bot.config.ADMINS else None
        )

        if not can_access:
            await query.answer(reason, show_alert=True)
            return

        if not file:
            await query.answer("❌ File not found.", show_alert=True)
            return

        # Send file to PM
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

            sent_msg = await client.send_cached_media(
                chat_id=callback_user_id,
                file_id=file.file_id,
                caption=caption,
                parse_mode=CaptionFormatter.get_parse_mode()
            )

            #await query.answer("✅ File sent to your PM!", show_alert=True)

            # Schedule deletion
            asyncio.create_task(
                self._auto_delete_message(sent_msg, delete_time)
            )

        except UserIsBlocked:
            await query.answer(
                "❌ Please start the bot first!\n"
                f"Click here: @{self.bot.bot_username}",
                show_alert=True
            )
        except Exception as e:
            logger.error(f"Error sending file via callback: {e}")
            await query.answer("❌ Error sending file. Try again.", show_alert=True)

    @check_ban()
    @require_subscription()
    async def handle_sendall_callback(self, client: Client, query: CallbackQuery):
        """Handle send all files callback - always send to PM"""
        callback_user_id = query.from_user.id

        # Extract search key and original user_id
        parts = query.data.split('#', 2)
        if len(parts) < 3:
            _, search_key = parts
            original_user_id = callback_user_id
        else:
            _, search_key, original_user_id = parts
            original_user_id = int(original_user_id)

        # Check ownership
        if original_user_id and callback_user_id != original_user_id:
            await query.answer("❌ You cannot interact with this message!", show_alert=True)
            return

        if query.message.chat.type != enums.ChatType.PRIVATE:
            bot_username = self.bot.bot_username
            pm_link = f"https://t.me/{bot_username}?start=sendall_{search_key}"

            await query.answer(
                url=pm_link
            )

            # from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            # await query.message.edit_reply_markup(
            #     InlineKeyboardMarkup([[
            #         InlineKeyboardButton("📱 Get All Files in PM", url=pm_link)
            #     ]])
            # )
            # return

        user_id = callback_user_id

        # Check if user has started the bot
        try:
            await client.get_chat(user_id)
        except UserIsBlocked:
            await query.answer(
                "❌ Please start the bot first!\n"
                f"Click here: @{self.bot.bot_username}",
                show_alert=True
            )
            return
        except Exception:
            pass

        # Get cached search results
        cached_data = await self.bot.cache.get(search_key)

        if not cached_data:
            await query.answer("❌ Search results expired. Please search again.", show_alert=True)
            return

        files_data = cached_data.get('files', [])
        search_query = cached_data.get('query', '')

        if not files_data:
            await query.answer("❌ No files found.", show_alert=True)
            return

        # Check access for bulk send
        can_access, reason = await self.bot.user_repo.can_retrieve_file(
            user_id,
            self.bot.config.ADMINS[0] if self.bot.config.ADMINS else None
        )

        if not can_access:
            await query.answer(f"❌ {reason}", show_alert=True)
            return

        # Check if user has enough quota for all files
        user = await self.bot.user_repo.get_user(user_id)
        if user and not user.is_premium and not self.bot.config.DISABLE_PREMIUM:
            remaining = self.bot.config.NON_PREMIUM_DAILY_LIMIT - user.daily_retrieval_count
            if remaining < len(files_data):
                await query.answer(
                    f"❌ You can only retrieve {remaining} more files today. "
                    f"Upgrade to premium for unlimited access!",
                    show_alert=True
                )
                return

        # Start sending files to PM
        #await query.answer(f"📤 Sending {len(files_data)} files to your PM...", show_alert=True)

        # Send status message to PM
        try:
            status_msg = await client.send_message(
                chat_id=user_id,
                text=(
                    f"📤 **Sending Files**\n\n"
                    f"Query: {search_query}\n"
                    f"Total Files: {len(files_data)}\n"
                    f"Progress: 0/{len(files_data)}"
                )
            )
        except UserIsBlocked:
            await query.answer(
                "❌ Please start the bot first!\n"
                f"Click here: @{self.bot.bot_username}",
                show_alert=True
            )
            return

        success_count = 0
        failed_count = 0
        sent_messages = []  # Track sent messages for auto-deletion

        for idx, file_data in enumerate(files_data):
            try:
                file_unique_id = file_data['file_unique_id']

                # Get full file details from database
                file = await self.bot.media_repo.find_file(file_unique_id)

                if not file:
                    failed_count += 1
                    continue

                # Send file
                delete_time = self.bot.config.MESSAGE_DELETE_SECONDS
                delete_minutes = delete_time // 60

                caption = CaptionFormatter.format_file_caption(
                    file=file,
                    custom_caption=self.bot.config.CUSTOM_FILE_CAPTION,
                    batch_caption=self.bot.config.BATCH_FILE_CAPTION,
                    keep_original=self.bot.config.KEEP_ORIGINAL_CAPTION,
                    is_batch=False,  # These are individual files from search, not batch
                    auto_delete_minutes=delete_minutes if delete_time > 0 else None
                )

                sent_msg = await client.send_cached_media(
                    chat_id=user_id,
                    file_id=file.file_id,
                    caption=caption,
                    parse_mode=CaptionFormatter.get_parse_mode()
                )

                sent_messages.append(sent_msg)
                success_count += 1

                if user and not user.is_premium and not self.bot.config.DISABLE_PREMIUM:
                    await self.bot.user_repo.increment_retrieval_count(user_id)

                # Update progress every 5 files
                if (idx + 1) % 5 == 0 or (idx + 1) == len(files_data):
                    try:
                        await status_msg.edit_text(
                            f"📤 **Sending Files**\n\n"
                            f"Query: {search_query}\n"
                            f"Total Files: {len(files_data)}\n"
                            f"Progress: {idx + 1}/{len(files_data)}\n"
                            f"✅ Success: {success_count}\n"
                            f"❌ Failed: {failed_count}"
                        )
                    except:
                        pass

                # Small delay to avoid flooding
                await asyncio.sleep(1)

            except FloodWait as e:
                logger.warning(f"FloodWait: sleeping for {e.value} seconds")
                await asyncio.sleep(e.value)
                # Retry the current file
                try:
                    caption = CaptionFormatter.format_file_caption(
                        file=file,
                        custom_caption=self.bot.config.CUSTOM_FILE_CAPTION,
                        batch_caption=self.bot.config.BATCH_FILE_CAPTION,
                        keep_original=self.bot.config.KEEP_ORIGINAL_CAPTION,
                        is_batch=False,
                        auto_delete_minutes=delete_minutes if delete_time > 0 else None
                    )

                    sent_msg = await client.send_cached_media(
                        chat_id=user_id,
                        file_id=file.file_id,
                        caption=caption,
                        parse_mode=CaptionFormatter.get_parse_mode()
                    )
                    sent_messages.append(sent_msg)
                    success_count += 1
                except:
                    failed_count += 1

            except Exception as e:
                logger.error(f"Error sending file: {e}")
                failed_count += 1

        # Final status
        final_text = (
            f"✅ **Transfer Complete!**\n\n"
            f"Query: {search_query}\n"
            f"Total Files: {len(files_data)}\n"
            f"✅ Sent: {success_count}\n"
        )

        if failed_count > 0:
            final_text += f"❌ Failed: {failed_count}\n"

        # Add auto-delete notice if enabled
        if self.bot.config.MESSAGE_DELETE_SECONDS > 0:
            delete_minutes = self.bot.config.MESSAGE_DELETE_SECONDS // 60
            final_text += f"\n⏱ Files will be auto-deleted after {delete_minutes} minutes"

        await status_msg.edit_text(final_text)

        # Schedule auto-deletion for all sent messages
        if self.bot.config.MESSAGE_DELETE_SECONDS > 0:
            for sent_msg in sent_messages:
                asyncio.create_task(
                    self._auto_delete_message(sent_msg, self.bot.config.MESSAGE_DELETE_SECONDS)
                )

