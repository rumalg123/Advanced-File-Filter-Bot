import logging
import re

from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler
from pyrogram.types import Message

from core.services.filestore import FileStoreService

from core.utils.logger import get_logger
logger = get_logger(__name__)


class FileStoreHandler:
    """Handler for file store operations"""

    def __init__(self, bot, filestore_service: FileStoreService = None):
        self.bot = bot
        # Use injected service or create new one (fallback)
        self.filestore_service = bot.filestore_service
        self.register_handlers()

    def register_handlers(self):
        """Register filestore handlers"""
        # Link generation commands
        if self.bot.config.ADMINS:
            # Admin-only commands
            self.bot.add_handler(
                MessageHandler(
                    self.link_command,
                    filters.command(['link', 'plink']) & filters.user(self.bot.config.ADMINS)
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.batch_command,
                    filters.command(['batch', 'pbatch']) & filters.user(self.bot.config.ADMINS)
                )
            )

        # Public file store (if enabled)
        if hasattr(self.bot.config, 'PUBLIC_FILE_STORE') and self.bot.config.PUBLIC_FILE_STORE:
            self.bot.add_handler(
                MessageHandler(
                    self.link_command,
                    filters.command(['link', 'plink'])
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.batch_command,
                    filters.command(['batch', 'pbatch'])
                )
            )

    async def link_command(self, client: Client, message: Message):
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

    async def batch_command(self, client: Client, message: Message):
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
            # Count messages
            # In batch_command method, after "# Count messages" comment, update the link_pattern:
            # In batch_command method, after "# Count messages" comment:
            link_pattern = re.compile(
                r"(?:https?://)?(?:t\.me|telegram\.me|telegram\.dog)/"
                r"(?:c/)?(\d+|[a-zA-Z][a-zA-Z0-9_-]*)/(\d+)/?$"
            )

            match = link_pattern.match(first_link)
            f_msg_id = int(match.group(2)) if match else 0

            match = link_pattern.match(last_link)
            l_msg_id = int(match.group(2)) if match else 0

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