import asyncio
import base64

from pyrogram import Client
from pyrogram.errors import FloodWait, UserIsBlocked
from pyrogram.types import CallbackQuery

from core.cache.config import CacheKeyGenerator
from core.utils.caption import CaptionFormatter
from core.utils.logger import get_logger
from core.utils.validators import is_original_requester, is_private_chat, skip_subscription_check
from handlers.commands_handlers.base import BaseCommandHandler
from handlers.decorators import check_ban

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
    async def handle_file_callback(self, client: Client, query: CallbackQuery):
        """Handle file request callbacks - redirect to PM from groups"""
        callback_user_id = query.from_user.id
        logger.info(f"handle_file_callback called for user {callback_user_id}, data: {query.data}")

        # Extract file identifier and original user_id
        parts = query.data.split('#', 2)
        logger.info(f"Callback data parts after split: {parts}")
        if len(parts) < 3:
            _, file_identifier = parts
            original_user_id = callback_user_id  # Assume current user
            logger.info(f"No original_user_id in callback, using current user: {callback_user_id}")
        else:
            _, file_identifier, original_user_id = parts
            original_user_id = int(original_user_id)
            logger.info(f"Original user_id from callback: {original_user_id}")

        logger.info(f"File identifier extracted: {file_identifier}")

        # Check if the callback user is the original requester
        if original_user_id and not is_original_requester(callback_user_id, original_user_id):
            await query.answer("❌ You cannot interact with this message!", show_alert=True)
            return

        # If in group, redirect to PM
        if not is_private_chat(query):
            bot_username = self.bot.bot_username
            pm_link = f"https://t.me/{bot_username}?start={self.encode_file_identifier(file_identifier)}"

            await query.answer(
                "📩 Click here to get the file in PM",
                url=pm_link
            )
            return

        # We're in PM now, check subscription
        logger.info(f"In PM, checking subscription for user {callback_user_id}")
        if self.bot.config.AUTH_CHANNEL or getattr(self.bot.config, 'AUTH_GROUPS', []):
            # Skip subscription check for admins and auth users
            skip_sub_check = skip_subscription_check(
                callback_user_id,
                self.bot.config.ADMINS,
                getattr(self.bot.config, 'AUTH_USERS', [])
            )

            if not skip_sub_check:
                is_subscribed = await self.bot.subscription_manager.is_subscribed(
                    client, callback_user_id
                )

                if not is_subscribed:
                    # Send subscription required message
                    await self._send_subscription_message(client, query, file_identifier)
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
        logger.info(f"Calling check_and_grant_access for user {callback_user_id}, file: {file_identifier}, increment=True")
        logger.info(f"ADMINS: {self.bot.config.ADMINS}, DISABLE_PREMIUM: {self.bot.config.DISABLE_PREMIUM}")
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
                auto_delete_minutes=delete_minutes,
                auto_delete_message = self.bot.config.AUTO_DELETE_MESSAGE
            )

            sent_msg = await client.send_cached_media(
                chat_id=callback_user_id,
                file_id=file.file_id,
                caption=caption,
                parse_mode=CaptionFormatter.get_parse_mode()
            )

            await query.answer("✅ File sent!", show_alert=False)

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
    async def handle_sendall_callback(self, client: Client, query: CallbackQuery):
        """Handle send all files callback - redirect to PM from groups"""
        callback_user_id = query.from_user.id
        logger.info(f"handle_sendall_callback called for user {callback_user_id}, data: {query.data}")

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

        # If in group, redirect to PM
        if not is_private_chat(query):
            bot_username = self.bot.bot_username
            pm_link = f"https://t.me/{bot_username}?start=sendall_{search_key}"

            await query.answer(
                "📩 Click here to get all files in PM",
                url=pm_link
            )
            return

        # We're in PM now, check subscription
        if self.bot.config.AUTH_CHANNEL or getattr(self.bot.config, 'AUTH_GROUPS', []):
            # Skip subscription check for admins and auth users
            skip_sub_check = skip_subscription_check(
                callback_user_id, 
                self.bot.config.ADMINS, 
                getattr(self.bot.config, 'AUTH_USERS', [])
            )

            if not skip_sub_check:
                is_subscribed = await self.bot.subscription_manager.is_subscribed(
                    client, callback_user_id
                )

                if not is_subscribed:
                    # Send subscription required message
                    await self._send_subscription_message_for_sendall(client, query, search_key)
                    return

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

        # Get cached search results with debug logging
        cached_data = await self.bot.cache.get(search_key)
        
        if not cached_data:
            logger.warning(f"Search results expired or not found for key: {search_key}")
            
            # Check if the key exists at all
            key_exists = await self.bot.cache.exists(search_key)
            logger.debug(f"Cache key exists check for {search_key}: {key_exists}")
            
            # Check TTL of the key if it exists
            if key_exists:
                ttl = await self.bot.cache.ttl(search_key)
                logger.debug(f"Cache key TTL for {search_key}: {ttl}")
            
            await query.answer("❌ Search results expired. Please search again.", show_alert=True)
            return
        
        logger.debug(f"Retrieved cached search results for key: {search_key}, files count: {len(cached_data.get('files', []))}")

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
        # Force fresh fetch from DB, not cache, to get accurate count
        await self.bot.user_repo.cache.delete(CacheKeyGenerator.user(user_id))
        user = await self.bot.user_repo.get_user(user_id)

        # Check if user is admin or owner
        is_admin = user_id in self.bot.config.ADMINS if self.bot.config.ADMINS else False
        owner_id = self.bot.config.ADMINS[0] if self.bot.config.ADMINS else None
        is_owner = user_id == owner_id

        # Only check quota for non-premium, non-admin, non-owner users
        if user and not user.is_premium and not self.bot.config.DISABLE_PREMIUM and not is_admin and not is_owner:
            remaining = self.bot.config.NON_PREMIUM_DAILY_LIMIT - user.daily_retrieval_count
            if remaining < len(files_data):
                await query.answer(
                    f"❌ You can only retrieve {remaining} more files today. "
                    f"Upgrade to premium for unlimited access!",
                    show_alert=True
                )
                return

        # Start sending files to PM
        await query.answer(f"📤 Sending {len(files_data)} files...", show_alert=False)

        # Send status message to PM
        try:
            status_msg = await client.send_message(
                chat_id=user_id,
                text=(
                    f"📤 <b>Sending Files</b>\n"
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

        # Initialize these variables outside the loop to avoid uninitialized variable warnings
        delete_time = self.bot.config.MESSAGE_DELETE_SECONDS
        delete_minutes = delete_time // 60
        file = None

        for idx, file_data in enumerate(files_data):
            try:
                file_unique_id = file_data['file_unique_id']

                # Get full file details from database
                file = await self.bot.media_repo.find_file(file_unique_id)

                if not file:
                    failed_count += 1
                    continue

                caption = CaptionFormatter.format_file_caption(
                    file=file,
                    custom_caption=self.bot.config.CUSTOM_FILE_CAPTION,
                    batch_caption=self.bot.config.BATCH_FILE_CAPTION,
                    keep_original=self.bot.config.KEEP_ORIGINAL_CAPTION,
                    is_batch=False,  # These are individual files from search, not batch
                    auto_delete_minutes=delete_minutes if delete_time > 0 else None,
                    auto_delete_message=self.bot.config.AUTO_DELETE_MESSAGE
                )

                sent_msg = await client.send_cached_media(
                    chat_id=user_id,
                    file_id=file.file_id,
                    caption=caption,
                    parse_mode=CaptionFormatter.get_parse_mode()
                )

                sent_messages.append(sent_msg)
                success_count += 1

                # Note: We'll increment all at once after the loop to avoid race conditions

                # Update progress every 5 files
                if (idx + 1) % 5 == 0 or (idx + 1) == len(files_data):
                    try:
                        await status_msg.edit_text(
                            f"📤 <b>Sending Files</b>\n"
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
                # Retry the current file (only if file was successfully fetched)
                if file:
                    try:
                        caption = CaptionFormatter.format_file_caption(
                            file=file,
                            custom_caption=self.bot.config.CUSTOM_FILE_CAPTION,
                            batch_caption=self.bot.config.BATCH_FILE_CAPTION,
                            keep_original=self.bot.config.KEEP_ORIGINAL_CAPTION,
                            is_batch=False,
                            auto_delete_minutes=delete_minutes if delete_time > 0 else None,
                            auto_delete_message=self.bot.config.AUTO_DELETE_MESSAGE
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
                else:
                    failed_count += 1

            except Exception as e:
                logger.error(f"Error sending file: {e}")
                failed_count += 1

        # Increment retrieval count for all successfully sent files at once (batch operation)
        # Only increment for non-premium, non-admin, non-owner users
        is_admin = user_id in self.bot.config.ADMINS if self.bot.config.ADMINS else False
        owner_id = self.bot.config.ADMINS[0] if self.bot.config.ADMINS else None
        is_owner = user_id == owner_id

        if success_count > 0 and user and not user.is_premium and not self.bot.config.DISABLE_PREMIUM and not is_admin and not is_owner:
            await self.bot.user_repo.increment_retrieval_count_batch(user_id, success_count)

        # Final status
        final_text = (
            f"✅ <b>Transfer Complete!</b>\n"
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

    async def _send_subscription_message(self, client: Client, query: CallbackQuery, file_identifier: str):
        """Send subscription required message for file callback"""
        from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        user_id = query.from_user.id

        # Build buttons for required subscriptions
        buttons = []

        # AUTH_CHANNEL button
        if self.bot.config.AUTH_CHANNEL:
            try:
                chat_link = await self.bot.subscription_manager.get_chat_link(
                    client, self.bot.config.AUTH_CHANNEL
                )
                chat = await client.get_chat(self.bot.config.AUTH_CHANNEL)
                channel_name = chat.title or "Updates Channel"

                buttons.append([
                    InlineKeyboardButton(
                        f"📢 Join {channel_name}",
                        url=chat_link
                    )
                ])
            except Exception as e:
                logger.error(f"Error creating AUTH_CHANNEL button: {e}")

        # AUTH_GROUPS buttons
        if hasattr(self.bot.config, 'AUTH_GROUPS') and self.bot.config.AUTH_GROUPS:
            for group_id in self.bot.config.AUTH_GROUPS:
                try:
                    chat_link = await self.bot.subscription_manager.get_chat_link(
                        client, group_id
                    )
                    chat = await client.get_chat(group_id)
                    group_name = chat.title or "Required Group"

                    buttons.append([
                        InlineKeyboardButton(
                            f"👥 Join {group_name}",
                            url=chat_link
                        )
                    ])
                except Exception as e:
                    logger.error(f"Error creating AUTH_GROUP button for {group_id}: {e}")

        # Add "Try Again" button
        buttons.append([
            InlineKeyboardButton(
                "🔄 Try Again",
                callback_data=f"checksub#{user_id}#file#{file_identifier}"
            )
        ])

        message_text = (
            "🔒 <b>Subscription Required</b>\n"
            "You need to join our channel(s) to get files.\n"
            "Please join the required channel(s) and try again."
        )

        await query.answer("🔒 Join our channel(s) first!", show_alert=True)

        try:
            await query.message.reply_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(buttons),
                disable_web_page_preview=True
            )
        except:
            pass

    async def _send_subscription_message_for_sendall(self, client: Client, query: CallbackQuery, search_key: str):
        """Send subscription required message for sendall callback"""
        from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        user_id = query.from_user.id

        # Build buttons for required subscriptions
        buttons = []

        # AUTH_CHANNEL button
        if self.bot.config.AUTH_CHANNEL:
            try:
                chat_link = await self.bot.subscription_manager.get_chat_link(
                    client, self.bot.config.AUTH_CHANNEL
                )
                chat = await client.get_chat(self.bot.config.AUTH_CHANNEL)
                channel_name = chat.title or "Updates Channel"

                buttons.append([
                    InlineKeyboardButton(
                        f"📢 Join {channel_name}",
                        url=chat_link
                    )
                ])
            except Exception as e:
                logger.error(f"Error creating AUTH_CHANNEL button: {e}")

        # AUTH_GROUPS buttons
        if hasattr(self.bot.config, 'AUTH_GROUPS') and self.bot.config.AUTH_GROUPS:
            for group_id in self.bot.config.AUTH_GROUPS:
                try:
                    chat_link = await self.bot.subscription_manager.get_chat_link(
                        client, group_id
                    )
                    chat = await client.get_chat(group_id)
                    group_name = chat.title or "Required Group"

                    buttons.append([
                        InlineKeyboardButton(
                            f"👥 Join {group_name}",
                            url=chat_link
                        )
                    ])
                except Exception as e:
                    logger.error(f"Error creating AUTH_GROUP button for {group_id}: {e}")

        # Add "Try Again" button
        buttons.append([
            InlineKeyboardButton(
                "🔄 Try Again",
                callback_data=f"checksub#{user_id}#sendall#{search_key}"
            )
        ])

        message_text = (
            "🔒 <b>Subscription Required</b>\n"
            "You need to join our channel(s) to get files.\n"
            "Please join the required channel(s) and try again."
        )

        await query.answer("🔒 Join our channel(s) first!", show_alert=True)

        try:
            await query.message.reply_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(buttons),
                disable_web_page_preview=True
            )
        except:
            pass