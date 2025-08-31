import asyncio
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import Message

from core.cache.monitor import CacheMonitor
from core.utils.helpers import format_file_size
from core.utils.logger import get_logger
from core.utils.performance import performance_monitor
from handlers.commands_handlers.base import BaseCommandHandler, admin_only

logger = get_logger(__name__)


class AdminCommandHandler(BaseCommandHandler):
    """Handler for admin-only commands"""

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
    # The broadcast command is already well-implemented, but let's add some improvements:

    @admin_only
    async def broadcast_command(self, client: Client, message: Message):
        """Handle broadcast command with improvements"""
        if not message.reply_to_message:
            await message.reply_text(
                "⚠️ Reply to a message to broadcast it.\n\n"
                "**Tips:**\n"
                "• You can broadcast text, photos, videos, documents\n"
                "• Use formatting: **bold**, __italic__, `code`\n"
                "• Add buttons using @BotFather's inline keyboard"
            )
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

        # Confirmation for large broadcasts
        user_count = await self.bot.user_repo.count({'status': {'$ne': 'banned'}})

        if user_count > 100:
            confirm_msg = await message.reply_text(
                f"⚠️ **Broadcast Confirmation**\n\n"
                f"This will send the message to **{user_count:,}** users.\n\n"
                f"Reply with 'YES' within 30 seconds to confirm."
            )

            try:
                response = await client.wait_for_message(
                    chat_id=message.chat.id,
                    filters=filters.user(message.from_user.id) & filters.text,  # Fixed parameters
                    timeout=30
                )

                if not response or not response.text or response.text.upper() != "YES":
                    await confirm_msg.edit_text("❌ Broadcast cancelled.")
                    return

            except asyncio.TimeoutError:
                await confirm_msg.edit_text("❌ Broadcast cancelled (timeout).")
                return

        status_msg = await message.reply_text("📡 Starting broadcast...")

        # Progress callback
        async def update_progress(stats: Dict[str, int]):
            text = (
                f"📡 <b>Broadcast Progress</b>\n\n"
                f"Total: {stats['total']}\n"
                f"✅ Success: {stats['success']}\n"
                f"🚫 Blocked: {stats['blocked']}\n"
                f"❌ Deleted: {stats['deleted']}\n"
                f"⚠️ Failed: {stats['failed']}\n\n"
                f"⏳ Progress: {((stats['success'] + stats['blocked'] + stats['deleted'] + stats['failed']) / stats['total'] * 100):.1f}%"
            )

            try:
                await status_msg.edit_text(text)
            except FloodWait as e:
                await asyncio.sleep(e.value)

        # Start broadcast
        start_time = datetime.now()
        final_stats = await self.bot.broadcast_service.broadcast_to_users(
            client,  # Add client parameter
            broadcast_msg,
            progress_callback=update_progress
        )

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

        await status_msg.edit_text(final_text)

        # Log broadcast
        if self.bot.config.LOG_CHANNEL:
            await client.send_message(
                self.bot.config.LOG_CHANNEL,
                f"#Broadcast\n"
                f"Admin: {message.from_user.mention}\n"
                f"Total: {final_stats['total']:,}\n"
                f"Success: {final_stats['success']:,}"
            )

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
                    "**Usage:** `/ban <user_id> [reason]`\n\n"
                    "**Examples:**\n"
                    "• `/ban 123456789`\n"
                    "• `/ban 123456789 Spamming`\n"
                    "• `/ban 123456789 \"Spamming and hate speech\"`"
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
                "🚫 **You have been banned from using this bot**\n\n"
                f"**Reason:** {reason}\n"
                f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                "If you believe this is a mistake, please contact the bot administrator."
            )

            notification_sent = await self._notify_user(client, target_user_id, ban_notification)

            # Log to admin channel
            if self.bot.config.LOG_CHANNEL:
                try:
                    log_text = (
                        f"#UserBanned\n\n"
                        f"**User:** `{target_user_id}` ({user_data.name})\n"
                        f"**Reason:** {reason}\n"
                        f"**Admin:** {message.from_user.mention}\n"
                        f"**Notification:** {'✅ Sent' if notification_sent else '❌ Failed'}\n"
                        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    await client.send_message(self.bot.config.LOG_CHANNEL, log_text)
                except Exception as e:
                    logger.error(f"Failed to log ban action: {e}")

    @admin_only
    async def unban_command(self, client: Client, message: Message):
        """Unban a user"""
        if len(message.command) < 2:
            await message.reply_text("**Usage:** `/unban <user_id>`")
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
                "✅ **You have been unbanned!**\n\n"
                f"You can now use the bot again.\n"
                f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                "Welcome back!"
            )

            notification_sent = await self._notify_user(client, target_user_id, unban_notification)

            # Log to admin channel
            if self.bot.config.LOG_CHANNEL:
                try:
                    log_text = (
                        f"#UserUnbanned\n\n"
                        f"**User:** `{target_user_id}` ({user_data.name})\n"
                        f"**Admin:** {message.from_user.mention}\n"
                        f"**Notification:** {'✅ Sent' if notification_sent else '❌ Failed'}\n"
                        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    await client.send_message(self.bot.config.LOG_CHANNEL, log_text)
                except Exception as e:
                    logger.error(f"Failed to log unban action: {e}")

    @admin_only
    async def add_premium_command(self, client: Client, message: Message):
        """Add premium status to user"""
        if len(message.command) < 2:
            await message.reply_text("**Usage:** `/addpremium <user_id>`")
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
                "🎉 **Congratulations! You have been upgraded to Premium!**\n\n"
                f"**Benefits:**\n"
                f"• Unlimited file downloads\n"
                f"• Priority support\n"
                f"• Advanced features\n"
                f"• Valid for {self.bot.config.PREMIUM_DURATION_DAYS} days\n\n"
                f"**Activated on:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                "Enjoy your premium access! 🌟"
            )

            notification_sent = await self._notify_user(client, target_user_id, premium_notification)

            # Log to admin channel
            if self.bot.config.LOG_CHANNEL:
                try:
                    log_text = (
                        f"#PremiumAdded\n\n"
                        f"**User:** `{target_user_id}` ({user_data.name})\n"
                        f"**Duration:** {self.bot.config.PREMIUM_DURATION_DAYS} days\n"
                        f"**Admin:** {message.from_user.mention}\n"
                        f"**Notification:** {'✅ Sent' if notification_sent else '❌ Failed'}\n"
                        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    await client.send_message(self.bot.config.LOG_CHANNEL, log_text)
                except Exception as e:
                    logger.error(f"Failed to log premium addition: {e}")

    @admin_only
    async def remove_premium_command(self, client: Client, message: Message):
        """Remove premium status from user"""
        if len(message.command) < 2:
            await message.reply_text("**Usage:** `/removepremium <user_id>`")
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
                "📋 **Your premium subscription has been removed**\n\n"
                f"**New Limits:**\n"
                f"• {self.bot.config.NON_PREMIUM_DAILY_LIMIT} files per day\n"
                f"• Standard support\n\n"
                f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                "Thank you for using our premium service!"
            )

            notification_sent = await self._notify_user(client, target_user_id, premium_removal_notification)

            # Log to admin channel
            if self.bot.config.LOG_CHANNEL:
                try:
                    log_text = (
                        f"#PremiumRemoved\n\n"
                        f"**User:** `{target_user_id}` ({user_data.name})\n"
                        f"**Admin:** {message.from_user.mention}\n"
                        f"**Notification:** {'✅ Sent' if notification_sent else '❌ Failed'}\n"
                        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
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
                "🚀 **Bot Performance Metrics**\n\n"
                f"**Event Loop:** {metrics['event_loop']}\n"
                f"**Mode:** {metrics.get('optimization', 'Standard Mode')}\n"
            )

            if metrics['event_loop'] == 'uvloop':
                text += f"**Performance:** {metrics.get('expected_improvement', 'Optimized')}\n"
            else:
                text += f"**Note:** {metrics.get('recommendation', '')}\n"

            text += (
                f"\n📊 **System Resources:**\n"
                f"├ Memory: {metrics['memory_mb']:.2f} MB\n"
                f"├ CPU: {metrics['cpu_percent']:.1f}%\n"
                f"├ Threads: {metrics['num_threads']}\n"
                f"├ File Descriptors: {metrics['num_fds']}\n"
                f"└ Pending Tasks: {metrics['pending_tasks']}\n\n"
                f"⏱ **Uptime:** {uptime_str}"
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
                "📊 **Cache Statistics**\n\n"
                "**Memory Usage:**\n"
                f"├ Used: {stats['memory']['used_memory_human']}\n"
                f"├ RSS: {stats['memory']['used_memory_rss_human']}\n"
                f"├ Peak: {stats['memory']['used_memory_peak_human']}\n"
                f"└ Fragmentation: {stats['memory']['mem_fragmentation_ratio']}\n\n"

                "**Performance:**\n"
                f"├ Hit Rate: {stats['performance']['cache_hit_rate']}\n"
                f"├ Hits: {stats['performance']['keyspace_hits']:,}\n"
                f"├ Misses: {stats['performance']['keyspace_misses']:,}\n"
                f"└ Ops/sec: {stats['performance']['instantaneous_ops_per_sec']}\n\n"

                "**Keys by Type:**\n"
            )

            for pattern, count in stats['keys']['by_pattern'].items():
                text += f"├ {pattern}: {count:,}\n"

            text += f"\n**Total Keys:** {stats['keys']['total_keys']:,}"
            text += f"\n**Keys with TTL:** {stats['keys']['expires']:,}"

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

            text = "🔍 **Cache Analysis**\n\n"

            if duplicates:
                text += f"**⚠️ Found {len(duplicates)} duplicate entries:**\n"
                for dup in duplicates[:5]:  # Show first 5
                    text += f"├ File {dup['file_id'][:10]}... has {dup['count']} cache entries\n"
                if len(duplicates) > 5:
                    text += f"└ ... and {len(duplicates) - 5} more\n"
                text += "\n"

            if analysis['large_values']:
                text += f"**📦 Large Cache Values ({len(analysis['large_values'])}):**\n"
                for item in analysis['large_values'][:3]:
                    text += f"├ {item['key'][:30]}... - {item['size_human']}\n"
                text += "\n"

            if analysis['no_ttl']:
                text += f"**⏰ Keys without TTL: {len(analysis['no_ttl'])}**\n\n"

            text += "**📊 Key Size Distribution:**\n"
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
                "⚠️ **Cache Cleanup**\n\n"
                "This will remove duplicate cache entries.\n"
                "Use `/cache_cleanup confirm` to proceed."
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
                f"✅ **Cache Cleanup Complete**\n\n"
                f"Removed {cleaned} duplicate entries\n"
                f"Freed up memory from {len(duplicates)} files"
            )

        except Exception as e:
            await status_msg.edit_text(f"❌ Error: {str(e)}")

    async def shell_command(self, client: Client, message: Message):
        """Execute shell commands - ONLY for primary admin"""
        # Check if user is the first admin
        user_id = message.from_user.id if message.from_user else None
        if not user_id or user_id != self.bot.config.ADMINS[0]:
            await message.reply_text("⚠️ This command is restricted to the primary admin only.")
            return

        # Get command from message
        if len(message.command) < 2:
            await message.reply_text(
                "**Usage:** `/shell <command>`\n\n"
                "**Examples:**\n"
                "• `/shell ls -la`\n"
                "• `/shell df -h`\n"
                "• `/shell ps aux | grep python`\n\n"
                "⚠️ **Warning:** Use with extreme caution!"
            )
            return

        # Get the command (everything after /shell)
        shell_command = message.text.split(None, 1)[1]

        # Log the command execution
        logger.warning(f"Shell command executed by {user_id}: {shell_command}")

        # Send processing message
        processing_msg = await message.reply_text("⏳ Executing command...")

        try:
            # Execute the command with timeout
            process = await asyncio.create_subprocess_shell(
                shell_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Limit resources
                preexec_fn=lambda: __import__('resource').setrlimit(
                    __import__('resource').RLIMIT_CPU, (30, 30)
                ) if hasattr(__import__('resource'), 'setrlimit') else None
            )

            # Wait for command to complete with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=30.0  # 30 second timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await processing_msg.edit_text("❌ Command timed out after 30 seconds.")
                return

            # Decode output
            stdout_text = stdout.decode('utf-8', errors='replace') if stdout else ""
            stderr_text = stderr.decode('utf-8', errors='replace') if stderr else ""

            # Combine output
            output = ""
            if stdout_text:
                output += f"**STDOUT:**\n```\n{stdout_text}\n```\n"
            if stderr_text:
                output += f"**STDERR:**\n```\n{stderr_text}\n```\n"

            if not output:
                output = "✅ Command executed successfully (no output)"

            # Add return code
            output += f"\n**Return Code:** {process.returncode}"

            # Check output size (Telegram message limit is 4096 characters)
            if len(output) > 4000:
                # Save to temporary file
                with tempfile.NamedTemporaryFile(
                        mode='w',
                        suffix='.txt',
                        delete=False,
                        encoding='utf-8'
                ) as temp_file:
                    temp_file.write(f"Command: {shell_command}\n")
                    temp_file.write("=" * 50 + "\n\n")

                    if stdout_text:
                        temp_file.write("STDOUT:\n")
                        temp_file.write("-" * 30 + "\n")
                        temp_file.write(stdout_text)
                        temp_file.write("\n\n")

                    if stderr_text:
                        temp_file.write("STDERR:\n")
                        temp_file.write("-" * 30 + "\n")
                        temp_file.write(stderr_text)
                        temp_file.write("\n\n")

                    temp_file.write(f"Return Code: {process.returncode}\n")
                    temp_filename = temp_file.name

                try:
                    # Send as document
                    await message.reply_document(
                        document=temp_filename,
                        caption=f"📄 **Shell Output**\n\nCommand: `{shell_command[:100]}{'...' if len(shell_command) > 100 else ''}`\nReturn Code: {process.returncode}",
                        file_name=f"shell_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    )

                    # Delete processing message
                    await processing_msg.delete()

                finally:
                    # Clean up temp file
                    try:
                        os.unlink(temp_filename)
                    except Exception as e:
                        logger.error(f"Failed to delete temp file: {e}")
            else:
                # Send as regular message
                await processing_msg.edit_text(output)

            # Log to admin channel if configured
            if self.bot.config.LOG_CHANNEL:
                log_text = (
                    f"#ShellCommand\n\n"
                    f"**Admin:** {message.from_user.mention}\n"
                    f"**Command:** `{shell_command[:200]}{'...' if len(shell_command) > 200 else ''}`\n"
                    f"**Return Code:** {process.returncode}\n"
                    f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )

                try:
                    await client.send_message(self.bot.config.LOG_CHANNEL, log_text)
                except Exception as e:
                    logger.error(f"Failed to log shell command: {e}")

        except Exception as e:
            error_msg = f"❌ **Error executing command:**\n\n`{str(e)}`"
            await processing_msg.edit_text(error_msg)
            logger.error(f"Shell command error: {e}", exc_info=True)