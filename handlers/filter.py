# handlers/filter.py
import asyncio
import io
from typing import List

from pyrogram import Client, filters, enums
from pyrogram.handlers import MessageHandler
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from core.utils.logger import get_logger
from handlers.commands_handlers.base import BaseCommandHandler

logger = get_logger(__name__)


class FilterHandler(BaseCommandHandler):
    """Handler for filter-related commands and messages"""

    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot
        self.filter_service = bot.filter_service
        self.connection_service = bot.connection_service
        self._handlers = []  # Track handlers
        self._shutdown = asyncio.Event()
        self.register_handlers()

    def register_handlers(self):
        """Register filter handlers"""
        # Check if filters are disabled
        if self.bot.config.DISABLE_FILTER:
            logger.info("Filters are disabled via DISABLE_FILTER config")
            return

        # Command handlers
        handlers_to_register = [
            (self.add_filter_command, filters.command(["add", "filter"]) & (filters.private | filters.group)),
            (self.view_filters_command,
             filters.command(["filters", "viewfilters"]) & (filters.private | filters.group)),
            (self.delete_filter_command, filters.command(["delf", "deletef"]) & (filters.private | filters.group)),
            (self.delete_all_command, filters.command(["delallf", "deleteallf"]) & (filters.private | filters.group))
        ]

        for handler_func, handler_filter in handlers_to_register:
            handler = MessageHandler(handler_func, handler_filter)

            # Use handler_manager if available
            if hasattr(self.bot, 'handler_manager') and self.bot.handler_manager:
                self.bot.handler_manager.add_handler(handler)
            else:
                self.bot.add_handler(handler)

            self._handlers.append(handler)

        logger.info(f"FilterHandler registered {len(self._handlers)} handlers")

    async def cleanup(self):
        """Clean up handler resources"""
        logger.info("Cleaning up FilterHandler...")

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
            logger.info("FilterHandler cleanup complete")
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
        logger.info("FilterHandler cleanup complete")

    def _split_quotes(self, text: str) -> List[str]:
        """Split text respecting quotes"""
        import shlex
        try:
            return shlex.split(text)
        except:
            return text.split(None, 1)

    async def add_filter_command(self, client: Client, message: Message):
        """Handle add filter command"""
        user_id = message.from_user.id if message.from_user else None
        if not user_id:
            return await message.reply("You are anonymous admin. Use /connect in PM")

        # Get group ID based on context
        group_id, title = await self.filter_service.get_active_group_id(client,message)
        if not group_id:
            if title == "not_connected":
                return await message.reply_text(
                    "I'm not connected to any groups!\nCheck /connections or connect to any groups",
                    quote=True
                )
            return

        # Check admin rights
        if not await self._check_admin_rights(client, group_id, user_id):
            return await message.reply("You need to be an admin to add filters!")

        # Parse command arguments
        args = message.text.html.split(None, 1)
        if len(args) < 2:
            return await message.reply_text("Command Incomplete :(", quote=True)

        extracted = self._split_quotes(args[1])
        keyword = extracted[0].lower()

        # Extract filter content
        filter_data = await self._extract_filter_data(message, extracted, keyword)
        if not filter_data:
            return

        reply_text, btn, alert, fileid = filter_data

        # Add the filter
        success = await self.filter_service.add_filter(
            str(group_id),
            keyword,
            reply_text,
            str(btn),
            fileid,
            str(alert) if alert else None
        )

        if success:
            return await message.reply_text(
                f"Filter for <code>{keyword}</code> added in <b>{title}</b>",
                quote=True,
                parse_mode=enums.ParseMode.HTML
            )
        else:
            return await message.reply_text("Failed to add filter!", quote=True)

    async def view_filters_command(self, client: Client, message: Message):
        """Handle view filters command"""
        user_id = message.from_user.id if message.from_user else None
        if not user_id:
            return await message.reply("You are anonymous admin. Use /connect in PM")

        # Get group ID based on context
        group_id, title = await self.filter_service.get_active_group_id(client,message)
        if not group_id:
            if title == "not_connected":
                return await message.reply_text(
                    "I'm not connected to any groups!\nCheck /connections or connect to any groups",
                    quote=True
                )
            return

        # Check admin rights
        if not await self._check_admin_rights(client, group_id, user_id):
            return await message.reply("You need to be an admin to view filters!")

        filters = await self.filter_service.get_all_filters(str(group_id))
        count = await self.filter_service.count_filters(str(group_id))

        if count:
            filterlist = f"Total number of filters in <b>{title}</b>: {count}\n"
            keywords = "\n".join(f"{idx + 1}.  <code>{text}</code>" for idx, text in enumerate(sorted(filters)))
            filterlist += keywords

            if len(filterlist) > 4096:
                # Send as file if too long
                doc_keywords = "\n".join(f"{idx + 1}.  {text}" for idx, text in enumerate(sorted(filters)))
                doc_filterlist = f"Total number of filters in {title}: {count}\n{doc_keywords}"

                with io.BytesIO(str.encode(doc_filterlist)) as keyword_file:
                    keyword_file.name = "keywords.txt"
                    await message.reply_document(
                        document=keyword_file,
                        caption=f"Total number of filters in <b>{title}</b>: {count}",
                        quote=True
                    )
                return
        else:
            filterlist = f"There are no active filters in <b>{title}</b>"

        await message.reply_text(
            text=filterlist,
            quote=True,
            parse_mode=enums.ParseMode.HTML
        )

    async def delete_filter_command(self, client: Client, message: Message):
        """Handle delete filter command"""
        user_id = message.from_user.id if message.from_user else None
        if not user_id:
            return await message.reply("You are anonymous admin. Use /connect in PM")

        # Get group ID based on context
        group_id, title = await self.filter_service.get_active_group_id(client,message)
        if not group_id:
            if title == "not_connected":
                return await message.reply_text(
                    "I'm not connected to any groups!\nCheck /connections or connect to any groups",
                    quote=True
                )
            return

        # Check admin rights
        if not await self._check_admin_rights(client, group_id, user_id):
            return await message.reply("You need to be an admin to delete filters!")

        # Parse command
        try:
            import shlex
            args = shlex.split(message.text)
            if len(args) < 2:
                raise ValueError("No filter names provided")
            filters_to_delete = args[1:]
        except:
            return await message.reply_text(
                "<i>Mention the filtername which you wanna delete!</i>\n"
                "<code>/del filtername</code>\n"
                "Use /filters to view all available filters",
                quote=True
            )

        # Delete filters
        for filter_name in filters_to_delete:
            deleted = await self.filter_service.delete_filter(str(group_id), filter_name.lower())

            if deleted:
                await message.reply_text(
                    f"<code>{filter_name}</code> deleted. I'll not respond to that filter anymore.",
                    quote=True,
                    parse_mode=enums.ParseMode.HTML
                )
            else:
                await message.reply_text(f"Couldn't find filter: <code>{filter_name}</code>", quote=True)

    async def delete_all_command(self, client: Client, message: Message):
        """Handle delete all filters command"""
        user_id = message.from_user.id if message.from_user else None
        if not user_id:
            return await message.reply("You are anonymous admin. Use /connect in PM")

        # Get group ID based on context
        group_id, title = await self.filter_service.get_active_group_id(client,message)
        if not group_id:
            if title == "not_connected":
                return await message.reply_text(
                    "I'm not connected to any groups!\nCheck /connections or connect to any groups",
                    quote=True
                )
            return

        # Only group owner or bot admins can delete all
        if not await self._is_owner_or_bot_admin(client, group_id, user_id):
            return await message.reply("Only group owner or bot admins can delete all filters!")

        # Confirmation
        await message.reply_text(
            f"This will delete all filters from '{title}'.\nDo you want to continue??",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(text="YES", callback_data=f"delallconfirm#{group_id}")],
                [InlineKeyboardButton(text="CANCEL", callback_data="delallcancel")]
            ]),
            quote=True
        )

    async def _check_admin_rights(self, client: Client, group_id: int, user_id: int) -> bool:
        """Check if user has admin rights in the group"""
        from core.utils.validators import has_admin_rights
        return await has_admin_rights(client, group_id, user_id, self.bot.config.ADMINS)

    async def _is_owner_or_bot_admin(self, client: Client, group_id: int, user_id: int) -> bool:
        """Check if user is group owner or bot admin"""
        from core.utils.validators import is_owner_or_bot_admin
        return await is_owner_or_bot_admin(client, group_id, user_id, self.bot.config.ADMINS)

    async def _extract_filter_data(self, message: Message, extracted: List[str], keyword: str):
        """Extract filter data from message"""
        fileid = None
        reply_text = ""
        btn = "[]"
        alert = None

        if not message.reply_to_message and len(extracted) < 2:
            await message.reply_text("Add some content to save your filter!", quote=True)
            return None

        if len(extracted) >= 2 and not message.reply_to_message:
            # Parse the filter text
            reply_text, buttons, alerts = self.filter_service.parse_filter_text(
                extracted[1], keyword
            )
            btn = buttons if buttons else "[]"
            alert = alerts if alerts else None

            if not reply_text:
                await message.reply_text(
                    "You cannot have buttons alone, give some text to go with it!",
                    quote=True
                )
                return None

        elif message.reply_to_message:
            # Extract from replied message
            if message.reply_to_message.media:
                # Get file ID based on media type
                media_mapping = {
                    enums.MessageMediaType.DOCUMENT: "document",
                    enums.MessageMediaType.VIDEO: "video",
                    enums.MessageMediaType.AUDIO: "audio",
                    enums.MessageMediaType.ANIMATION: "animation",
                    enums.MessageMediaType.PHOTO: "photo",
                    enums.MessageMediaType.STICKER: "sticker"
                }

                for media_type, attr in media_mapping.items():
                    if message.reply_to_message.media == media_type:
                        media = getattr(message.reply_to_message, attr, None)
                        if media:
                            fileid = media.file_id
                            break

            # Get text or caption
            if message.reply_to_message.text:
                reply_text = message.reply_to_message.text.html
            elif message.reply_to_message.caption:
                reply_text = message.reply_to_message.caption.html

            # Handle buttons from reply markup
            if message.reply_to_message.reply_markup:
                btn = str(message.reply_to_message.reply_markup.inline_keyboard)

            # If additional text provided with command, parse it
            if len(extracted) >= 2:
                reply_text, buttons, alerts = self.filter_service.parse_filter_text(
                    extracted[1], keyword
                )
                if buttons:
                    btn = buttons
                if alerts:
                    alert = alerts

        return reply_text, btn, alert, fileid