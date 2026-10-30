import asyncio
import html
from pathlib import Path

from pyrogram import Client
from pyrogram import StopPropagation
from pyrogram.errors import MessageNotModified
from pyrogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from core.cache.config import CacheTTLConfig, CacheKeyGenerator
from core.utils.button_builder import ButtonBuilder
from core.utils.error_formatter import ErrorMessageFormatter
from core.utils.logger import get_logger
from core.utils.telegram_api import telegram_api
from handlers.base import BaseHandler

logger = get_logger(__name__)


class BotSettingsHandler(BaseHandler):
    """Handler for bot settings management"""
    PROTECTED_SETTINGS = [
        'DATABASE_URI',
        'DATABASE_NAME',
        'REDIS_URI',
        'API_ID',
        'API_HASH',
        'BOT_TOKEN',
        'SESSION'
    ]

    def __init__(self, bot):
        super().__init__(bot)
        self.settings_service = bot.bot_settings_service
        self.current_page = 0
        self.ttl = CacheTTLConfig()

        # Use unified session manager
        self.session_manager = getattr(bot, 'session_manager', None)

        # Handlers are registered through the main command handler system
        # so register_handlers() is intentionally empty

    def register_handlers(self) -> None:
        """
        Register handlers - intentionally empty.
        BotSettingsHandler's handlers are registered through the main command handler system.
        """
        pass

    # cleanup() method inherited from BaseHandler

    async def invalidate_related_caches(self, key: str):
        """Invalidate caches related to a specific setting"""
        await self.bot.cache_invalidator.invalidate_settings_cache(key)
        logger.info(f"Invalidated caches for setting: {key}")

    async def _cancel_captured_edit(self, user_id: int, session):
        """A completed older input must not cancel a newer owner dialog."""
        session_id = getattr(session, 'session_id', None)
        if session_id is None:
            return await self.session_manager.cancel_edit_session(user_id)
        return await self.session_manager.cancel_edit_session(user_id, session_id=session_id)

    async def bsetting_command(self, client: Client, message: Message):
        """Handle /bsetting command"""
        await self.show_settings_menu(message, page=0, edit=False)

    async def show_settings_menu(self, message: Message, page: int = 0, *, edit: bool = True):
        """Show settings menu with numbered page navigation"""
        settings = await self.settings_service.get_all_settings()

        # Get all setting keys
        all_keys = list(settings.keys())
        total_settings = len(all_keys)
        settings_per_page = 8
        total_pages = max(1, (total_settings + settings_per_page - 1) // settings_per_page)
        page = min(max(0, page), total_pages - 1)

        # Get settings for current page
        start = page * settings_per_page
        end = min(start + settings_per_page, total_settings)
        page_keys = all_keys[start:end]

        # Build setting buttons (2 settings per row)
        buttons = []
        for i in range(0, len(page_keys), 2):
            row = []
            for j in range(2):
                if i + j < len(page_keys):
                    key = page_keys[i + j]
                    # Shorten key for button display
                    display_name = self._get_display_name(key)
                    row.append(ButtonBuilder.action_button(
                        display_name,
                        callback_data=f"bset_view_{key}_{page}"  # Include page number in callback
                    ))
            buttons.append(row)

        # Add page navigation buttons
        if total_pages > 1:
            MAX_PAGE_BUTTONS = 11  # Maximum number of page buttons to show

            if total_pages <= MAX_PAGE_BUTTONS:
                # Show all page numbers
                page_row = []
                for p in range(total_pages):
                    if p == page:
                        # Current page (highlighted)
                        page_row.append(ButtonBuilder.action_button(
                            f"• {p + 1} •",
                            callback_data="bset_noop"
                        ))
                    else:
                        page_row.append(ButtonBuilder.action_button(
                            str(p + 1),
                            callback_data=f"bset_page_{p}"
                        ))

                # Split into multiple rows if needed (5 buttons per row for better display)
                for i in range(0, len(page_row), 5):
                    buttons.append(page_row[i:i + 5])
            else:
                # Too many pages, show a subset with prev/next
                page_buttons = []

                # Previous button
                if page > 0:
                    page_buttons.append(ButtonBuilder.action_button("◀️", callback_data=f"bset_page_{page - 1}"))

                # Calculate which pages to show
                if page < 4:
                    # Near the beginning
                    for p in range(min(7, total_pages)):
                        if p == page:
                            page_buttons.append(ButtonBuilder.action_button(f"• {p + 1} •", callback_data="bset_noop"))
                        else:
                            page_buttons.append(ButtonBuilder.action_button(str(p + 1), callback_data=f"bset_page_{p}"))
                    if total_pages > 7:
                        page_buttons.append(ButtonBuilder.action_button("...", callback_data="bset_noop"))
                        page_buttons.append(
                            ButtonBuilder.action_button(str(total_pages), callback_data=f"bset_page_{total_pages - 1}"))
                elif page >= total_pages - 4:
                    # Near the end
                    page_buttons.append(ButtonBuilder.action_button("1", callback_data="bset_page_0"))
                    page_buttons.append(ButtonBuilder.action_button("...", callback_data="bset_noop"))
                    for p in range(max(0, total_pages - 7), total_pages):
                        if p == page:
                            page_buttons.append(ButtonBuilder.action_button(f"• {p + 1} •", callback_data="bset_noop"))
                        else:
                            page_buttons.append(ButtonBuilder.action_button(str(p + 1), callback_data=f"bset_page_{p}"))
                else:
                    # In the middle
                    page_buttons.append(ButtonBuilder.action_button("1", callback_data="bset_page_0"))
                    page_buttons.append(ButtonBuilder.action_button("...", callback_data="bset_noop"))
                    for p in range(page - 2, page + 3):
                        if p == page:
                            page_buttons.append(ButtonBuilder.action_button(f"• {p + 1} •", callback_data="bset_noop"))
                        else:
                            page_buttons.append(ButtonBuilder.action_button(str(p + 1), callback_data=f"bset_page_{p}"))
                    page_buttons.append(ButtonBuilder.action_button("...", callback_data="bset_noop"))
                    page_buttons.append(
                        ButtonBuilder.action_button(str(total_pages), callback_data=f"bset_page_{total_pages - 1}"))

                # Next button
                if page < total_pages - 1:
                    page_buttons.append(ButtonBuilder.action_button("▶️", callback_data=f"bset_page_{page + 1}"))

                # Add page navigation row
                buttons.append(page_buttons)

        # Close button
        buttons.append([ButtonBuilder.action_button("❌ Close", callback_data="bset_close")])

        text = (
            "⚙️ <b>Bot Settings</b>\n\n"
            "Select a setting to view or modify.\n"
            f"Page {page + 1} of {total_pages} • Total Settings: {total_settings}"
        )

        if edit:
            try:
                await message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
            except MessageNotModified:
                # Repeated navigation should keep the existing menu.
                pass
            except Exception as e:
                logger.error(f"Failed to edit settings menu message: {e}")
                # If edit fails, send a new message
                await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        else:
            # This is a regular message, send a reply
            await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    async def settings_callback(self, client: Client, query: CallbackQuery):
        """Handle settings callbacks"""
        user_id = query.from_user.id

        # Check if user is first admin
        if not self.bot.config.ADMINS or user_id != self.bot.config.ADMINS[0]:
            await query.answer(ErrorMessageFormatter.format_warning("Only the primary admin can access settings!", plain_text=True), show_alert=True)
            return

        data = query.data

        if data == "bset_close":
            await query.answer()
            await query.message.delete()
            # Clear any active edit session
            if self.session_manager:
                await self.session_manager.cancel_edit_session(user_id)
            return

        elif data == "bset_noop":
            await query.answer()

        elif data.startswith("bset_page_"):
            try:
                page = int(data.removeprefix("bset_page_"))
            except ValueError:
                await query.answer("Invalid settings page. Open /bsetting again.", show_alert=True)
                return
            await query.answer(f"Loading page {page + 1}")
            await self.show_settings_menu(query.message, page)

        elif data.startswith("bset_view_"):
            await query.answer()
            # Extract key and page number from callback data
            parts = data.replace("bset_view_", "").rsplit("_", 1)
            if len(parts) == 2 and parts[1].isdigit():
                key = parts[0]
                self.current_page = int(parts[1])  # Store current page
            else:
                key = data.replace("bset_view_", "")
                self.current_page = 0
            await self.show_setting_details(query.message, key)

        elif data.startswith("bset_edit_"):
            await query.answer()
            key = data.replace("bset_edit_", "")
            await self.start_edit_session(query.message, key, user_id)

        elif data.startswith("bset_default_"):
            key = data.replace("bset_default_", "")
            await self.reset_to_default(query, key)

        elif data.startswith("bset_bool_"):
            key, _, raw_value = data.removeprefix("bset_bool_").rpartition("_")
            if raw_value not in {'true', 'false'}:
                await query.answer("Invalid settings value. Open /bsetting again.", show_alert=True)
                return
            setting = (await self.settings_service.get_all_settings()).get(key)
            if not setting or setting['type'] != 'bool':
                await query.answer("This control is not available for this setting.", show_alert=True)
                return
            value = raw_value == "true"
            await self.update_boolean_setting(query, key, value)

        elif data == "bset_back":
            await query.answer()
            # Go back to the correct page
            page = getattr(self, 'current_page', 0)
            await self.show_settings_menu(query.message, page)

    async def show_setting_details(self, message: Message, key: str):
        """Show details for a specific setting"""
        settings = await self.settings_service.get_all_settings()

        if key not in settings:
            await message.edit_text(ErrorMessageFormatter.format_not_found("Setting") + "!")
            return

        setting = settings[key]
        current_value = setting['value']
        default_value = setting['default']
        setting_type = setting['type']
        description = setting['description']

        # Format values for display
        if setting_type == 'list':
            if isinstance(current_value, list):
                current_display = ', '.join(str(v) for v in current_value) if current_value else "Empty"
            else:
                current_display = str(current_value)
            default_display = ', '.join(str(v) for v in default_value) if default_value else "Empty"
        else:
            current_display = str(current_value)
            default_display = str(default_value)

        current_display = html.escape(current_display)
        default_display = html.escape(default_display)
        description = html.escape(str(description))

        protection_status = ""
        editable = key not in self.PROTECTED_SETTINGS and setting.get('editable', True)
        if key in self.PROTECTED_SETTINGS:
            protection_status = "\n🔒 <b>Protected:</b> This setting cannot be changed via bot"
        if setting.get('edit_note'):
            protection_status += f"\n{'ℹ️' if editable else '🔒'} {html.escape(setting['edit_note'])}"

        text = (
            f"⚙️ <b>Setting: {self._get_display_name(key)}</b>\n\n"
            f"📝 <b>Description:</b> {description}\n"
            f"🔧 <b>Type:</b> <code>{setting_type}</code>\n"
            f"📌 <b>Current Value:</b> <code>{current_display}</code>\n"
            f"🔄 <b>Default Value:</b> <code>{default_display}</code>\n"
            f"{protection_status}"
        )

        buttons = []
        if editable:
            if setting_type == 'bool':
                # Boolean settings get True/False buttons
                buttons.append([
                    ButtonBuilder.action_button(
                        "✅ True" if current_value else "☐ True",
                        callback_data=f"bset_bool_{key}_true"
                    ),
                    ButtonBuilder.action_button(
                        "✅ False" if not current_value else "☐ False",
                        callback_data=f"bset_bool_{key}_false"
                    )
                ])
            else:
                # Other types get Edit button
                buttons.append([
                    ButtonBuilder.action_button("✏️ Edit Value", callback_data=f"bset_edit_{key}")
                ])

            # Use Default button if current != default
            if current_display != default_display:
                buttons.append([
                    ButtonBuilder.action_button("🔄 Use Default Value", callback_data=f"bset_default_{key}")
                ])

        # Always add Back and Close buttons (for both protected and non-protected)
        buttons.append([
            ButtonBuilder.action_button("⬅️ Back", callback_data="bset_back"),
            ButtonBuilder.action_button("❌ Close", callback_data="bset_close")
        ])

        try:
            await message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        except MessageNotModified:
            # A retried callback may save the value already displayed.
            pass

    async def start_edit_session(self, message: Message, key: str, user_id: int):
        """Start an edit session for a setting using unified session manager"""
        if key in self.PROTECTED_SETTINGS:
            await message.reply_text("This setting is protected and cannot be changed via bot.")
            return
        setting = (await self.settings_service.get_all_settings()).get(key)
        if not setting:
            await message.reply_text("This setting is no longer available. Open /bsetting again.")
            return
        if not setting.get('editable', True):
            await message.reply_text(setting.get('edit_note', 'This setting is locked.'))
            return
        if not self.session_manager:
            await message.reply(ErrorMessageFormatter.format_error("Session management not available"))
            return

        session_data = {
            'key': key,
            'message_id': message.id,
            'chat_id': message.chat.id
        }
        
        # Create session using unified session manager
        await self.session_manager.create_edit_session(user_id, session_data)

        setting_type = setting['type']
        current_value = setting['value']
        current_display = html.escape(str(current_value))

        # Session is now managed by unified session manager

        # Special handling for message templates
        if key == 'AUTO_DELETE_MESSAGE':
            text = (
                f"✏️ <b>Editing: Auto Delete Message</b>\n\n"
                f"Current: <code>{current_display}</code>\n\n"
                f"<b>Available placeholders:</b>\n"
                f"• `{{content_type}}` - Type of content (file, message, etc.)\n"
                f"• `{{minutes}}` - Minutes until deletion\n\n"
                f"<b>HTML formatting supported:</b>\n"
                f"• <code>&lt;b&gt;bold&lt;/b&gt;</code> - <b>bold text</b>\n"
                f"• `<i>italic</i>` - _italic text_\n"
                f"• `<code>code</code>` - `monospace`\n"
                f"• `<u>underline</u>` - underlined\n"
                f"• `<s>strike</s>` - ~~strikethrough~~\n"
                f"• `<a href=\"url\">link</a>` - hyperlink\n\n"
                f"<b>Example:</b>\n"
                f"`⏱ <b>Auto-Delete Notice</b>\n\nThis {{content_type}} will be <u>automatically deleted</u> after <b>{{minutes}} minutes</b>`\n\n"
                f"⏱ You have 60 seconds to respond.\n"
                f"Send /cancel to cancel."
            )
        elif key == 'START_MESSAGE':
            text = (
                f"✏️ <b>Editing: Start Message</b>\n\n"
                f"Current length: {len(current_value)} characters\n\n"
                f"<b>Available placeholders:</b>\n"
                f"• `{{mention}}` - User mention\n"
                f"• `{{user_id}}` - User ID\n"
                f"• `{{first_name}}` - User's first name\n"
                f"• `{{bot_name}}` - Bot's name\n"
                f"• `{{bot_username}}` - Bot's username\n\n"
                f"<b>HTML formatting supported:</b>\n"
                f"• <code>&lt;b&gt;bold&lt;/b&gt;</code> - <b>bold text</b>\n"
                f"• `<i>italic</i>` - _italic text_\n"
                f"• `<code>code</code>` - `monospace`\n"
                f"• `<u>underline</u>` - underlined\n"
                f"• `<s>strike</s>` - ~~strikethrough~~\n"
                f"• `<a href=\"url\">link</a>` - hyperlink\n"
                f"• `\\n` - New line\n\n"
                f"<b>Example:</b>\n"
                f"`<b>👋 Welcome {{mention}}!</b>\\n\\n<i>Your personal file search assistant</i>`\n\n"
                f"⏱ You have 60 seconds to respond.\n"
                f"Send /cancel to cancel."
            )
        elif setting_type == 'list':
            if key == 'FILE_STORE_CHANNEL':
                instruction = "Send the new value (space-separated for multiple values):"
            else:
                instruction = "Send the new value (comma-separated for multiple values):"
            example = "Example: value1, value2, value3" if key != 'FILE_STORE_CHANNEL' else "Example: -100123 -100456"

            text = (
                f"✏️ <b>Editing: {self._get_display_name(key)}</b>\n\n"
                f"Current: <code>{current_display}</code>\n\n"
                f"{instruction}\n{example}\n\n"
                f"⏱ You have 60 seconds to respond.\n"
                f"Send /cancel to cancel."
            )
        elif setting_type == 'int':
            instruction = "Send the new integer value:"
            example = "Example: 100"

            text = (
                f"✏️ <b>Editing: {self._get_display_name(key)}</b>\n\n"
                f"Current: <code>{current_display}</code>\n\n"
                f"{instruction}\n{example}\n\n"
                f"⏱ You have 60 seconds to respond.\n"
                f"Send /cancel to cancel."
            )
        else:  # str
            instruction = "Send the new text value:"
            example = "Example: your text here"

            text = (
                f"✏️ <b>Editing: {self._get_display_name(key)}</b>\n\n"
                f"Current: <code>{current_display}</code>\n\n"
                f"{instruction}\n{example}\n\n"
                f"⏱ You have 60 seconds to respond.\n"
                f"Send /cancel to cancel."
            )

        await message.edit_text(text)

        # Timeout is now handled automatically by unified session manager

    async def handle_cancel(self, client: Client, message: Message):
        """Handle standalone /cancel command using unified session manager"""
        user_id = message.from_user.id
        
        if not self.session_manager:
            await message.reply_text(ErrorMessageFormatter.format_error("Session management not available"))
            return
        
        # Check if user has any active edit session
        session = await self.session_manager.get_edit_session(user_id)
        
        if not session:
            await message.reply_text(ErrorMessageFormatter.format_not_found("Active edit session") + " to cancel")
            return
            
        # Try to delete the editing message
        try:
            if 'message_id' in session.data:
                editing_msg_id = session.data['message_id']
                await telegram_api.call_api(
                    client.delete_messages,
                    message.chat.id,
                    editing_msg_id,
                    chat_id=message.chat.id
                )
        except Exception as e:
            logger.warning(f"Could not delete editing message: {e}")
            
        # Cancel the session
        await self._cancel_captured_edit(user_id, session)
            
        # Delete the cancel message itself
        try:
            await message.delete()
        except Exception as e:
            logger.warning(f"Could not delete cancel message: {e}")
            pass

        logger.info(f"Cancelled edit session for user {user_id}")
        raise StopPropagation  # Prevent any other handlers from processing /cancel

    async def _auto_delete_message(self, message, delay_seconds):
        """Auto-delete a message after specified delay"""
        if delay_seconds <= 0:
            return
        try:
            await asyncio.sleep(delay_seconds)
            await message.delete()
        except Exception as e:
            logger.warning(f"Could not auto-delete message: {e}")

    # In handle_edit_input method, after the success check (around line 234-243):

    async def handle_edit_input(self, client: Client, message: Message):
        """Handle user input during edit session using unified session manager"""
        user_id = message.from_user.id
        
        if not self.session_manager:
            return
        
        # Check if user has active edit session
        session = await self.session_manager.get_edit_session(user_id)
        if not session:
            logger.debug(f"No active session found for user {user_id} - not processing message: {message.text}")
            return

        # This handler should ONLY process messages when user is actively in edit session
        logger.info(f"[EDIT_SESSION] Processing input for user {user_id}: {message.text}")
        
        try:
            return await self._process_edit_session_input(client, message, session)
        except asyncio.CancelledError:
            # Finish cancellation before shutdown closes the operational Redis
            # connection. Fence cleanup to the session this input captured.
            cleanup = asyncio.create_task(self._cancel_captured_edit(user_id, session))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
            raise

    async def _process_edit_session_input(self, client, message, session):
        user_id = message.from_user.id
        # Set a temporary flag to prevent search processing of this message
        await self.bot.cache.set(
            CacheKeyGenerator.recent_settings_edit(user_id),
            True,
            expire=CacheTTLConfig.OPERATION_LOCK
        )

        # Handle cancel
        if message.text.lower() == '/cancel':
            # Delete the editing message first
            try:
                if 'message_id' in session.data:
                    editing_msg_id = session.data['message_id']
                    await telegram_api.call_api(
                        client.delete_messages,
                        message.chat.id,
                        editing_msg_id,
                        chat_id=message.chat.id
                    )
            except Exception as e:
                logger.warning(f"Could not delete editing message: {e}")
                
            # Delete the cancel message itself
            try:
                await message.delete()
            except Exception as e:
                logger.warning(f"Could not delete cancel message: {e}")
                pass

            # Clean up session
            await self._cancel_captured_edit(user_id, session)
            raise StopPropagation  # Prevent any other handlers from processing this message

        # Update the setting
        key = session.data['key']
        new_value = message.text

        try:
            if key in self.PROTECTED_SETTINGS:
                await message.reply_text(
                    ErrorMessageFormatter.format_warning(
                        f"The setting `{key}` is protected and cannot be changed via bot.\n"
                        f"Changing this setting requires:\n"
                        f"1. Manual update in environment variables\n"
                        f"2. Complete bot restart\n\n"
                        f"This protection prevents accidental bot lockouts.",
                        title="Security Warning"
                    )
                )
                await self._cancel_captured_edit(user_id, session)
                raise StopPropagation  # Prevent other handlers from processing this message
            success = await self.settings_service.update_setting(key, new_value)

            if success:
                await self.invalidate_related_caches(key)
                await self.bot.cache.set(
                    CacheKeyGenerator.recent_settings_edit(user_id),
                    True,
                    expire=CacheTTLConfig.OPERATION_LOCK
                )
                # Delete the message containing the value for security
                try:
                    await message.delete()
                except Exception as error:
                    logger.warning("Could not delete saved settings input: %s", error)
                
                # Also delete the editing message
                try:
                    if 'message_id' in session.data:
                        editing_msg_id = session.data['message_id']
                        await telegram_api.call_api(
                            client.delete_messages,
                            message.chat.id,
                            editing_msg_id,
                            chat_id=message.chat.id
                        )
                except Exception as e:
                    logger.warning(f"Could not delete editing message: {e}")

                # Send success message with restart reminder
                success_msg = await telegram_api.call_api(
                    client.send_message,
                    message.chat.id,
                    ErrorMessageFormatter.format_success(f"Setting <b>{self._get_display_name(key)}</b> updated successfully!") + "\n\n"
                    + ErrorMessageFormatter.format_warning("You must restart the bot for changes to take effect.", title="Important") + "\n\n"
                    + "Use `/restart` command now to apply changes.",
                    chat_id=message.chat.id
                )

                # Clean up session immediately to prevent search triggers
                await self._cancel_captured_edit(user_id, session)
                
                # Schedule auto-delete of success message
                self._schedule_auto_delete(success_msg, 10)
                
                # Prevent any other handlers from processing this message
                raise StopPropagation
            else:
                # Clean up session on failure too
                await self._cancel_captured_edit(user_id, session)
                await message.reply_text(ErrorMessageFormatter.format_failed("to update setting"))
                raise StopPropagation  # Prevent search trigger even on failure
        except StopPropagation:
            # Re-raise StopPropagation without treating it as an error
            raise
        except Exception as e:
            # Clean up session on error
            if self.session_manager:
                await self._cancel_captured_edit(user_id, session)
            
            # Better error message handling
            error_msg = str(e).strip() if str(e).strip() else "Unknown error occurred"
            logger.error(f"Error in bot settings edit for user {user_id}: {error_msg}", exc_info=True)
            
            await message.reply_text(ErrorMessageFormatter.format_error(f"Error updating setting: {error_msg}"))
            raise StopPropagation  # Prevent search trigger on error


    async def update_boolean_setting(self, query: CallbackQuery, key: str, value: bool):

        """Update a boolean setting"""
        if key in self.PROTECTED_SETTINGS:
            await query.answer("This setting is protected and cannot be changed via bot.", show_alert=True)
            return
        try:
            success = await self.settings_service.update_setting(key, value)

            if success:
                await self.invalidate_related_caches(key)
                if key == 'DISABLE_FILTER' and hasattr(self.bot, 'filter_handler'):
                    # Re-register or unregister filter handlers
                    if value:  # If disabling filters
                        logger.info("Disabling filter handlers")
                    else:
                        logger.info("Enabling filter handlers")
                await self.show_setting_details(query.message, key)
                notice = "Setting updated! Restart bot for changes to take effect."
                if key == 'DATABASE_GLOBAL_OWNER_REGISTRY' and value:
                    notice = "Setting saved. Ownership activation must be complete before restarting the bot."
                await query.answer(
                    ErrorMessageFormatter.format_success(
                        notice,
                        plain_text=True
                    ),
                    show_alert=True
                )
            else:
                await query.answer(ErrorMessageFormatter.format_failed("to update setting", plain_text=True), show_alert=True)
        except Exception as e:
            await query.answer(ErrorMessageFormatter.format_error(str(e), plain_text=True), show_alert=True)

    async def reset_to_default(self, query: CallbackQuery, key: str):
        """Reset a setting to default value"""
        if key in self.PROTECTED_SETTINGS:
            await query.answer("This setting is protected and cannot be changed via bot.", show_alert=True)
            return
        try:
            success = await self.settings_service.reset_to_default(key)

            if success:
                await self.show_setting_details(query.message, key)
                await query.answer(
                    ErrorMessageFormatter.format_success("Reset to default! Restart bot for changes to take effect.", plain_text=True),
                    show_alert=True
                )
            else:
                await query.answer(ErrorMessageFormatter.format_failed("to reset setting", plain_text=True), show_alert=True)
        except Exception as e:
            await query.answer(ErrorMessageFormatter.format_error(str(e), plain_text=True), show_alert=True)

    def _get_git_info(self):
        """Get the Git checkout or last successfully applied update revision."""
        from core.utils.runtime_version import get_runtime_version
        return get_runtime_version()

    async def restart_command(self, client: Client, message: Message):
        """Update from the configured upstream, then restart the bot process."""
        import json
        import os
        import sys
        import subprocess
        import platform
        import signal
        from update import SecureUpdater

        if getattr(self, '_restart_in_progress', False):
            await message.reply_text("🔄 An update and restart is already in progress.")
            return
        self._restart_in_progress = True
        restart_msg = None
        try:
            restart_msg = await message.reply_text("🔄 <b>Fetching and validating bot updates...</b>")
            upstream_repo = await self.settings_service.get_setting('UPSTREAM_REPO')
            upstream_branch = await self.settings_service.get_setting('UPSTREAM_BRANCH')
            if not upstream_repo or not upstream_branch:
                raise ValueError('UPSTREAM_REPO and UPSTREAM_BRANCH must be configured')

            git_info_before = self._get_git_info()
            updater = SecureUpdater(upstream_repo, upstream_branch)
            # Clone into a temporary checkout: source-only Docker images do not
            # have .git. Back up and validate before changing the running source.
            updated = await asyncio.to_thread(updater.update, install_dependencies=True)
            if not updated:
                raise RuntimeError('Upstream update failed; see the update log and backups')

            restart_data = {
                'chat_id': restart_msg.chat.id,
                'message_id': restart_msg.id,
                'git_before': git_info_before,
            }
            Path('restart_msg.txt').write_text(json.dumps(restart_data), encoding='utf-8')
        except Exception as e:
            self._restart_in_progress = False
            logger.error(f"Error occurred while preparing restart: {e}")
            if restart_msg is not None:
                await restart_msg.edit_text(
                    "❌ <b>Update failed; restart cancelled.</b> Check the update log and backups. "
                    "Confirm UPSTREAM_REPO and UPSTREAM_BRANCH in /bsetting.")
            return

        # A deleted Telegram status message must not strand already updated code.
        try:
            await restart_msg.edit_text("✅ <b>Bot code updated. Restarting...</b>")
        except Exception:
            logger.warning('Cannot edit update status; continuing restart', exc_info=True)

        in_container = (
            Path('/.dockerenv').exists()
            or os.environ.get('IN_DOCKER', '').lower() in ('1', 'true', 'yes')
            or bool(os.environ.get('KUBERNETES_SERVICE_HOST'))
        )
        if in_container:
            # idle() handles SIGTERM, Client.run() awaits stop(), and Compose's
            # unless-stopped policy restarts this container with the updated files.
            os.kill(os.getpid(), signal.SIGTERM)
            return

        # Platform-specific restart
        if platform.system() == "Windows":
            # Windows-specific restart
            try:
                # Create a batch file for restart
                with open("restart.bat", "w") as f:
                    f.write(f'''@echo off
    timeout /t 2 /nobreak > nul
    {sys.executable} {' '.join(sys.argv)}
    del "%~f0"
    ''')

                # Start the batch file
                subprocess.Popen(["cmd", "/c", "restart.bat"],
                                 creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS)

                # Exit the current process
                await client.stop()
                sys.exit(0)
            except Exception as e:
                logger.error(f"Windows restart failed: {e}")
                await restart_msg.edit_text(ErrorMessageFormatter.format_failed(str(e), action="Restart"))
        else:
            # Unix-like systems (Linux, macOS)
            os.execl(sys.executable, sys.executable, *sys.argv)

    def _get_display_name(self, key: str) -> str:
        """Get shortened display name for settings"""
        # Map long names to shorter versions
        display_map = {
            'USE_CAPTION_FILTER': 'Caption Filter',
            'FEATURE_SAVED_SEARCH_ALERTS': 'Saved Alerts',
            'FEATURE_FAVORITES': 'Favorites',
            'FEATURE_ADVANCED_SEARCH': 'Advanced Search',
            'FEATURE_INDEXED_MEDIA_SEARCH': 'Indexed Search',
            'FEATURE_RECOMMENDATION_FEEDBACK': 'Rec Feedback',
            'FEATURE_FILE_REPORTS': 'File Reports',
            'FEATURE_SEARCH_AUTOCOMPLETE': 'Autocomplete',
            'FEATURE_DUPLICATE_GROUPING': 'Group Variants',
            'FEATURE_REQUEST_TRACKING': 'Request Tracking',
            'FEATURE_RECENT_FILES': 'Recent Files',
            'FEATURE_RECOMMENDATION_EXPLANATIONS': 'Rec Reasons',
            'FEATURE_CONTENT_DASHBOARD': 'Content Dashboard',
            'FEATURE_CANONICAL_MEDIA_METADATA': 'Canonical Metadata',
            'FEATURE_QUOTA_DELIVERY_LEDGER': 'Quota Ledger',
            'PROCESSING_DURABLE_INDEXING': 'Durable Indexing',
            'PROCESSING_DURABLE_SAVED_SEARCH_ALERTS': 'Durable Alerts',
            'DATABASE_GLOBAL_OWNER_REGISTRY': 'Media Owners',
            'DISABLE_PREMIUM': 'Disable Premium',
            'DISABLE_FILTER': 'Disable Filter',
            'PUBLIC_FILE_STORE': 'Public Store',
            'KEEP_ORIGINAL_CAPTION': 'Keep Caption',
            'MESSAGE_DELETE_SECONDS': 'Auto Delete',
            'NON_PREMIUM_DAILY_LIMIT': 'Daily Limit',
            'PREMIUM_DURATION_DAYS': 'Premium Days',
            'FILE_STORE_CHANNEL': 'File Channels',
            'CUSTOM_FILE_CAPTION': 'File Caption',
            'BATCH_FILE_CAPTION': 'Batch Caption',
            'SUPPORT_GROUP_USERNAME': 'Support User',
            'INDEX_REQ_CHANNEL': 'Index Channel',
            'DELETE_CHANNEL': 'Delete Channel',
            'AUTH_CHANNEL': 'Auth Channel',
            'AUTH_GROUPS': 'Auth Groups',
            'MAX_BTN_SIZE': 'Max Buttons',
            'UPSTREAM_REPO': 'Upstream Repo',
            'UPSTREAM_BRANCH': 'Upstream Branch',
            'SUPPORT_CHAT_ID': 'Support Chat',
            'DATABASE_NAME': 'DB Name',
            'DATABASE_URI': 'DB URI',
            'LOG_CHANNEL': 'Log Channel',
            'MAIN_CHANNEL': 'Main Channel',
            'SUPPORT_GROUP': 'Support Group',
            'PICS': 'Random Pics',
            'REQ_CHANNEL': 'Request Channel',
            'SUPPORT_GROUP_URL': 'Support URL',
            'SUPPORT_GROUP_NAME': 'Support Name',
            'SUPPORT_GROUP_ID': 'Support ID',
            'PAYMENT_LINK': 'Payment Link',
            'USE_ORIGINAL_CAPTION_FOR_BATCH': 'Batch Original Caption',
            'REQUEST_PER_DAY': "Requests per day",
            'REQUEST_WARNING_LIMIT': "Request warning limit",
            'AUTO_DELETE_MESSAGE': 'Auto Delete Msg',
            'START_MESSAGE': 'Start Message',
            'PREMIUM_PRICE': 'Premium Price',
            'DATABASE_SIZE_LIMIT_GB': 'DB Size Limit (GB)',
            'DATABASE_AUTO_SWITCH': 'DB Auto Switch',
            'DATABASE_MAX_FAILURES': 'Circuit Max Failures',
            'DATABASE_RECOVERY_TIMEOUT': 'Circuit Recovery Time',
            'DATABASE_HALF_OPEN_CALLS': 'Circuit Half-Open Calls',
            'PORT':'Port',
            'CACHE_TIME':'Cache Time',
            'ADMINS': 'Admin Users',
            'CHANNELS': 'Indexing Channels',
            'AUTH_USERS': 'Authorized Users',
            'REDIS_URI': 'Redis URI',
            'REQUEST_ONLY_FOR_PREMIUM': 'Request Only for Premium'
        }

        return display_map.get(key, key)
