import asyncio
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.enums import ParseMode

from core.cache.monitor import CacheMonitor
from core.utils.helpers import format_file_size
from core.utils.logger import get_logger
from core.utils.performance import performance_monitor
from core.utils.validators import admin_only, owner_only
from handlers.commands_handlers.base import BaseCommandHandler

logger = get_logger(__name__)


class AdminCommandHandler(BaseCommandHandler):
    """Handler for admin-only commands"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.broadcasting_in_progress = False
        self.broadcast_task = None
        self.broadcast_state_key = "broadcast:state"
        
    async def _get_broadcast_state(self):
        """Get broadcast state from Redis"""
        try:
            state = await self.bot.cache.get(self.broadcast_state_key)
            is_active = state == "active" if state else False
            logger.debug(f"Broadcast state check: {state} -> {is_active}")
            # Sync memory state with Redis state
            self.broadcasting_in_progress = is_active
            return is_active
        except Exception as e:
            logger.error(f"Error getting broadcast state: {e}")
            return self.broadcasting_in_progress  # Fallback to memory state
    
    async def _set_broadcast_state(self, active: bool):
        """Set broadcast state in Redis"""
        try:
            if active:
                await self.bot.cache.set(self.broadcast_state_key, "active", expire=3600)  # 1 hour TTL
                logger.info("Broadcast state set to ACTIVE")
            else:
                await self.bot.cache.delete(self.broadcast_state_key)
                logger.info("Broadcast state cleared")
            self.broadcasting_in_progress = active
        except Exception as e:
            logger.error(f"Error setting broadcast state: {e}")
            self.broadcasting_in_progress = active  # Always update memory state

    def _parse_quoted_command(self, text: str) -> List[str]:
        """Parse command with quoted arguments"""
        import shlex
        try:
            return shlex.split(text)
        except ValueError:
            # Fallback to simple split if shlex fails
            return text.split()

    async def _notify_user(self, client: Client, user_id: int, message: str) -> bool:
        """Send notification to user, return True if successful"""
        try:
            await client.send_message(user_id, message)
            return True
        except Exception as e:
            logger.warning(f"Failed to notify user {user_id}: {e}")
            return False
    @admin_only
    async def broadcast_command(self, client: Client, message: Message):
        """Enhanced broadcast command with HTML formatting and preview"""
        if not message.reply_to_message:
            await message.reply_text(
                "⚠️ Reply to a message to broadcast it.\n\n"
                "<b>Features:</b>\n"
                "• HTML formatting support\n"
                "• Preview before sending\n"
                "• Can broadcast text, photos, videos, documents\n"
                "• Use HTML tags: <b>bold</b>, <i>italic</i>, <code>code</code>\n"
                "• Confirmation buttons for safety",
                parse_mode=ParseMode.HTML
            )
            return

        # Check persistent broadcast state
        is_broadcasting = await self._get_broadcast_state()
        if is_broadcasting:
            await message.reply_text("⚠️ A broadcast is already in progress. Use /stop_broadcast to stop it.")
            return

        # Rate limit check
        is_allowed, cooldown = await self.bot.rate_limiter.check_rate_limit(
            message.from_user.id,
            'broadcast'
        )
        if not is_allowed:
            await message.reply_text(
                f"⚠️ Broadcast rate limit. Try again in {cooldown} seconds."
            )
            return

        broadcast_msg = message.reply_to_message
        user_count = await self.bot.user_repo.count({'status': {'$ne': 'banned'}})

        # Create preview message
        preview_text = f"📡 <b>Broadcast Preview</b>\n\n"
        preview_text += f"👥 <b>Total Recipients:</b> {user_count:,} users\n\n"
        preview_text += f"📄 <b>Message Preview:</b>\n"
        
        if broadcast_msg.text:
            # Show text preview (limit to 200 chars)
            text_preview = broadcast_msg.text[:200] + ("..." if len(broadcast_msg.text) > 200 else "")
            preview_text += f"<i>{text_preview}</i>"
        elif broadcast_msg.caption:
            # Show caption preview for media
            caption_preview = broadcast_msg.caption[:200] + ("..." if len(broadcast_msg.caption) > 200 else "")
            preview_text += f"<i>{caption_preview}</i>"
        elif broadcast_msg.document:
            preview_text += f"📄 <i>Document: {broadcast_msg.document.file_name}</i>"
        elif broadcast_msg.photo:
            preview_text += f"🖼 <i>Photo</i>"
        elif broadcast_msg.video:
            preview_text += f"🎥 <i>Video</i>"
        elif broadcast_msg.audio:
            preview_text += f"🎵 <i>Audio</i>"
        else:
            preview_text += f"📱 <i>Media message</i>"

        preview_text += f"\n\n⚠️ <b>Warning:</b> This will send the message with HTML formatting to all users."

        # Confirmation buttons
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Confirm Broadcast", callback_data="confirm_broadcast"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast")
            ]
        ])

        # Store broadcast message for callback
        self.bot._pending_broadcast = {
            'message': broadcast_msg,
            'admin_id': message.from_user.id,
            'admin_message_id': message.id
        }

        await message.reply_text(preview_text, reply_markup=buttons, parse_mode=ParseMode.HTML)

    async def handle_broadcast_confirmation(self, client: Client, callback_query):
        """Handle broadcast confirmation callback"""
        if not hasattr(self.bot, '_pending_broadcast') or not self.bot._pending_broadcast:
            await callback_query.answer("❌ No pending broadcast found.")
            return

        pending = self.bot._pending_broadcast
        if callback_query.from_user.id != pending['admin_id']:
            await callback_query.answer("❌ Only the admin who initiated this broadcast can confirm it.")
            return

        if callback_query.data == "cancel_broadcast":
            await callback_query.message.edit_text("❌ Broadcast cancelled.")
            # Reset rate limit when broadcast is cancelled
            await self.bot.rate_limiter.reset_rate_limit(callback_query.from_user.id, 'broadcast')
            self.bot._pending_broadcast = None
            await callback_query.answer()
            return

        if callback_query.data == "confirm_broadcast":
            # Check persistent broadcast state
            is_broadcasting = await self._get_broadcast_state()
            if is_broadcasting:
                await callback_query.answer("⚠️ A broadcast is already in progress.")
                return

            # Set broadcast state as active
            await self._set_broadcast_state(True)
            broadcast_msg = pending['message']
            
            logger.info(f"Starting broadcast for admin {callback_query.from_user.id}")
            await callback_query.message.edit_text("📡 Starting broadcast...")

            # Progress callback
            async def update_progress(stats: Dict[str, int]):
                try:
                    if stats['total'] > 0:
                        processed = stats['success'] + stats['blocked'] + stats['deleted'] + stats['failed']
                        progress_percent = (processed / stats['total']) * 100
                        
                        text = (
                            f"📡 <b>Broadcast Progress</b>\n\n"
                            f"👥 Total Users: {stats['total']:,}\n"
                            f"✅ Success: {stats['success']:,}\n"
                            f"🚫 Blocked: {stats['blocked']:,}\n"
                            f"❌ Deleted: {stats['deleted']:,}\n"
                            f"⚠️ Failed: {stats['failed']:,}\n\n"
                            f"📊 Processed: {processed:,}/{stats['total']:,}\n"
                            f"⏳ Progress: {progress_percent:.1f}%"
                        )

                        try:
                            await callback_query.message.edit_text(text, parse_mode=ParseMode.HTML)
                        except FloodWait as e:
                            await asyncio.sleep(e.value)
                except Exception as e:
                    logger.error(f"Progress update error: {e}")

            # Start broadcast task
            start_time = datetime.now()
            
            try:
                self.broadcast_task = asyncio.create_task(
                    self.bot.broadcast_service.broadcast_to_users(
                        client,
                        broadcast_msg,
                        progress_callback=update_progress
                    )
                )
                
                # Store global reference for cross-handler access
                self.bot._active_broadcast_task = self.broadcast_task
                
                final_stats = await self.broadcast_task

                # Final message
                duration = datetime.now() - start_time
                final_text = (
                    f"✅ <b>Broadcast Completed!</b>\n\n"
                    f"⏱ Duration: {duration}\n"
                    f"📊 Total Users: {final_stats['total']:,}\n"
                    f"✅ Success: {final_stats['success']:,} ({final_stats['success'] / final_stats['total'] * 100:.1f}%)\n"
                    f"🚫 Blocked: {final_stats['blocked']:,}\n"
                    f"❌ Deleted: {final_stats['deleted']:,}\n"
                    f"⚠️ Failed: {final_stats['failed']:,}"
                )

                await callback_query.message.edit_text(final_text, parse_mode=ParseMode.HTML)

                # Log broadcast
                if self.bot.config.LOG_CHANNEL:
                    await client.send_message(
                        self.bot.config.LOG_CHANNEL,
                        f"#Broadcast\n"
                        f"Admin: {callback_query.from_user.mention}\n"
                        f"Total: {final_stats['total']:,}\n"
                        f"Success: {final_stats['success']:,}",
                        parse_mode=ParseMode.HTML
                    )

            except asyncio.CancelledError:
                await callback_query.message.edit_text(
                    "🛑 <b>Broadcast Stopped</b>\n\n"
                    "The broadcast was manually stopped by an admin.",
                    parse_mode=ParseMode.HTML
                )
                # Reset rate limit when broadcast is cancelled
                await self.bot.rate_limiter.reset_rate_limit(callback_query.from_user.id, 'broadcast')
            except Exception as e:
                logger.error(f"Broadcast error: {e}")
                await callback_query.message.edit_text(
                    f"❌ <b>Broadcast Failed</b>\n\n"
                    f"Error: {str(e)}",
                    parse_mode=ParseMode.HTML
                )
                # Reset rate limit when broadcast fails
                await self.bot.rate_limiter.reset_rate_limit(callback_query.from_user.id, 'broadcast')
            finally:
                await self._set_broadcast_state(False)
                self.broadcast_task = None
                self.bot._pending_broadcast = None
                # Clear global reference
                if hasattr(self.bot, '_active_broadcast_task'):
                    self.bot._active_broadcast_task = None

            await callback_query.answer()

    @admin_only
    async def stop_broadcast_command(self, client: Client, message: Message):
        """Stop ongoing broadcast"""
        # Check persistent broadcast state
        is_broadcasting = await self._get_broadcast_state()
        memory_state = self.broadcasting_in_progress
        task_exists = self.broadcast_task is not None
        
        # Also check global task reference
        global_task_exists = hasattr(self.bot, '_active_broadcast_task') and self.bot._active_broadcast_task is not None
        
        logger.info(f"Stop broadcast check - Redis: {is_broadcasting}, Memory: {memory_state}, Task: {task_exists}, Global: {global_task_exists}")
        
        if not is_broadcasting and not memory_state and not task_exists and not global_task_exists:
            await message.reply_text("❌ No broadcast is currently in progress.")
            return

        # Clear persistent state regardless of task status
        await self._set_broadcast_state(False)
        
        # Try to find and cancel the broadcast task across all handlers
        task_cancelled = False
        if self.broadcast_task:
            self.broadcast_task.cancel()
            task_cancelled = True
            logger.info("Cancelled broadcast task from current handler instance")
        
        # Also check if there's a global broadcast task reference we can cancel
        if hasattr(self.bot, '_active_broadcast_task') and self.bot._active_broadcast_task:
            try:
                self.bot._active_broadcast_task.cancel()
                self.bot._active_broadcast_task = None  # Clear immediately after cancelling
                task_cancelled = True
                logger.info("Cancelled broadcast task from global reference")
            except Exception as e:
                logger.error(f"Error cancelling global broadcast task: {e}")
                # Clear reference even if cancellation failed
                self.bot._active_broadcast_task = None
        
        if task_cancelled:
            await message.reply_text("🛑 <b>Broadcast stopped!</b>\n\nThe ongoing broadcast has been cancelled.", parse_mode=ParseMode.HTML)
        else:
            # Handle case where bot was restarted but broadcast state persisted
            await message.reply_text(
                "🛑 <b>Broadcast state cleared!</b>\n\n"
                "The broadcast was likely interrupted by a restart. State has been reset.",
                parse_mode=ParseMode.HTML
            )

    @admin_only
    async def reset_broadcast_limit_command(self, client: Client, message: Message):
        """Reset broadcast rate limit for admin (for testing/debugging)"""
        try:
            user_id = message.from_user.id
            await self.bot.rate_limiter.reset_rate_limit(user_id, 'broadcast')
            await message.reply_text(
                "✅ <b>Broadcast Rate Limit Reset</b>\n\n"
                "You can now use the broadcast command again.",
                parse_mode=ParseMode.HTML
            )
            logger.info(f"Admin {user_id} reset their broadcast rate limit")
        except Exception as e:
            await message.reply_text(f"❌ Error resetting rate limit: {str(e)}")
            logger.error(f"Error resetting broadcast rate limit: {e}")

    @admin_only
    async def users_command(self, client: Client, message: Message):
        """Get total users count"""
        stats = await self.bot.user_repo.get_user_stats()

        text = (
            f"👥 <b>User Statistics</b>\n\n"
            f"Total Users: {stats['total']:,}\n"
            f"Premium Users: {stats['premium']:,}\n"
            f"Banned Users: {stats['banned']:,}\n"
            f"Active Today: {stats['active_today']:,}"
        )

        await message.reply_text(text)

    @admin_only
    async def ban_command(self, client: Client, message: Message):
        """Ban a user"""
        # Parse command with quoted arguments
        try:
            parts = self._parse_quoted_command(message.text)
            if len(parts) < 2:
                await message.reply_text(
                    "<b>Usage:</b> <code>/ban &lt;user_id&gt; [reason]</code>\n"
                    "<b>Examples:</b>\n"
                    "• <code>/ban 123456789</code>\n"
                    "• <code>/ban 123456789 Spamming</code>\n"
                    "• <code>/ban 123456789 \"Spamming and hate speech\"</code>"
                )
                return

            target_user_id = int(parts[1])
            reason = " ".join(parts[2:]) if len(parts) > 2 else "No reason provided"

        except ValueError:
            await message.reply_text("❌ Invalid user ID format.")
            return
        except Exception as e:
            await message.reply_text(f"❌ Error parsing command: {str(e)}")
            return

        # Ban the user
        success, msg, user_data = await self.bot.user_repo.ban_user(target_user_id, reason)

        await message.reply_text(msg)

        if success and user_data:
            await self.bot.cache_invalidator.invalidate_user_cache(target_user_id)
            # Notify the banned user
            ban_notification = (
                "🚫 <b>You have been banned from using this bot</b>\n"
                f"<b>Reason:</b> {reason}\n"
                f"<b>Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                "If you believe this is a mistake, please contact the bot administrator."
            )

            notification_sent = await self._notify_user(client, target_user_id, ban_notification)

            # Log to admin channel
            if self.bot.config.LOG_CHANNEL:
                try:
                    log_text = (
                        f"#UserBanned\n\n"
                        f"<b>User:</b> <code>{target_user_id}</code> ({user_data.name})\n"
                        f"<b>Reason:</b> {reason}\n"
                        f"<b>Admin:</b> {message.from_user.mention}\n"
                        f"<b>Notification:</b> {'✅ Sent' if notification_sent else '❌ Failed'}\n"
                        f"<b>Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    await client.send_message(self.bot.config.LOG_CHANNEL, log_text)
                except Exception as e:
                    logger.error(f"Failed to log ban action: {e}")

    @admin_only
    async def unban_command(self, client: Client, message: Message):
        """Unban a user"""
        if len(message.command) < 2:
            await message.reply_text("<b>Usage:</b> <code>/unban &lt;user_id&gt;</code>")
            return

        try:
            target_user_id = int(message.command[1])
        except ValueError:
            await message.reply_text("❌ Invalid user ID format.")
            return

        # Unban the user
        success, msg, user_data = await self.bot.user_repo.unban_user(target_user_id)

        await message.reply_text(msg)

        if success and user_data:
            await self.bot.cache_invalidator.invalidate_user_cache(target_user_id)
            # Notify the user
            unban_notification = (
                "✅ <b>You have been unbanned!</b>\n"
                f"You can now use the bot again.\n"
                f"<b>Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                "Welcome back!"
            )

            notification_sent = await self._notify_user(client, target_user_id, unban_notification)

            # Log to admin channel
            if self.bot.config.LOG_CHANNEL:
                try:
                    log_text = (
                        f"#UserUnbanned\n\n"
                        f"<b>User:</b> <code>{target_user_id}</code> ({user_data.name})\n"
                        f"<b>Admin:</b> {message.from_user.mention}\n"
                        f"<b>Notification:</b> {'✅ Sent' if notification_sent else '❌ Failed'}\n"
                        f"<b>Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    await client.send_message(self.bot.config.LOG_CHANNEL, log_text)
                except Exception as e:
                    logger.error(f"Failed to log unban action: {e}")

    @admin_only
    async def add_premium_command(self, client: Client, message: Message):
        """Add premium status to user"""
        if len(message.command) < 2:
            await message.reply_text("<b>Usage:</b> <code>/addpremium &lt;user_id&gt;</code>", parse_mode=ParseMode.HTML)
            return

        try:
            target_user_id = int(message.command[1])
        except ValueError:
            await message.reply_text("❌ Invalid user ID format.")
            return

        # Add premium status
        success, msg, user_data = await self.bot.user_repo.update_premium_status(target_user_id, True)

        await message.reply_text(msg)

        if success and user_data:
            await self.bot.cache_invalidator.invalidate_user_cache(target_user_id)
            # Notify the user
            premium_notification = (
                "🎉 <b>Congratulations! You have been upgraded to Premium!</b>\n\n"
                f"<b>Benefits:</b>\n"
                f"• Unlimited file downloads\n"
                f"• Priority support\n"
                f"• Advanced features\n"
                f"• Valid for {self.bot.config.PREMIUM_DURATION_DAYS} days\n\n"
                f"<b>Activated on:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                "Enjoy your premium access! 🌟"
            )

            notification_sent = await self._notify_user(client, target_user_id, premium_notification)

            # Log to admin channel
            if self.bot.config.LOG_CHANNEL:
                try:
                    log_text = (
                        f"#PremiumAdded\n\n"
                        f"<b>User:</b> <code>{target_user_id}</code> ({user_data.name})\n"
                        f"<b>Duration:</b> {self.bot.config.PREMIUM_DURATION_DAYS} days\n"
                        f"<b>Admin:</b> {message.from_user.mention}\n"
                        f"<b>Notification:</b> {'✅ Sent' if notification_sent else '❌ Failed'}\n"
                        f"<b>Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    await client.send_message(self.bot.config.LOG_CHANNEL, log_text)
                except Exception as e:
                    logger.error(f"Failed to log premium addition: {e}")

    @admin_only
    async def remove_premium_command(self, client: Client, message: Message):
        """Remove premium status from user"""
        if len(message.command) < 2:
            await message.reply_text("<b>Usage:</b> <code>/removepremium &lt;user_id&gt;</code>", parse_mode=ParseMode.HTML)
            return

        try:
            target_user_id = int(message.command[1])
        except ValueError:
            await message.reply_text("❌ Invalid user ID format.")
            return

        # Remove premium status
        success, msg, user_data = await self.bot.user_repo.update_premium_status(target_user_id, False)

        await message.reply_text(msg)

        if success and user_data:
            await self.bot.cache_invalidator.invalidate_user_cache(target_user_id)
            # Notify the user
            premium_removal_notification = (
                "📋 <b>Your premium subscription has been removed</b>\n\n"
                f"<b>New Limits:</b>\n"
                f"• {self.bot.config.NON_PREMIUM_DAILY_LIMIT} files per day\n"
                f"• Standard support\n\n"
                f"<b>Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                "Thank you for using our premium service!"
            )

            notification_sent = await self._notify_user(client, target_user_id, premium_removal_notification)

            # Log to admin channel
            if self.bot.config.LOG_CHANNEL:
                try:
                    log_text = (
                        f"#PremiumRemoved\n\n"
                        f"<b>User:</b> <code>{target_user_id}</code> ({user_data.name})\n"
                        f"<b>Admin:</b> {message.from_user.mention}\n"
                        f"<b>Notification:</b> {'✅ Sent' if notification_sent else '❌ Failed'}\n"
                        f"<b>Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    await client.send_message(self.bot.config.LOG_CHANNEL, log_text)
                except Exception as e:
                    logger.error(f"Failed to log premium removal: {e}")

    @admin_only
    async def log_command(self, client: Client, message: Message):
        """Send log files to admin"""
        try:
            log_path = Path("logs/bot.txt")

            if not log_path.exists():
                await message.reply_text("❌ No log file found.")
                return

            # Check file size
            file_size = log_path.stat().st_size

            if file_size > 50 * 1024 * 1024:  # 50MB limit
                await message.reply_text(
                    f"❌ Log file too large ({format_file_size(file_size)}). "
                    "Please check logs directly on the server."
                )
                return

            # Send log file
            await message.reply_document(
                document=str(log_path),
                caption=f"📄 Bot Log File\n📊 Size: {format_file_size(file_size)}",
                file_name=f"bot_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            )

        except Exception as e:
            logger.error(f"Error sending log file: {e}")
            await message.reply_text(f"❌ Error: {str(e)}")

    @admin_only
    async def performance_command(self, client: Client, message: Message):
        """Get bot performance metrics"""
        try:
            # Get performance metrics
            metrics = await performance_monitor.get_metrics()

            # Format uptime
            uptime_seconds = metrics['uptime_seconds']
            days = int(uptime_seconds // 86400)
            hours = int((uptime_seconds % 86400) // 3600)
            minutes = int((uptime_seconds % 3600) // 60)
            seconds = int(uptime_seconds % 60)

            uptime_str = ""
            if days > 0:
                uptime_str += f"{days}d "
            if hours > 0:
                uptime_str += f"{hours}h "
            if minutes > 0:
                uptime_str += f"{minutes}m "
            uptime_str += f"{seconds}s"

            # Build response text
            text = (
                "🚀 <b>Bot Performance Metrics</b>\n\n"
                f"<b>Event Loop:</b> {metrics['event_loop']}\n"
                f"<b>Mode:</b> {metrics.get('optimization', 'Standard Mode')}\n"
            )

            if metrics['event_loop'] == 'uvloop':
                text += f"<b>Performance:</b> {metrics.get('expected_improvement', 'Optimized')}\n"
            else:
                text += f"<b>Note:</b> {metrics.get('recommendation', '')}\n"

            text += (
                f"\n📊 <b>System Resources:</b>\n"
                f"├ Memory: {metrics['memory_mb']:.2f} MB\n"
                f"├ CPU: {metrics['cpu_percent']:.1f}%\n"
                f"├ Threads: {metrics['num_threads']}\n"
                f"├ File Descriptors: {metrics['num_fds']}\n"
                f"└ Pending Tasks: {metrics['pending_tasks']}\n\n"
                f"⏱ <b>Uptime:</b> {uptime_str}"
            )

            await message.reply_text(text)

        except Exception as e:
            logger.error(f"Error getting performance metrics: {e}")
            await message.reply_text(f"❌ Error getting performance metrics: {str(e)}")

    @admin_only
    async def cache_stats_command(self, client: Client, message: Message):
        """Get cache statistics"""
        monitor = CacheMonitor(self.bot.cache)

        status_msg = await message.reply_text("📊 Analyzing cache...")

        try:
            stats = await monitor.get_cache_stats()

            if "error" in stats:
                await status_msg.edit_text(f"❌ Error: {stats['error']}")
                return

            text = (
                "📊 <b>Cache Statistics</b>\n\n"
                "<b>Memory Usage:</b>\n"
                f"├ Used: {stats['memory']['used_memory_human']}\n"
                f"├ RSS: {stats['memory']['used_memory_rss_human']}\n"
                f"├ Peak: {stats['memory']['used_memory_peak_human']}\n"
                f"└ Fragmentation: {stats['memory']['mem_fragmentation_ratio']}\n\n"

                "<b>Performance:</b>\n"
                f"├ Hit Rate: {stats['performance']['cache_hit_rate']}\n"
                f"├ Hits: {stats['performance']['keyspace_hits']:,}\n"
                f"├ Misses: {stats['performance']['keyspace_misses']:,}\n"
                f"└ Ops/sec: {stats['performance']['instantaneous_ops_per_sec']}\n\n"

                "<b>Keys by Type:</b>\n"
            )

            for pattern, count in stats['keys']['by_pattern'].items():
                text += f"├ {pattern}: {count:,}\n"

            text += f"\n<b>Total Keys:</b> {stats['keys']['total_keys']:,}"
            text += f"\n<b>Keys with TTL:</b> {stats['keys']['expires']:,}"

            await status_msg.edit_text(text)

        except Exception as e:
            await status_msg.edit_text(f"❌ Error: {str(e)}")

    @admin_only
    async def cache_analyze_command(self, client: Client, message: Message):
        """Analyze cache usage patterns"""
        monitor = CacheMonitor(self.bot.cache)

        status_msg = await message.reply_text("🔍 Analyzing cache usage...")

        try:
            # Check for duplicates
            duplicates = await monitor.find_duplicate_data()

            # Analyze usage
            analysis = await monitor.analyze_cache_usage()

            text = "🔍 <b>Cache Analysis</b>\n\n"

            if duplicates:
                text += f"<b>⚠️ Found {len(duplicates)} duplicate entries:</b>\n"
                for dup in duplicates[:5]:  # Show first 5
                    text += f"├ File {dup['file_id'][:10]}... has {dup['count']} cache entries\n"
                if len(duplicates) > 5:
                    text += f"└ ... and {len(duplicates) - 5} more\n"
                text += "\n"

            if analysis['large_values']:
                text += f"<b>📦 Large Cache Values ({len(analysis['large_values'])}):</b>\n"
                for item in analysis['large_values'][:3]:
                    text += f"├ {item['key'][:30]}... - {item['size_human']}\n"
                text += "\n"

            if analysis['no_ttl']:
                text += f"<b>⏰ Keys without TTL: {len(analysis['no_ttl'])}</b>\n\n"

            text += "<b>📊 Key Size Distribution:</b>\n"
            for category, count in sorted(analysis['key_size_distribution'].items()):
                text += f"├ {category}: {count}\n"

            await status_msg.edit_text(text)

        except Exception as e:
            await status_msg.edit_text(f"❌ Error: {str(e)}")

    @admin_only
    async def cache_cleanup_command(self, client: Client, message: Message):
        """Clean up duplicate cache entries"""
        if len(message.command) < 2 or message.command[1] != "confirm":
            await message.reply_text(
                "⚠️ <b>Cache Cleanup</b>\n\n"
                "This will remove duplicate cache entries.\n"
                "Use <code>/cache_cleanup confirm</code> to proceed."
            )
            return

        monitor = CacheMonitor(self.bot.cache)
        status_msg = await message.reply_text("🧹 Cleaning up cache...")

        try:
            # Find duplicates
            duplicates = await monitor.find_duplicate_data()

            if not duplicates:
                await status_msg.edit_text("✅ No duplicate entries found!")
                return

            cleaned = 0
            for dup in duplicates:
                # Keep the first entry, delete others
                for key in dup['cache_keys'][1:]:
                    await self.bot.cache.redis.delete(key)
                    cleaned += 1

            await status_msg.edit_text(
                f"✅ <b>Cache Cleanup Complete</b>\n\n"
                f"Removed {cleaned} duplicate entries\n"
                f"Freed up memory from {len(duplicates)} files"
            )

        except Exception as e:
            await status_msg.edit_text(f"❌ Error: {str(e)}")

    @owner_only
    async def shell_command(self, client: Client, message: Message):
        """Execute shell commands via bot (Owner only)."""
        try:
            # Extract command from message
            command_parts = message.text.split(' ', 1)
            if len(command_parts) < 2:
                await message.reply_text(
                    "🐚 <b>Shell Command Usage:</b>\n\n"
                    "<b>Syntax:</b> <code>/shell &lt;command&gt;</code>\n\n"
                    "<b>Examples:</b>\n"
                    "• <code>/shell pip install requests</code>\n"
                    "• <code>/shell ls -la</code>\n"
                    "• <code>/shell git status</code>\n"
                    "• <code>/shell python --version</code>\n"
                    "• <code>/shell df -h</code>\n\n"
                    "⚠️ <b>Security Warning:</b>\n"
                    "This command has full system access. Use with extreme caution!\n\n"
                    "<b>Safe Commands:</b>\n"
                    "• Package management: <code>pip install/uninstall</code>\n"
                    "• File operations: <code>ls</code>, <code>cat</code>, <code>head</code>, <code>tail</code>\n"
                    "• System info: <code>ps</code>, <code>df</code>, <code>free</code>, <code>uname</code>\n"
                    "• Git operations: <code>git status</code>, <code>git log</code>\n\n"
                    "<b>Dangerous Commands:</b>\n"
                    "❌ Avoid: <code>rm -rf</code>, <code>chmod 777</code>, <code>sudo su</code>, etc.",
                    parse_mode=ParseMode.HTML
                )
                return
            
            command = command_parts[1].strip()
            
            # Security warning for dangerous commands
            dangerous_patterns = [
                r'\brm\s+-rf\b', r'\brm\s+.*\*', r'\bchmod\s+777\b', 
                r'\bsudo\s+su\b', r'\bmkfs\b', r'\bformat\b',
                r'\bdd\s+if=', r'\bfdisk\b', r'\bcrontab\s+-r\b',
                r'>\s*/dev/', r'\bkill\s+-9.*1\b'
            ]
            
            is_dangerous = any(re.search(pattern, command, re.IGNORECASE) for pattern in dangerous_patterns)
            
            if is_dangerous:
                await message.reply_text(
                    f"⚠️ <b>Potentially Dangerous Command Detected</b>\n\n"
                    f"<b>Command:</b> <code>{command}</code>\n\n"
                    f"This command appears to be potentially destructive. "
                    f"Please review carefully before execution.\n\n"
                    f"Reply with <code>EXECUTE ANYWAY</code> to proceed or cancel this operation.",
                    parse_mode=ParseMode.HTML
                )
                return
            
            # Send initial status message
            status_msg = await message.reply_text(
                f"🐚 <b>Executing Shell Command</b>\n\n"
                f"<b>Command:</b> <code>{command}</code>\n"
                f"<b>Status:</b> Running...\n\n"
                f"⏳ Please wait for output...",
                parse_mode=ParseMode.HTML
            )
            
            logger.info(f"Shell command initiated by owner: {command}")
            start_time = datetime.now()
            
            # Execute command with timeout
            try:
                # Use subprocess for better control and security
                process = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=os.getcwd(),
                    env=os.environ.copy()
                )
                
                # Wait for completion with timeout (max 5 minutes)
                try:
                    stdout, stderr = process.communicate(timeout=300)
                    return_code = process.returncode
                    execution_time = (datetime.now() - start_time).total_seconds()
                    
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout, stderr = process.communicate()
                    return_code = -1
                    execution_time = 300
                    stderr += "\n⚠️ Command timed out after 5 minutes"
                
            except Exception as e:
                await status_msg.edit_text(
                    f"🐚 <b>Shell Command Failed</b>\n\n"
                    f"<b>Command:</b> <code>{command}</code>\n"
                    f"<b>Error:</b> {str(e)}\n\n"
                    f"❌ Execution failed before completion",
                    parse_mode=ParseMode.HTML
                )
                logger.error(f"Shell command execution failed: {e}")
                return
            
            # Prepare output message
            execution_status = "✅ Success" if return_code == 0 else f"❌ Failed (Exit Code: {return_code})"
            
            # Combine stdout and stderr
            output_parts = []
            if stdout.strip():
                output_parts.append(f"<b>📤 STDOUT:</b>\n<pre>\n{stdout.strip()}\n</pre>")
            if stderr.strip():
                output_parts.append(f"<b>📥 STDERR:</b>\n<pre>\n{stderr.strip()}\n</pre>")
            
            if not output_parts:
                output_text = "<i>(No output generated)</i>"
            else:
                output_text = "\n\n".join(output_parts)
            
            # Create result message
            result_message = f"""🐚 <b>Shell Command Executed</b>

<b>Command:</b> <code>{command}</code>
<b>Status:</b> {execution_status}
<b>Execution Time:</b> {execution_time:.2f}s
<b>Return Code:</b> {return_code}

{output_text}"""
            
            # Handle long outputs
            if len(result_message) > 4096:  # Telegram message limit
                # Send basic info first
                basic_info = f"""🐚 <b>Shell Command Executed</b>

<b>Command:</b> <code>{command}</code>
<b>Status:</b> {execution_status}
<b>Execution Time:</b> {execution_time:.2f}s
<b>Return Code:</b> {return_code}

⚠️ <b>Output too long - sending as file...</b>"""
                
                await status_msg.edit_text(basic_info, parse_mode=ParseMode.HTML)
                
                # Create output file
                output_filename = f"shell_output_{int(start_time.timestamp())}.txt"
                full_output = f"Shell Command: {command}\n"
                full_output += f"Executed at: {start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                full_output += f"Return Code: {return_code}\n"
                full_output += f"Execution Time: {execution_time:.2f}s\n"
                full_output += "=" * 50 + "\n\n"
                
                if stdout.strip():
                    full_output += "STDOUT:\n" + stdout + "\n\n"
                if stderr.strip():
                    full_output += "STDERR:\n" + stderr + "\n"
                
                # Write to temp file and send
                with open(output_filename, 'w', encoding='utf-8') as f:
                    f.write(full_output)
                
                await message.reply_document(
                    output_filename,
                    caption=f"📄 Shell command output\n<b>Command:</b> <code>{command}</code>",
                    parse_mode=ParseMode.HTML
                )
                
                # Clean up temp file
                os.remove(output_filename)
            else:
                # Send normal message
                await status_msg.edit_text(result_message, parse_mode=ParseMode.HTML)
            
            logger.info(f"Shell command completed: {command} (exit code: {return_code}, time: {execution_time:.2f}s)")
            
        except Exception as e:
            logger.error(f"Error in shell command: {e}")
            try:
                await status_msg.edit_text(
                    f"🐚 <b>Shell Command Error</b>\n\n"
                    f"<b>Command:</b> <code>{command if 'command' in locals() else 'Unknown'}</code>\n"
                    f"<b>Error:</b> {str(e)}\n\n"
                    f"❌ Unexpected error occurred",
                    parse_mode=ParseMode.HTML
                )
            except:
                await message.reply_text(
                    f"🐚 <b>Shell Command Error</b>\n\n"
                    f"<b>Error:</b> {str(e)}\n\n"
                    f"❌ Failed to execute shell command",
                    parse_mode=ParseMode.HTML
                )