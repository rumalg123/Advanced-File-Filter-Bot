import asyncio
import re
from typing import Optional

from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler
from pyrogram.types import Message
from pyrogram.enums import ParseMode
from core.services.filestore import FileStoreService
from core.utils.errors import ErrorFactory, ErrorCode
from core.utils.logger import get_logger
from core.utils.link_parser import TelegramLinkParser

logger = get_logger(__name__)


class FileStoreHandler:
    """Handler for file store operations"""

    def __init__(self, bot, filestore_service: Optional[FileStoreService] = None) -> None:
        self.bot = bot
        # Use injected service or create new one (fallback)
        self.filestore_service = bot.filestore_service
        self._handlers = []  # Track handlers
        self._shutdown = asyncio.Event()
        self.register_handlers()

    def register_handlers(self):
        """Register filestore handlers"""
        handlers_to_register = []

        # Link generation commands
        if self.bot.config.ADMINS:
            # Admin-only commands
            handlers_to_register.extend([
                (self.link_command, filters.command(['link', 'plink']) & filters.user(self.bot.config.ADMINS)),
                (self.batch_command, filters.command(['batch', 'pbatch']) & filters.user(self.bot.config.ADMINS)),
                (self.premium_batch_command, filters.command(['batch_premium', 'bprem', 'pbatch_premium', 'pbprem']) & filters.user(self.bot.config.ADMINS))
            ])

        # Public file store (if enabled)
        if hasattr(self.bot.config, 'PUBLIC_FILE_STORE') and self.bot.config.PUBLIC_FILE_STORE:
            handlers_to_register.extend([
                (self.link_command, filters.command(['link', 'plink'])),
                (self.batch_command, filters.command(['batch', 'pbatch'])),
                (self.premium_batch_command, filters.command(['batch_premium', 'bprem', 'pbatch_premium', 'pbprem']))
            ])

        # Register all handlers
        for handler_func, handler_filter in handlers_to_register:
            handler = MessageHandler(handler_func, handler_filter)

            # Use handler_manager if available
            if hasattr(self.bot, 'handler_manager') and self.bot.handler_manager:
                self.bot.handler_manager.add_handler(handler)
            else:
                self.bot.add_handler(handler)

            self._handlers.append(handler)

        logger.info(f"FileStoreHandler registered {len(self._handlers)} handlers")

    async def cleanup(self):
        """Clean up handler resources"""
        logger.info("Cleaning up FileStoreHandler...")

        # Signal shutdown
        self._shutdown.set()

        # If handler_manager is available, let it handle everything
        if hasattr(self.bot, 'handler_manager') and self.bot.handler_manager:
            logger.info("HandlerManager will handle handler removal")
            # Mark our handlers as removed in the manager
            for handler in self._handlers:
                handler_id = id(handler)
                self.bot.handler_manager.removed_handlers.add(handler_id)
            self._handlers.clear()
            logger.info("FileStoreHandler cleanup complete")
            return

        # Manual cleanup only if no handler_manager
        for handler in self._handlers:
            try:
                self.bot.remove_handler(handler)
            except ValueError as e:
                if "x not in list" in str(e):
                    logger.debug(f"Handler already removed")
                else:
                    logger.error(f"Error removing handler: {e}")
            except Exception as e:
                logger.error(f"Error removing handler: {e}")

        self._handlers.clear()
        logger.info("FileStoreHandler cleanup complete")

    async def link_command(self, client: Client, message: Message) -> None:
        """Generate shareable link for a file"""
        if not message.reply_to_message:
            await message.reply('Reply to a message to get a shareable link.')
            return

        # Check if it's a protected link request
        protect = message.text.lower().strip().startswith("/plink")

        # Generate link
        link = await self.filestore_service.create_file_link(
            client,
            message,
            protect=protect
        )

        if link:
            await message.reply(f"Here is your Link:\n{link}")
        else:
            await message.reply("Failed to generate link. Make sure you replied to a supported media.")

    async def batch_command(self, client: Client, message: Message) -> None:
        """Generate batch link for multiple files"""
        # Parse command
        parts = message.text.strip().split(" ")

        if len(parts) != 3:
            await message.reply(
                "Use correct format.\n"
                "Example: `/batch https://t.me/channel/10 https://t.me/channel/20`"
            )
            return

        cmd, first_link, last_link = parts
        logger.debug(f"cmd: {cmd}, first_link: {first_link}, last_link: {last_link}")
        protect = cmd.lower() == "/pbatch"

        # Create batch link
        sts = await message.reply(
            "Generating link for your batch...\nThis may take time depending upon number of messages")

        link = await self.filestore_service.create_batch_link(
            client,
            first_link,
            last_link,
            protect=protect
        )

        if link:
            # Count messages using centralized parser
            first_parsed = TelegramLinkParser.parse_link(first_link)
            last_parsed = TelegramLinkParser.parse_link(last_link)
            
            f_msg_id = first_parsed.message_id if first_parsed else 0
            l_msg_id = last_parsed.message_id if last_parsed else 0

            total_msgs = abs(l_msg_id - f_msg_id) + 1

            await sts.edit(
                f"Here is your link\n"
                f"Contains approximately `{total_msgs}` messages.\n"
                f"{link}"
            )
        else:
            await sts.edit(
                "Failed to generate batch link.\n"
                "Make sure:\n"
                "• Both links are from the same channel\n"
                "• Bot has access to the channel\n"
                "• Links are in correct format"
            )

    async def premium_batch_command(self, client: Client, message: Message) -> None:
        """Generate premium-only batch link for multiple files with enhanced validation"""
        # Parse command with robust validation
        parts = message.text.strip().split(" ")

        if len(parts) != 3:
            await message.reply(
                "**🚫 Invalid Format**\n\n"
                "**Usage:**\n"
                "• `/batch_premium <first_link> <last_link>`\n"
                "• `/pbatch_premium <first_link> <last_link>`\n\n"
                "**Short aliases:**\n"
                "• `/bprem <first_link> <last_link>`\n"
                "• `/pbprem <first_link> <last_link>`\n\n"
                "**Example:**\n"
                "`/batch_premium https://t.me/channel/100 https://t.me/channel/200`",
                parse_mode=ParseMode.HTML
            )
            return

        cmd, first_link, last_link = parts
        logger.info(f"Premium batch command", extra={
            "event": "batch.command.premium",
            "user_id": message.from_user.id,
            "command": cmd,
            "first_link": first_link,
            "last_link": last_link
        })
        
        # Determine if it's a protected batch
        protect = cmd.lower() in ["/pbatch_premium", "/pbprem"]

        # Pre-validate links using robust parser
        parsed_links = TelegramLinkParser.parse_link_pair(first_link, last_link)
        if not parsed_links:
            await message.reply(
                "❌ **Invalid Links**\n\n"
                "Please check that:\n"
                "• Both links are valid Telegram message links\n"
                "• Both links are from the same channel\n"
                "• First message ID is less than second message ID\n"
                "• Batch size is reasonable (< 10,000 messages)\n\n"
                "**Valid formats:**\n"
                "• `https://t.me/channel/123`\n"
                "• `https://t.me/c/1234567890/123`",
                parse_mode=ParseMode.HTML
            )
            return

        first_parsed, last_parsed = parsed_links
        message_count = last_parsed.message_id - first_parsed.message_id + 1

        # Create premium batch link
        sts = await message.reply(
            f"🔄 **Generating Premium Batch Link**\n\n"
            f"📊 **Messages**: ~{message_count:,}\n"
            f"📡 **Source**: {first_parsed.chat_identifier}\n"
            f"💎 **Type**: {'Protected Premium' if protect else 'Premium'}\n\n"
            f"⏳ *This may take a moment...*"
        )

        try:
            link = await self.filestore_service.create_premium_batch_link(
                client,
                first_link,
                last_link,
                protect=protect,
                premium_only=True,
                created_by=message.from_user.id
            )

            if link:
                batch_type = "Protected Premium" if protect else "Premium"
                
                await sts.edit(
                    f"✅ **{batch_type} Batch Link Created**\n\n"
                    f"📦 **Messages**: ~{message_count:,}\n"
                    f"📡 **Source**: `{first_parsed.chat_identifier}`\n"
                    f"📋 **Range**: `{first_parsed.message_id}` → `{last_parsed.message_id}`\n"
                    f"💎 **Access**: Premium users only\n"
                    f"🔒 **Protection**: {'Non-forwardable content' if protect else 'Standard content'}\n\n"
                    f"🔗 **Link**: {link}\n\n"
                    f"⚡ **Access Rules**:\n"
                    f"• Link-level premium overrides global settings\n"
                    f"• Works even when global premium is disabled\n"
                    f"• Only premium users can access this content",
                    parse_mode=ParseMode.HTML
                )
            else:
                await sts.edit(
                    "❌ **Failed to Generate Premium Batch Link**\n\n"
                    "**Please check:**\n"
                    "• Bot has access to the source channel\n"
                    "• Links are valid and from the same channel\n"
                    "• Database is accessible\n"
                    "• You have permission to create batch links\n\n"
                    "*Try again in a few moments*",
                    parse_mode=ParseMode.HTML
                )
        except Exception as e:
            logger.error(f"Error creating premium batch link: {e}", extra={
                "event": "batch.command.error",
                "user_id": message.from_user.id,
                "error": str(e)
            })
            await sts.edit(
                "❌ **System Error**\n\n"
                "An unexpected error occurred while creating the batch link.\n"
                "Please try again later or contact support.",
                parse_mode=ParseMode.HTML
            )