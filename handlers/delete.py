import asyncio
import hashlib
import html
import secrets
from typing import List, Dict, Any, Optional

from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from core.cache.config import CacheKeyGenerator
from core.services.bulk_delete_policy import (
    MAX_BULK_DELETE_FILES, BulkDeleteInterrupted, BulkDeleteRejected,
)
from core.concurrency.semaphore_manager import semaphore_manager
from core.constants import ProcessingConstants
from core.utils.button_builder import ButtonBuilder
from core.utils.error_formatter import ErrorMessageFormatter
from core.utils.helpers import extract_file_info
from core.utils.logger import get_logger
from core.utils.telegram_api import telegram_api
from core.utils.validators import is_original_requester, validate_callback_data
from handlers.base import BaseHandler

logger = get_logger(__name__)


class DeleteHandler(BaseHandler):
    """Handler for file deletion from database"""

    def __init__(self, bot):
        super().__init__(bot)
        self.delete_queue = asyncio.Queue(maxsize=1000)
        self._register_queue(self.delete_queue)

        # Register handlers
        self.register_handlers()

        # Create background task for queue processing
        task = self._track_task(self._process_delete_queue())
        if task:
            logger.info("Delete queue processor task created")

    def register_handlers(self) -> None:
        """Register delete handlers"""
        handlers_registered = 0

        # Register DELETE_CHANNEL handler if configured
        if self.bot.config.DELETE_CHANNEL:
            handler = MessageHandler(
                self.handle_delete_channel_message,
                filters.chat(self.bot.config.DELETE_CHANNEL)
            )
            self._register_handler(handler)
            handlers_registered += 1
            logger.info(f"Registered DELETE_CHANNEL handler for channel {self.bot.config.DELETE_CHANNEL}")

        # Register admin commands if ADMINS configured
        if self.bot.config.ADMINS:
            self._register_message_handlers([
                (self.handle_delete_command, filters.command("delete") & filters.user(self.bot.config.ADMINS)),
                (self.handle_deleteall_command, filters.command("deleteall") & filters.user(self.bot.config.ADMINS))
            ])
            handlers_registered += 2

            # Callback handler for deleteall confirmation
            self._register_callback_handlers([
                (self.handle_deleteall_callback, filters.regex(r"^deleteall_(confirm|cancel)#"))
            ])
            handlers_registered += 1
            logger.info(f"Registered delete commands for {len(self.bot.config.ADMINS)} admins")

        logger.info(f"DeleteHandler registered {handlers_registered} handlers")

    async def _process_delete_queue(self):
        """Process delete queue in background"""
        logger.info("Delete queue processor started")

        while not self._shutdown.is_set():
            try:
                batch = []
                deadline = asyncio.get_event_loop().time() + ProcessingConstants.DELETE_BATCH_TIMEOUT

                while len(batch) < ProcessingConstants.DELETE_BATCH_SIZE and not self._shutdown.is_set():
                    try:
                        remaining = deadline - asyncio.get_event_loop().time()
                        if remaining <= 0:
                            break  # Deadline passed, process what we have

                        timeout = min(remaining, 5.0)  # Cap at 5 seconds

                        item = await asyncio.wait_for(
                            self.delete_queue.get(),
                            timeout=timeout
                        )
                        batch.append(item)

                    except asyncio.TimeoutError:
                        break  # Timeout reached, process batch

                if batch and not self._shutdown.is_set():
                    await self._process_delete_batch(batch)
                elif not batch:
                    # No items to process, wait a bit before checking again
                    try:
                        await asyncio.wait_for(self._shutdown.wait(), timeout=1.0)
                        break  # Shutdown requested
                    except asyncio.TimeoutError:
                        pass  # Continue checking for items

            except asyncio.CancelledError:
                logger.info("Delete queue processor cancelled")
                break
            except Exception as e:
                logger.error(f"Error processing delete queue: {e}", exc_info=True)
                # Wait before retrying to avoid tight error loop
                try:
                    await asyncio.wait_for(self._shutdown.wait(), timeout=5.0)
                    break  # Shutdown requested
                except asyncio.TimeoutError:
                    pass  # Continue after wait

        logger.info("Delete queue processor exited")

    async def handle_delete_channel_message(self, client: Client, message: Message):
        """Handle messages forwarded to delete channel"""
        logger.debug(f"Delete channel message received: {message.id}")

        if not message.media:
            logger.debug("No media found in message")
            return

        # Extract file information
        file_info = extract_file_info(message)

        if not file_info:
            logger.warning("No supported media type found in message")
            return

        logger.info(f"Adding file to delete queue: {file_info['file_name']} ({file_info['file_unique_id']})")

        # Add to delete queue
        try:
            # Try to add without blocking
            self.delete_queue.put_nowait(file_info)
            logger.info(f"File added to delete queue successfully: {file_info['file_name']}")
        except asyncio.QueueFull:
            # PH-007: never silently discard accepted delete-channel messages.
            # Apply backpressure until the worker has capacity. This remains
            # in-memory and cannot guarantee crash recovery.
            logger.warning("Delete queue at capacity; applying backpressure")
            await self.delete_queue.put(file_info)

    async def handle_delete_command(self, client: Client, message: Message):
        """Handle manual delete command"""
        if len(message.command) > 1:
            # Delete by file_unique_id
            file_unique_id = message.command[1]
            deleted = await self._delete_file(file_unique_id)

            if deleted:
                await message.reply_text(ErrorMessageFormatter.format_success("File deleted from database!"))
            else:
                await message.reply_text(ErrorMessageFormatter.format_not_found("File") + " in database")
            return

        if not message.reply_to_message:
            await message.reply_text(
                "Reply to a media message to delete it from database.\n"
                "Or use: <code>/delete &lt;file_unique_id&gt;</code>"
            )
            return

        # Extract file info from replied message
        file_info = extract_file_info(message.reply_to_message)

        if not file_info:
            await message.reply_text(ErrorMessageFormatter.format_error("No supported media found in the message"))
            return

        # Delete from database
        deleted = await self._delete_file(file_info['file_unique_id'])

        if deleted:
            await message.reply_text(
                ErrorMessageFormatter.format_success("File deleted from database!") + "\n"
                f"📁 Name: {file_info['file_name']}"
            )
        else:
            await message.reply_text(ErrorMessageFormatter.format_not_found("File") + " in database")

    async def handle_deleteall_command(self, client: Client, message: Message):
        """Create a safe, short-lived preview before deleting any media."""
        if not message.from_user or message.from_user.id not in self.bot.config.ADMINS:
            await message.reply_text("Only bot administrators can delete indexed files.")
            return
        if len(message.command) < 2:
            await message.reply_text(
                "<b>Usage:</b> <code>/deleteall &lt;keyword&gt;</code>\n"
                f"Preview and confirm at most {MAX_BULK_DELETE_FILES} matches."
            )
            return

        keyword = " ".join(message.command[1:]).strip()
        try:
            preview = await self.bot.media_repo.preview_delete_files_by_keyword(keyword)
        except BulkDeleteRejected as error:
            await message.reply_text(
                ErrorMessageFormatter.format_warning(html.escape(str(error)))
            )
            return
        except Exception as error:
            logger.exception("PH-007 deletion preview failed")
            await message.reply_text("Deletion preview temporarily unavailable. Try again.")
            return

        if preview.count == 0:
            await message.reply_text("No indexed files match that keyword.")
            return
        if preview.count > MAX_BULK_DELETE_FILES:
            await message.reply_text(
                f"Deletion refused: {preview.count} matches exceeds the "
                f"{MAX_BULK_DELETE_FILES}-file per-request safety limit. "
                "Use a narrower keyword."
            )
            return

        user_id = message.from_user.id
        token = secrets.token_hex(6)
        pending = {"keyword": preview.keyword, "count": preview.count, "token": token}
        stored = await self.bot.cache.set(
            CacheKeyGenerator.deleteall_pending(user_id), pending, expire=90
        )
        if not stored:
            await message.reply_text(
                "Could not save confirmation securely. Nothing was deleted."
            )
            return

        sample = "\n".join(
            f"• {html.escape(name[:100])}" for name in preview.sample
        )
        await message.reply_text(
            "⚠️ <b>Bulk deletion preview</b>\n\n"
            f"Keyword: <code>{html.escape(preview.keyword)}</code>\n"
            f"Matching files: <b>{preview.count}</b>\n"
            f"Maximum allowed: {MAX_BULK_DELETE_FILES}\n\n"
            f"Sample:\n{sample}\n\n"
            "This removes matching records from the bot index, not Telegram. "
            "Confirm within 90 seconds.",
            reply_markup=InlineKeyboardMarkup([[
                ButtonBuilder.action_button(
                    "✅ Confirm", callback_data=f"deleteall_confirm#{user_id}#{token}"
                ),
                ButtonBuilder.action_button(
                    "❌ Cancel", callback_data=f"deleteall_cancel#{user_id}#{token}"
                ),
            ]]),
        )

    async def handle_deleteall_callback(self, client: Client, callback_query):
        """Consume one exact confirmation; report real partial results."""
        valid, parts = validate_callback_data(callback_query, expected_parts=3)
        if not valid or len(parts) != 3 or parts[0] not in (
            "deleteall_confirm", "deleteall_cancel"
        ):
            await callback_query.answer("Invalid deletion request", show_alert=True)
            return
        action, original, token = parts
        try:
            owner_id = int(original)
        except (TypeError, ValueError):
            await callback_query.answer("Invalid requester", show_alert=True)
            return
        requester = getattr(callback_query.from_user, "id", None)
        if (not is_original_requester(requester, owner_id)
                or requester not in self.bot.config.ADMINS):
            await callback_query.answer(
                "Only the original bot administrator can confirm.",
                show_alert=True,
            )
            return

        cache_key = CacheKeyGenerator.deleteall_pending(owner_id)
        pending = await self.bot.cache.get(cache_key)
        if (not isinstance(pending, dict)
                or pending.get("token") != token
                or not isinstance(pending.get("keyword"), str)
                or not isinstance(pending.get("count"), int)):
            await callback_query.answer(
                "Confirmation expired or replaced. Preview again.", show_alert=True
            )
            return

        # Atomic compare-and-delete makes concurrent/replayed callbacks harmless.
        consumed = await self.bot.cache.delete_if_value(cache_key, pending)
        if not consumed:
            await callback_query.answer(
                "Confirmation already used or unavailable.", show_alert=True
            )
            return
        if action == "deleteall_cancel":
            await callback_query.message.edit_text("Deletion cancelled. No files deleted.")
            await callback_query.answer()
            return

        fingerprint = hashlib.sha256(
            pending["keyword"].encode("utf-8")
        ).hexdigest()[:12]
        logger.warning(
            "PH-007 admin=%s began confirmed deletion keyword_hash=%s count=%d",
            owner_id, fingerprint, pending["count"],
        )
        await callback_query.message.edit_text("🗑 Deleting in bounded batches...")
        deleted = 0
        completed = False
        try:
            deleted = await self.bot.media_repo.delete_files_by_keyword(
                pending["keyword"],
                expected_count=pending["count"],
                stop_requested=self._shutdown.is_set,
            )
            completed = True
            response = (
                f"✅ Deleted <b>{deleted}</b> indexed files. "
                "No Telegram source files were removed."
            )
        except BulkDeleteRejected as error:
            response = (
                "⚠️ Nothing deleted. "
                f"{html.escape(str(error))} Run /deleteall again to preview."
            )
        except BulkDeleteInterrupted as error:
            deleted = error.deleted_count
            response = (
                f"⚠️ Deletion stopped after <b>{deleted}</b> acknowledged files. "
                "Review logs and preview remaining matches before retrying."
            )
            logger.error(
                "PH-007 admin=%s interrupted keyword_hash=%s acknowledged=%d: %s",
                owner_id, fingerprint, deleted, error,
            )
        except Exception as error:
            logger.exception(
                "PH-007 admin=%s failed keyword_hash=%s acknowledged=%d error=%s",
                owner_id, fingerprint, deleted, error
            )
            response = "⚠️ Deletion failed. Review logs before retrying."
        logger.warning(
            "PH-007 audit admin=%s keyword_hash=%s completed=%s deleted=%d expected=%d",
            owner_id, fingerprint, completed, deleted, pending["count"],
        )
        await callback_query.message.edit_text(response)
        if self.bot.config.LOG_CHANNEL:
            try:
                await telegram_api.call_api(
                    self.bot.send_message, self.bot.config.LOG_CHANNEL,
                    "#BulkDelete\n"
                    f"Admin ID: {owner_id}\n"
                    f"Keyword hash: {fingerprint}\n"
                    f"Expected: {pending['count']}\n"
                    f"Acknowledged deleted: {deleted}\n"
                    f"Completed: {completed}",
                    chat_id=self.bot.config.LOG_CHANNEL,
                )
            except Exception as e:
                logger.exception(f"PH-007 deletion audit Telegram delivery failed: {e}")
        await callback_query.answer(
            "Deletion completed" if completed else "Deletion stopped; review details"
        )

    async def _process_delete_batch(self, batch: List[Dict[str, Any]]):
        """Process a batch of delete requests"""
        results = {
            'deleted': 0,
            'not_found': 0,
            'errors': 0
        }

        for item in batch:
            if self._shutdown.is_set():
                logger.info("Shutdown requested, stopping batch processing")
                break

            try:
                file_unique_id = item['file_unique_id']
                file_name = item.get('file_name', 'Unknown')

                logger.debug(f"Processing deletion for: {file_name} ({file_unique_id})")

                deleted = await self._delete_file(file_unique_id)

                if deleted:
                    results['deleted'] += 1
                    logger.info(f"Deleted file: {file_name}")
                else:
                    results['not_found'] += 1
                    logger.debug(f"File not found: {file_name} ({file_unique_id})")

                # Small delay to avoid overwhelming the database
                await asyncio.sleep(0.1)

            except Exception as e:
                logger.error(f"Error deleting file {item.get('file_name', 'Unknown')}: {e}")
                results['errors'] += 1

        logger.info(f"Batch processing complete: {results}")

        # Send summary to log channel if significant deletions
        if results['deleted'] > 0 and self.bot.config.LOG_CHANNEL:
            try:
                summary = (
                    f"🗑 <b>Deletion Summary</b>\n\n"
                    f"✅ Deleted: {results['deleted']}\n"
                    f"❌ Not Found: {results['not_found']}\n"
                    f"⚠️ Errors: {results['errors']}\n"
                    f"📊 Total Processed: {len(batch)}"
                )

                await telegram_api.call_api(
                    self.bot.send_message,
                    self.bot.config.LOG_CHANNEL,
                    summary,
                    chat_id=self.bot.config.LOG_CHANNEL
                )
            except Exception as e:
                logger.error(f"Failed to send deletion summary: {e}")

    async def _delete_file(self, file_unique_id: str) -> bool:
        """Delete a single file from database"""
        try:
            # Use semaphore to control concurrent database write operations
            async with semaphore_manager.acquire('database_write'):
                # Repository handles finding, deleting, and cache invalidation
                deleted = await self.bot.media_repo.delete(file_unique_id)
                if deleted:
                    logger.info(f"Deleted file: {file_unique_id}")
                else:
                    logger.debug(f"File not found: {file_unique_id}")
                return deleted
        except Exception as e:
            logger.error(f"Error deleting file {file_unique_id}: {e}", exc_info=True)
            return False
