from pyrogram import Client, enums
from pyrogram.types import Message

from core.utils.logger import get_logger
from core.utils.validators import admin_only
from handlers.commands_handlers.base import BaseCommandHandler

logger = get_logger(__name__)


class ChannelCommandHandler(BaseCommandHandler):
    """Handler for channel management commands"""

    @admin_only
    async def add_channel_command(self, client: Client, message: Message):
        """Add a channel for automatic indexing"""
        if len(message.command) < 2:
            await message.reply_text(
                "Usage: /add_channel <channel_id or @username>\n\n"
                "Examples:\n"
                "• /add_channel -1001234567890\n"
                "• /add_channel @channelname"
            )
            return

        channel_input = message.command[1]

        # Parse channel input
        try:
            # Check if it's a numeric ID
            channel_id = int(channel_input)
        except ValueError:
            # It's a username, try to get channel info
            try:
                chat = await client.get_chat(channel_input)
                channel_id = chat.id
                channel_username = chat.username
                channel_title = chat.title
            except Exception as e:
                error_msg = str(e).lower()
                if "channel_private" in error_msg:
                    await message.reply_text(
                        "❌ <b>Cannot Access Channel</b>\n\n"
                        "This is a private channel. Please:\n"
                        "1. Add me to the channel first\n"
                        "2. Make me an admin\n"
                        "3. Try the command again"
                    )
                    return
                elif "username_invalid" in error_msg or "username_not_occupied" in error_msg:
                    await message.reply_text("❌ Invalid username. Please check and try again.")
                    return
                else:
                    await message.reply_text(f"❌ Error: Could not find channel. {str(e)}")
                    return
        else:
            # It's a numeric ID, try to get channel info
            try:
                chat = await client.get_chat(channel_id)
                channel_username = chat.username
                channel_title = chat.title
            except Exception as e:
                error_msg = str(e).lower()
                if "channel_private" in error_msg:
                    # Channel might be private or bot not member
                    await message.reply_text(
                        "❌ <b>Cannot Access Channel</b>\n\n"
                        "This channel is private or I'm not a member.\n"
                        "Please add me to the channel as an admin first.\n\n"
                        "If you've already added me, wait a moment and try again."
                    )
                    return
                else:
                    # Channel might be private or bot not member
                    channel_username = None
                    channel_title = f"Channel {channel_id}"

        # Verify bot is in the channel
        try:
            member = await client.get_chat_member(channel_id, "me")
            if member.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.MEMBER]:
                await message.reply_text(
                    "❌ I need to be a member/admin of the channel to index files.\n"
                    "Please add me to the channel first."
                )
                return
        except Exception as e:
            error_msg = str(e).lower()
            if "channel_private" in error_msg or "user_not_participant" in error_msg:
                await message.reply_text(
                    "⚠️ <b>Warning:</b> I cannot verify my membership in this channel.\n\n"
                    "Make sure:\n"
                    "1. I'm added to the channel\n"
                    "2. I'm an admin (for private channels)\n"
                    "3. The channel exists\n\n"
                    "Adding anyway, but indexing might fail."
                )
            else:
                await message.reply_text(
                    "⚠️ Warning: Could not verify channel membership.\n"
                    "Make sure I'm added to the channel for indexing to work."
                )

        # Add channel to database
        channel_repo = self.bot.channel_handler.channel_repo
        success = await channel_repo.add_channel(
            channel_id=channel_id,
            channel_username=channel_username,
            channel_title=channel_title,
            added_by=message.from_user.id
        )

        if success:
            # Update handlers immediately
            await self.bot.channel_handler.update_handlers()

            response = (
                f"✅ Channel added successfully!\n\n"
                f"📢 <b>Channel:</b> {channel_title or channel_input}\n"
                f"🆔 <b>ID:</b> <code>{channel_id}</code>\n"
            )
            if channel_username:
                response += f"👤 <b>Username:</b> @{channel_username}\n"
            response += f"\n📌 Files posted to this channel will now be automatically indexed."

            await message.reply_text(response)

            # Log action
            if self.bot.config.LOG_CHANNEL:
                await client.send_message(
                    self.bot.config.LOG_CHANNEL,
                    f"#ChannelAdded\n"
                    f"Channel: {channel_title or channel_id}\n"
                    f"ID: <code>{channel_id}</code>\n"
                    f"Added by: {message.from_user.mention}"
                )
        else:
            await message.reply_text("❌ Failed to add channel. Please try again.")

    @admin_only
    async def remove_channel_command(self, client: Client, message: Message):
        """Remove a channel from automatic indexing"""
        if len(message.command) < 2:
            await message.reply_text(
                "Usage: /remove_channel <channel_id or @username>\n\n"
                "Examples:\n"
                "• /remove_channel -1001234567890\n"
                "• /remove_channel @channelname"
            )
            return

        channel_input = message.command[1]

        # Parse channel input
        try:
            channel_id = int(channel_input)
        except ValueError:
            # It's a username, try to get channel info
            try:
                chat = await client.get_chat(channel_input)
                channel_id = chat.id
            except Exception:
                await message.reply_text("❌ Error: Could not find channel.")
                return

        # Get channel info before removing
        channel_repo = self.bot.channel_handler.channel_repo
        channel = await channel_repo.find_by_id(channel_id)

        if not channel:
            await message.reply_text("❌ Channel not found in the indexing list.")
            return

        # Remove channel
        success = await channel_repo.remove_channel(channel_id)
        logger.info(f"Remove channel success : {success}")

        if success:
            # Update handlers immediately
            await self.bot.channel_handler.update_handlers()

            response = (
                f"✅ Channel removed successfully!\n\n"
                f"📢 <b>Channel:</b> {channel.channel_title or channel_id}\n"
                f"🆔 <b>ID:</b> <code>{channel_id}</code>\n"
                f"📊 <b>Files indexed:</b> {channel.indexed_count}\n"
                f"\n📌 This channel will no longer be indexed automatically."
            )

            await message.reply_text(response)

            # Log action
            if self.bot.config.LOG_CHANNEL:
                await client.send_message(
                    self.bot.config.LOG_CHANNEL,
                    f"#ChannelRemoved\n"
                    f"Channel: {channel.channel_title or channel_id}\n"
                    f"ID: <code>{channel_id}</code>\n"
                    f"Files indexed: {channel.indexed_count}\n"
                    f"Removed by: {message.from_user.mention}"
                )
        else:
            await message.reply_text("❌ Failed to remove channel. Please try again.")

    @admin_only
    async def list_channels_command(self, client: Client, message: Message):
        """List all channels configured for automatic indexing"""
        channel_repo = self.bot.channel_handler.channel_repo
        stats = await channel_repo.get_channel_stats()

        if stats['total_channels'] == 0:
            await message.reply_text(
                "📢 No channels configured for automatic indexing.\n\n"
                "Use /add_channel to add channels."
            )
            return

        # Build response
        response = (
            f"📊 <b>Channel Statistics</b>\n\n"
            f"Total Channels: {stats['total_channels']}\n"
            f"✅ Active: {stats['active_channels']}\n"
            f"❌ Disabled: {stats['disabled_channels']}\n"
            f"📁 Total Files Indexed: {stats['total_files_indexed']}\n\n"
            f"<b>📢 Channels List:</b>\n\n"
        )

        for channel in stats['channels']:
            status_emoji = "✅" if channel.enabled else "❌"
            response += f"{status_emoji} "

            if channel.channel_title:
                response += f"<b>{channel.channel_title}</b>\n"
            else:
                response += f"<b>Channel {channel.channel_id}</b>\n"

            response += f"   🆔 ID: <code>{channel.channel_id}</code>\n"

            if channel.channel_username:
                response += f"   👤 Username: @{channel.channel_username}\n"

            response += f"   📁 Files indexed: {channel.indexed_count}\n"

            if channel.last_indexed_at:
                response += f"   ⏰ Last indexed: {channel.last_indexed_at.strftime('%Y-%m-%d %H:%M')}\n"

            response += "\n"

        # Add help text
        response += (
            "\n<b>Commands:</b>\n"
            "• /add_channel - Add a new channel\n"
            "• /remove_channel - Remove a channel\n"
            "• /toggle_channel - Enable/disable a channel"
        )

        await message.reply_text(response)

    @admin_only
    async def toggle_channel_command(self, client: Client, message: Message):
        """Toggle channel indexing on/off"""
        if len(message.command) < 2:
            await message.reply_text(
                "Usage: /toggle_channel <channel_id or @username>\n\n"
                "This command enables/disables automatic indexing for a channel without removing it."
            )
            return

        channel_input = message.command[1]

        # Parse channel input
        try:
            channel_id = int(channel_input)
        except ValueError:
            # It's a username, try to get channel info
            try:
                chat = await client.get_chat(channel_input)
                channel_id = chat.id
            except Exception:
                await message.reply_text("❌ Error: Could not find channel.")
                return

        # Get channel info
        channel_repo = self.bot.channel_handler.channel_repo
        channel = await channel_repo.find_by_id(channel_id)

        if not channel:
            await message.reply_text("❌ Channel not found in the indexing list.")
            return

        # Toggle status
        new_status = not channel.enabled
        success = await channel_repo.update_channel_status(channel_id, new_status)

        if success:
            # Update handlers immediately
            await self.bot.channel_handler.update_handlers()

            status_text = "enabled" if new_status else "disabled"
            emoji = "✅" if new_status else "❌"

            response = (
                f"{emoji} Channel {status_text}!\n\n"
                f"📢 <b>Channel:</b> {channel.channel_title or channel_id}\n"
                f"🆔 <b>ID:</b> <code>{channel_id}</code>\n"
                f"📊 <b>Status:</b> {'Active' if new_status else 'Disabled'}\n"
            )

            await message.reply_text(response)
        else:
            await message.reply_text("❌ Failed to update channel status.")