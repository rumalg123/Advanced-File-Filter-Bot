import asyncio
import base64
from typing import Set

from pyrogram import Client
from pyrogram.errors import FloodWait, UserIsBlocked, QueryIdInvalid
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup

from core.utils.button_builder import ButtonBuilder
from core.utils.caption import CaptionFormatter
from core.utils.error_formatter import ErrorMessageFormatter
from core.utils.logger import get_logger
from core.utils.messages import MessageHelper
from core.utils.pagination import resolve_search_query_reference
from core.utils.telegram_api import telegram_api
from core.utils.validators import (
    is_original_requester, is_private_chat, skip_subscription_check,
    is_admin, extract_user_id
)
from handlers.commands_handlers.base import BaseCommandHandler
from handlers.decorators import check_ban

logger = get_logger(__name__)


class FileCallbackHandler(BaseCommandHandler):
    """Handler for file-related callbacks"""

    def __init__(self, bot):
        super().__init__(bot)
        # Track pending auto-delete tasks for cleanup on shutdown
        self._pending_delete_tasks: Set[asyncio.Task] = set()

    def _track_task(self, coro) -> asyncio.Task:
        """Create a tracked task that auto-removes from pending set on completion"""
        task = asyncio.create_task(coro)
        self._pending_delete_tasks.add(task)
        task.add_done_callback(self._pending_delete_tasks.discard)
        return task

    def _feature_file_markup(self, file):
        """Build opt-in post-delivery actions without changing default delivery."""
        config = self.bot.config
        rows = []
        identifier = file.file_unique_id

        def callback(action: str):
            value = f"feature#{action}#{identifier}"
            return value if len(value.encode('utf-8')) <= 64 else None

        favorite_callback = callback('fav')
        unfavorite_callback = callback('unfav')
        if getattr(config, 'FEATURE_FAVORITES', False):
            favorite_buttons = []
            if favorite_callback:
                favorite_buttons.append(ButtonBuilder.action_button(
                    "⭐ Favorite", callback_data=favorite_callback
                ))
            if unfavorite_callback:
                favorite_buttons.append(ButtonBuilder.action_button(
                    "💔 Remove", callback_data=unfavorite_callback
                ))
            if favorite_buttons:
                rows.append(favorite_buttons)
        if getattr(config, 'FEATURE_RECOMMENDATION_FEEDBACK', False):
            feedback_buttons = []
            more_callback = callback('more')
            less_callback = callback('less')
            if more_callback:
                feedback_buttons.append(ButtonBuilder.action_button(
                    "👍 More like this", callback_data=more_callback
                ))
            if less_callback:
                feedback_buttons.append(ButtonBuilder.action_button(
                    "👎 Not interested", callback_data=less_callback
                ))
            if feedback_buttons:
                rows.append(feedback_buttons)
        report_callback = callback('report')
        longest_reason_callback = callback('reason_incorrect')
        if (
            getattr(config, 'FEATURE_FILE_REPORTS', False)
            and report_callback
            and longest_reason_callback
        ):
            rows.append([
                ButtonBuilder.action_button(
                    "🚩 Report", callback_data=report_callback
                )
            ])
        return InlineKeyboardMarkup(rows) if rows else None

    def _broken_file_report_markup(self, file):
        """Offer a report action when Telegram rejects an indexed file."""
        if not getattr(self.bot.config, 'FEATURE_FILE_REPORTS', False) or not file:
            return None
        report_data = f"feature#report#{file.file_unique_id}"
        reason_data = f"feature#reason_incorrect#{file.file_unique_id}"
        if max(len(report_data.encode()), len(reason_data.encode())) > 64:
            return None
        return InlineKeyboardMarkup([[
            ButtonBuilder.action_button(
                "🚩 Report broken file", callback_data=report_data
            )
        ]])

    async def cancel_pending_tasks(self):
        """Cancel all pending auto-delete tasks (call during shutdown)"""
        if self._pending_delete_tasks:
            logger.info(f"Cancelling {len(self._pending_delete_tasks)} pending delete tasks")
            for task in self._pending_delete_tasks:
                task.cancel()
            await asyncio.gather(*self._pending_delete_tasks, return_exceptions=True)
            self._pending_delete_tasks.clear()

    def encode_file_identifier(self, file_identifier: str, protect: bool = False) -> str:
        """
        Encode file identifier (file_ref) to shareable string
        Now uses file_ref for consistency
        """
        prefix = 'filep_' if protect else 'file_'
        string = prefix + file_identifier
        return base64.urlsafe_b64encode(string.encode("ascii")).decode().strip("=")

    @staticmethod
    def parse_file_callback(data: str, callback_user_id: int):
        """Parse legacy and session-aware file callback data."""
        parts = data.split('#', 3)
        if len(parts) < 2 or parts[0] != 'file' or not parts[1]:
            raise ValueError("invalid file callback")

        file_identifier = parts[1]
        original_user_id = callback_user_id
        query_reference = None

        if len(parts) >= 3 and parts[2]:
            if parts[2].startswith('@'):
                query_reference = parts[2]
            else:
                original_user_id = int(parts[2])

        if len(parts) == 4 and parts[3]:
            query_reference = parts[3]

        return file_identifier, original_user_id, query_reference

    @check_ban()
    async def handle_file_callback(self, client: Client, query: CallbackQuery):
        """Handle file request callbacks - redirect to PM from groups"""
        callback_user_id = query.from_user.id

        # Extract the file, owner, and immutable originating search reference.
        try:
            file_identifier, original_user_id, query_reference = self.parse_file_callback(
                query.data,
                callback_user_id
            )
        except (ValueError, IndexError) as e:
            logger.warning(f"Invalid callback data format: {query.data}, error: {e}")
            await query.answer(ErrorMessageFormatter.format_invalid("request format", plain_text=True), show_alert=True)
            return

        # Check if the callback user is the original requester
        if original_user_id and not is_original_requester(callback_user_id, original_user_id):
            await query.answer(ErrorMessageFormatter.format_access_denied("You cannot interact with this message", plain_text=True), show_alert=True)
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
            await telegram_api.call_api(
                client.get_chat,
                callback_user_id,
                chat_id=callback_user_id
            )
        except UserIsBlocked:
            await query.answer(
                ErrorMessageFormatter.format_error(
                    "Please start the bot first!",
                    plain_text=True
                ) + "\n"
                f"Click here: @{self.bot.bot_username}",
                show_alert=True
            )
            return
        except Exception:
            pass

        # Check access
        can_access, reason, file, reserved_quota = await self.bot.file_service.check_and_grant_access(
            callback_user_id,
            file_identifier,
            increment=True,
            owner_id=self.bot.config.ADMINS[0] if self.bot.config.ADMINS else None
        )

        if not can_access:
            # Check if it's daily limit
            if reason and "Daily limit reached" in reason:
                # Show proper daily limit message
                user = await self.bot.user_repo.get_user(callback_user_id)
                if user:
                    daily_limit = self.bot.user_repo.daily_limit
                    message = f"⚠️ Daily limit reached ({user.daily_retrieval_count}/{daily_limit}). Upgrade to premium for unlimited access!"
                else:
                    message = "⚠️ Daily limit reached. Upgrade to premium for unlimited access!"
            else:
                # Use the reason as-is (already formatted)
                message = reason
            await query.answer(message, show_alert=True)
            return

        if not file:
            await query.answer(ErrorMessageFormatter.format_not_found("File", plain_text=True), show_alert=True)
            return
        
        query_answered = False
        try:
            await query.answer("⏳ Sending file...", show_alert=False)
            query_answered = True
        except QueryIdInvalid:
            # Query already expired, we'll send status via message instead
            logger.warning(f"Query expired for user {callback_user_id}, will send message instead")
            query_answered = False
        except Exception as e:
            logger.warning(f"Could not answer query for user {callback_user_id}: {e}")
            query_answered = False

        # Send file to PM. The access service has atomically reserved one quota
        # slot when needed; return it unless Telegram confirms delivery.
        delivery_succeeded = False
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

            # Use telegram_api for concurrency control
            sent_msg = await telegram_api.call_api(
                client.send_cached_media,
                callback_user_id,  # positional arg for send_cached_media
                file.file_id,
                caption=caption,
                parse_mode=CaptionFormatter.get_parse_mode(),
                reply_markup=self._feature_file_markup(file),
                chat_id=callback_user_id  # for call_api rate limiting
            )
            delivery_succeeded = True
            # Schedule deletion with task tracking for cleanup
            self._track_task(
                self._auto_delete_message(sent_msg, delete_time)
            )
            
            # Track file click for recommendations (non-blocking)
            if hasattr(self.bot, 'recommendation_service') and self.bot.recommendation_service:
                try:
                    originating_query = ""
                    if query_reference:
                        originating_query = await resolve_search_query_reference(
                            self.bot.cache,
                            query_reference,
                            original_user_id
                        ) or ""

                    await self.bot.recommendation_service.track_file_click(
                        callback_user_id,
                        originating_query,
                        file.file_unique_id
                    )
                except Exception as e:
                    logger.debug(f"Error tracking file click for recommendations: {e}")

            feature_service = getattr(self.bot, 'feature_service', None)
            if feature_service:
                await feature_service.record_recent_file(
                    callback_user_id, file.file_unique_id
                )


        except UserIsBlocked:

            logger.error(f"User {callback_user_id} has blocked the bot")

            # Send error message only if query wasn't answered

            if not query_answered:

                try:

                    await telegram_api.call_api(

                        client.send_message,

                        callback_user_id,

                        ErrorMessageFormatter.format_error("Please start the bot first!") + f"\nClick here: @{self.bot.bot_username}",

                        chat_id=callback_user_id

                    )

                except Exception as e:

                    logger.error(f"Could not send blocked message to {callback_user_id}: {e}")


        except Exception as e:

            logger.error(f"Error sending file via callback: {e}")

            # Send error message using call_api

            try:

                await telegram_api.call_api(

                    client.send_message,

                    callback_user_id,

                    ErrorMessageFormatter.format_error("Error sending file. Please try again."),

                    reply_markup=self._broken_file_report_markup(file),

                    chat_id=callback_user_id

                )

            except Exception as msg_error:

                logger.error(f"Could not send error message to user {callback_user_id}: {msg_error}")

        finally:
            if reserved_quota and not delivery_succeeded:
                await asyncio.shield(
                    self.bot.user_repo.release_quota(callback_user_id, reserved_quota)
                )

    @check_ban()
    async def handle_sendall_callback(self, client: Client, query: CallbackQuery):
        """Handle send all files callback - redirect to PM from groups"""
        callback_user_id = query.from_user.id

        # Extract search key and original user_id
        try:
            parts = query.data.split('#', 2)
            if len(parts) < 2:
                await query.answer(ErrorMessageFormatter.format_invalid("callback data", plain_text=True), show_alert=True)
                return

            search_key = parts[1]
            if len(parts) >= 3:
                original_user_id = int(parts[2])
            else:
                original_user_id = callback_user_id
        except (ValueError, IndexError) as e:
            logger.warning(f"Invalid sendall callback data: {query.data}, error: {e}")
            await query.answer(ErrorMessageFormatter.format_invalid("request format", plain_text=True), show_alert=True)
            return

        # Check ownership
        if original_user_id and callback_user_id != original_user_id:
            await query.answer(ErrorMessageFormatter.format_access_denied("You cannot interact with this message", plain_text=True), show_alert=True)
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
            await telegram_api.call_api(
                client.get_chat,
                user_id,
                chat_id=user_id
            )
        except UserIsBlocked:
            await query.answer(
                ErrorMessageFormatter.format_error(
                    "Please start the bot first!",
                    plain_text=True
                ) + "\n"
                f"Click here: @{self.bot.bot_username}",
                show_alert=True
            )
            return
        except Exception:
            pass

        # Get cached search results with debug logging
        cached_data = await self.bot.cache.get(search_key)
        
        if not cached_data:
            await query.answer(ErrorMessageFormatter.format_error("Search results expired. Please search again.", plain_text=True), show_alert=True)
            return

        files_data = cached_data.get('files', [])
        search_query = cached_data.get('query', '')

        if not files_data:
            await query.answer(ErrorMessageFormatter.format_not_found("Files", plain_text=True), show_alert=True)
            return

        # Check access for bulk send
        owner_id = self.bot.config.ADMINS[0] if self.bot.config.ADMINS else None
        can_access, reason = await self.bot.user_repo.can_retrieve_file(user_id, owner_id)

        if not can_access:
            await query.answer(ErrorMessageFormatter.format_access_denied(reason, plain_text=True), show_alert=True)
            return

        # Check if user is admin or owner (they bypass quota) using validators
        user_is_admin = is_admin(user_id, self.bot.config.ADMINS)
        user_is_owner = user_id == owner_id

        # Get user for premium check
        user = await self.bot.user_repo.get_user(user_id)
        needs_quota = (
            user and
            not user.is_premium and
            not self.bot.config.DISABLE_PREMIUM and
            not user_is_admin and
            not user_is_owner
        )

        # Reserve quota atomically BEFORE sending files (prevents race conditions)
        reserved_count = 0
        if needs_quota:
            success, reserved_count, message = await self.bot.user_repo.reserve_quota_atomic(
                user_id,
                len(files_data),
                self.bot.config.NON_PREMIUM_DAILY_LIMIT
            )
            if not success:
                await query.answer(
                    ErrorMessageFormatter.format_error(
                        f"{message}. Upgrade to premium for unlimited access!",
                        plain_text=True
                    ),
                    show_alert=True
                )
                return

        # Start sending files to PM. If setup fails, no file was delivered and
        # the entire reservation must be returned.
        try:
            await query.answer(f"📤 Sending {len(files_data)} files...", show_alert=False)
        except BaseException:
            if needs_quota and reserved_count:
                await asyncio.shield(self.bot.user_repo.release_quota(user_id, reserved_count))
            raise

        # Send status message to PM
        try:
            status_msg = await telegram_api.call_api(
                client.send_message,
                user_id,  # positional arg for send_message
                f"📤 <b>Sending Files</b>\n"
                f"Query: {search_query}\n"
                f"Total Files: {len(files_data)}\n"
                f"Progress: 0/{len(files_data)}",
                chat_id=user_id  # for call_api rate limiting
            )
        except UserIsBlocked:
            if needs_quota and reserved_count:
                await asyncio.shield(self.bot.user_repo.release_quota(user_id, reserved_count))
            await query.answer(
                ErrorMessageFormatter.format_error(
                    "Please start the bot first!",
                    plain_text=True
                ) + "\n"
                f"Click here: @{self.bot.bot_username}",
                show_alert=True
            )
            return
        except BaseException:
            if needs_quota and reserved_count:
                await asyncio.shield(self.bot.user_repo.release_quota(user_id, reserved_count))
            raise

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

                # telegram_api.call_api already uses semaphore_manager internally
                sent_msg = await telegram_api.call_api(
                    client.send_cached_media,
                    user_id,  # positional arg for send_cached_media
                    file.file_id,
                    caption=caption,
                    parse_mode=CaptionFormatter.get_parse_mode(),
                    reply_markup=self._feature_file_markup(file),
                    chat_id=user_id  # for call_api rate limiting
                )

                sent_messages.append(sent_msg)
                success_count += 1

                feature_service = getattr(self.bot, 'feature_service', None)
                if feature_service:
                    await feature_service.record_recent_file(
                        user_id, file.file_unique_id
                    )

                # Note: We'll increment all at once after the loop to avoid race conditions

                # Update progress every 5 files
                if (idx + 1) % 5 == 0 or (idx + 1) == len(files_data):
                    try:
                        await status_msg.edit_text(
                            f"📤 <b>Sending Files</b>\n"
                            f"Query: {search_query}\n"
                            f"Total Files: {len(files_data)}\n"
                            f"Progress: {idx + 1}/{len(files_data)}\n"
                            f"{ErrorMessageFormatter.format_success('Success', include_prefix=False)}: {success_count}\n"
                            f"{ErrorMessageFormatter.format_error('Failed', include_prefix=False)}: {failed_count}"
                        )
                    except Exception:
                        pass  # Status message update is non-critical

                # Small delay to avoid flooding
                await asyncio.sleep(1)

            except asyncio.CancelledError:
                if needs_quota and reserved_count > success_count:
                    await asyncio.shield(
                        self.bot.user_repo.release_quota(
                            user_id,
                            reserved_count - success_count
                        )
                    )
                raise
            except Exception as e:
                logger.error(f"Error sending file: {e}")
                failed_count += 1

        # Release unused quota if some files failed (quota was reserved upfront)
        # The quota was already reserved at the start, so we only need to release
        # the difference between reserved and actually sent files
        if needs_quota and reserved_count > 0:
            unused_quota = reserved_count - success_count
            if unused_quota > 0:
                await asyncio.shield(
                    self.bot.user_repo.release_quota(user_id, unused_quota)
                )

        # Final status
        final_text = (
            ErrorMessageFormatter.format_success("Transfer Complete!", title="Transfer Complete") + "\n"
            f"Query: {search_query}\n"
            f"Total Files: {len(files_data)}\n"
            f"✅ Sent: {success_count}\n"
        )

        if failed_count > 0:
            final_text += ErrorMessageFormatter.format_error(f"Failed: {failed_count}", include_prefix=False) + "\n"

        # Add auto-delete notice if enabled
        if self.bot.config.MESSAGE_DELETE_SECONDS > 0:
            delete_minutes = self.bot.config.MESSAGE_DELETE_SECONDS // 60
            final_text += f"\n⏱ Files will be auto-deleted after {delete_minutes} minutes"

        await status_msg.edit_text(final_text)

        # Schedule auto-deletion for all sent messages and status message with task tracking
        if self.bot.config.MESSAGE_DELETE_SECONDS > 0:
            # Auto-delete status message (Transfer Complete)
            self._track_task(
                self._auto_delete_message(status_msg, self.bot.config.MESSAGE_DELETE_SECONDS)
            )
            # Auto-delete all sent file messages
            for sent_msg in sent_messages:
                self._track_task(
                    self._auto_delete_message(sent_msg, self.bot.config.MESSAGE_DELETE_SECONDS)
                )

    async def _send_subscription_message(self, client: Client, query: CallbackQuery, file_identifier: str):
        """Send subscription required message for file callback"""
        from pyrogram.types import InlineKeyboardMarkup

        user_id = query.from_user.id

        # Use centralized button builder from SubscriptionManager
        buttons = await self.bot.subscription_manager.build_subscription_buttons(
            client=client,
            user_id=user_id,
            callback_type="file",
            extra_data=file_identifier
        )

        # Get subscription message from bot config or default
        message_text = MessageHelper.get_force_sub_message(self.bot.config)

        await query.answer("🔒 Join our channel(s) first!", show_alert=True)

        try:
            await query.message.reply_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(buttons),
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.debug(f"Failed to send subscription message: {e}")

    async def _send_subscription_message_for_sendall(self, client: Client, query: CallbackQuery, search_key: str):
        """Send subscription required message for sendall callback"""
        from pyrogram.types import InlineKeyboardMarkup

        user_id = query.from_user.id

        # Use centralized button builder from SubscriptionManager
        buttons = await self.bot.subscription_manager.build_subscription_buttons(
            client=client,
            user_id=user_id,
            callback_type="sendall",
            extra_data=search_key
        )

        # Get subscription message from bot config or default
        message_text = MessageHelper.get_force_sub_message(self.bot.config)

        await query.answer("🔒 Join our channel(s) first!", show_alert=True)

        try:
            await query.message.reply_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(buttons),
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.debug(f"Failed to send subscription message for sendall: {e}")
