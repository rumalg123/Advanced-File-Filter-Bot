# handlers/filter.py
import io
import shlex
from typing import List

from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from core.utils.button_builder import ButtonBuilder
from core.utils.caption import CaptionFormatter
from core.utils.logger import get_logger
from core.utils.validators import extract_user_id, has_admin_rights, is_owner_or_bot_admin
from handlers.base import BaseHandler

logger = get_logger(__name__)


class FilterHandler(BaseHandler):
    """Handler for filter-related commands and messages"""

    def __init__(self, bot):
        super().__init__(bot)
        self.filter_service = bot.filter_service
        self.connection_service = bot.connection_service
        self.register_handlers()

    def register_handlers(self) -> None:
        """Register filter handlers"""
        # Check if filters are disabled
        if self.bot.config.DISABLE_FILTER:
            logger.info("Filters are disabled via DISABLE_FILTER config")
            return

        # Command handlers - use BaseHandler's method
        self._register_message_handlers([
            (self.add_filter_command, filters.command(["add", "filter"]) & (filters.private | filters.group)),
            (self.view_filters_command,
             filters.command(["filters", "viewfilters"]) & (filters.private | filters.group)),
            (self.delete_filter_command, filters.command(["delf", "deletef"]) & (filters.private | filters.group)),
            (self.delete_all_command, filters.command(["delallf", "deleteallf"]) & (filters.private | filters.group))
        ])

        logger.info(f"FilterHandler registered {len(self._handlers)} handlers")

    # cleanup() method is inherited from BaseHandler

    def _split_quotes(self, text: str) -> List[str]:
        """Split text respecting quotes"""
        try:
            return shlex.split(text)
        except ValueError:
            return text.split(None, 1)

    async def add_filter_command(self, client: Client, message: Message):
        """Handle add filter command"""
        user_id = extract_user_id(message)
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

        # Check for similar existing filters using fuzzy matching
        all_filters = await self.filter_service.get_all_filters(str(group_id))
        if all_filters:
            from core.utils.helpers import find_similar_queries
            similar_filters = find_similar_queries(
                keyword,
                [f.lower() for f in all_filters],
                threshold=85.0,  # 85% similarity (very similar)
                max_results=3
            )
            
            if similar_filters:
                suggestions = [f[0] for f in similar_filters]
                suggestion_text = "\n".join([f"• <code>{s}</code>" for s in suggestions])
                warning_msg = (
                    f"⚠️ <b>Similar filter(s) already exist:</b>\n{suggestion_text}\n\n"
                    f"Are you sure you want to add <code>{keyword}</code>?\n"
                    f"This might create duplicate filters."
                )
                # Still allow adding, but warn the user
                # Could add a confirmation step here if needed
                pass  # For now, just continue (could add confirmation callback)

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
                parse_mode=CaptionFormatter.get_parse_mode()
            )
        else:
            return await message.reply_text("Failed to add filter!", quote=True)

    async def view_filters_command(self, client: Client, message: Message):
        """Handle view filters command"""
        user_id = extract_user_id(message)
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
            parse_mode=CaptionFormatter.get_parse_mode()
        )

    async def delete_filter_command(self, client: Client, message: Message):
        """Handle delete filter command"""
        user_id = extract_user_id(message)
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
            args = shlex.split(message.text)
            if len(args) < 2:
                raise ValueError("No filter names provided")
            filters_to_delete = args[1:]
        except (ValueError, IndexError):
            return await message.reply_text(
                "<i>Mention the filtername which you wanna delete!</i>\n"
                "<code>/del filtername</code>\n"
                "Use /filters to view all available filters",
                quote=True
            )

        # Delete filters
        all_filters = await self.filter_service.get_all_filters(str(group_id))
        deleted_count = 0
        not_found = []
        
        for filter_name in filters_to_delete:
            filter_name_lower = filter_name.lower()
            
            # Check exact match first
            if filter_name_lower in [f.lower() for f in all_filters]:
                deleted = await self.filter_service.delete_filter(str(group_id), filter_name_lower)
                if deleted:
                    deleted_count += 1
                    await message.reply_text(
                        f"<code>{filter_name}</code> deleted. I'll not respond to that filter anymore.",
                        quote=True,
                        parse_mode=CaptionFormatter.get_parse_mode()
                    )
                else:
                    not_found.append(filter_name)
            else:
                # Try fuzzy matching to suggest similar filters
                from core.utils.helpers import find_similar_queries
                similar_filters = find_similar_queries(
                    filter_name_lower,
                    [f.lower() for f in all_filters],
                    threshold=70.0,  # 70% similarity
                    max_results=3
                )
                
                if similar_filters:
                    suggestions = [f[0] for f in similar_filters]
                    suggestion_text = "\n".join([f"• <code>{s}</code>" for s in suggestions])
                    await message.reply_text(
                        f"❌ Filter <code>{filter_name}</code> not found.\n\n"
                        f"💡 <b>Did you mean?</b>\n{suggestion_text}\n\n"
                        f"Use: <code>/del {' '.join(suggestions[:1])}</code>",
                        quote=True
                    )
                else:
                    not_found.append(filter_name)
        
        # Report any filters that weren't found and had no suggestions
        if not_found and deleted_count == 0:
            # Only show if we didn't delete anything and no suggestions were shown
            pass  # Already handled above with suggestions

    async def delete_all_command(self, client: Client, message: Message):
        """Handle delete all filters command"""
        user_id = extract_user_id(message)
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
                [ButtonBuilder.action_button(text="YES", callback_data=f"delallconfirm#{group_id}")],
                [ButtonBuilder.action_button(text="CANCEL", callback_data="delallcancel")]
            ]),
            quote=True
        )

    async def _check_admin_rights(self, client: Client, group_id: int, user_id: int) -> bool:
        """Check if user has admin rights in the group"""
        return await has_admin_rights(client, group_id, user_id, self.bot.config.ADMINS)

    async def _is_owner_or_bot_admin(self, client: Client, group_id: int, user_id: int) -> bool:
        """Check if user is group owner or bot admin"""
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
                # Get file ID using unified extractor
                from core.utils.media_extractor import extract_media_by_type
                
                if isinstance(message.reply_to_message.media, enums.MessageMediaType):
                    media = extract_media_by_type(message.reply_to_message, message.reply_to_message.media)
                    if media:
                        fileid = media.file_id

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