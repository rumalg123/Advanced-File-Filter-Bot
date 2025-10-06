import asyncio

from pyrogram import Client
from pyrogram import StopPropagation
from pyrogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from core.cache.config import CacheTTLConfig, CacheKeyGenerator
from core.utils.logger import get_logger

logger = get_logger(__name__)


class BotSettingsHandler:
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
        self.bot = bot
        self.settings_service = bot.bot_settings_service
        self.current_page = 0
        self.ttl = CacheTTLConfig()
        self._shutdown = asyncio.Event()
        self._handlers = []  # Track handlers
        
        # Use unified session manager
        self.session_manager = getattr(bot, 'session_manager', None)
        
        # Register handlers
        self._register_handlers()

    def _register_handlers(self):
        """Register all handlers with tracking"""
        # This method should be called instead of directly registering in __init__
        # The handlers should be registered through the main command handler
        pass

    async def cleanup(self):
        """Clean up handler resources"""
        logger.info("Cleaning up BotSettingsHandler...")

        # Signal shutdown
        self._shutdown.set()

        # Session cleanup handled by unified session manager

        # If handler_manager is available, let it handle everything
        if hasattr(self.bot, 'handler_manager') and self.bot.handler_manager:
            logger.info("HandlerManager will handle task and handler cleanup")
            # Mark our handlers as removed in the manager
            for handler in self._handlers:
                handler_id = id(handler)
                self.bot.handler_manager.removed_handlers.add(handler_id)
            self._handlers.clear()
            logger.info("BotSettingsHandler cleanup complete")
            return

        # Manual cleanup only if no handler_manager
        if hasattr(self, 'cleanup_task') and self.cleanup_task and not self.cleanup_task.done():
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass

        # Remove handlers
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
        logger.info("BotSettingsHandler cleanup complete")

    async def invalidate_related_caches(self, key: str):
        """Invalidate caches related to a specific setting"""
        # Map settings to their related cache patterns
        cache_invalidation_map = {
            'ADMINS': ['user:*', 'banned_users'],
            'AUTH_CHANNEL': ['subscription:*'],
            'AUTH_GROUPS': ['subscription:*'],
            'CHANNELS': ['active_channels_list', 'channel:*'],
            'MAX_BTN_SIZE': ['search:*'],
            'USE_CAPTION_FILTER': ['search:*'],
            'NON_PREMIUM_DAILY_LIMIT': ['user:*'],
            'PREMIUM_DURATION_DAYS': ['user:*'],
            'MESSAGE_DELETE_SECONDS': ['search:*'],
            'DISABLE_FILTER': ['filter:*', 'filters_list:*'],
            'DISABLE_PREMIUM': ['user:*'],
            'FILE_STORE_CHANNEL': ['filestore:*'],
        }

        patterns = cache_invalidation_map.get(key, [])
        for pattern in patterns:
            await self.bot.cache.delete_pattern(pattern)

        # Clear general settings cache
        await self.bot.cache.delete(CacheKeyGenerator.all_settings())

        logger.info(f"Invalidated caches for setting: {key}")

    async def bsetting_command(self, client: Client, message: Message):
        """Handle /bsetting command"""
        await self.show_settings_menu(message, page=0)

    async def show_settings_menu(self, message: Message, page: int = 0):
        """Show settings menu with numbered page navigation"""
        settings = await self.settings_service.get_all_settings()

        # Get all setting keys
        all_keys = list(settings.keys())
        total_settings = len(all_keys)
        settings_per_page = 8
        total_pages = (total_settings + settings_per_page - 1) // settings_per_page

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
                    row.append(InlineKeyboardButton(
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
                        page_row.append(InlineKeyboardButton(
                            f"• {p + 1} •",
                            callback_data="bset_noop"
                        ))
                    else:
                        page_row.append(InlineKeyboardButton(
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
                    page_buttons.append(InlineKeyboardButton("◀️", callback_data=f"bset_page_{page - 1}"))

                # Calculate which pages to show
                if page < 4:
                    # Near the beginning
                    for p in range(min(7, total_pages)):
                        if p == page:
                            page_buttons.append(InlineKeyboardButton(f"• {p + 1} •", callback_data="bset_noop"))
                        else:
                            page_buttons.append(InlineKeyboardButton(str(p + 1), callback_data=f"bset_page_{p}"))
                    if total_pages > 7:
                        page_buttons.append(InlineKeyboardButton("...", callback_data="bset_noop"))
                        page_buttons.append(
                            InlineKeyboardButton(str(total_pages), callback_data=f"bset_page_{total_pages - 1}"))
                elif page >= total_pages - 4:
                    # Near the end
                    page_buttons.append(InlineKeyboardButton("1", callback_data="bset_page_0"))
                    page_buttons.append(InlineKeyboardButton("...", callback_data="bset_noop"))
                    for p in range(max(0, total_pages - 7), total_pages):
                        if p == page:
                            page_buttons.append(InlineKeyboardButton(f"• {p + 1} •", callback_data="bset_noop"))
                        else:
                            page_buttons.append(InlineKeyboardButton(str(p + 1), callback_data=f"bset_page_{p}"))
                else:
                    # In the middle
                    page_buttons.append(InlineKeyboardButton("1", callback_data="bset_page_0"))
                    page_buttons.append(InlineKeyboardButton("...", callback_data="bset_noop"))
                    for p in range(page - 2, page + 3):
                        if p == page:
                            page_buttons.append(InlineKeyboardButton(f"• {p + 1} •", callback_data="bset_noop"))
                        else:
                            page_buttons.append(InlineKeyboardButton(str(p + 1), callback_data=f"bset_page_{p}"))
                    page_buttons.append(InlineKeyboardButton("...", callback_data="bset_noop"))
                    page_buttons.append(
                        InlineKeyboardButton(str(total_pages), callback_data=f"bset_page_{total_pages - 1}"))

                # Next button
                if page < total_pages - 1:
                    page_buttons.append(InlineKeyboardButton("▶️", callback_data=f"bset_page_{page + 1}"))

                # Add page navigation row
                buttons.append(page_buttons)

        # Close button
        buttons.append([InlineKeyboardButton("❌ Close", callback_data="bset_close")])

        text = (
            "⚙️ <b>Bot Settings</b>\n\n"
            "Select a setting to view or modify.\n"
            f"Page {page + 1} of {total_pages} • Total Settings: {total_settings}"
        )

        if hasattr(message, 'edit_text') and hasattr(message, 'id') and message.chat:
            try:
                await message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
            except Exception:
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
            await query.answer("⚠️ Only the primary admin can access settings!", show_alert=True)
            return

        data = query.data

        if data == "bset_close":
            await query.message.delete()
            # Clear any active edit session
            if self.session_manager:
                await self.session_manager.cancel_edit_session(user_id)
            return

        elif data == "bset_noop":
            await query.answer()

        elif data.startswith("bset_page_"):
            page = int(data.split("_")[2])
            await self.show_settings_menu(query.message, page)
            await query.answer(f"Page {page + 1}")

        elif data.startswith("bset_view_"):
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
            key = data.replace("bset_edit_", "")
            await self.start_edit_session(query.message, key, user_id)

        elif data.startswith("bset_default_"):
            key = data.replace("bset_default_", "")
            await self.reset_to_default(query, key)

        elif data.startswith("bset_bool_"):
            parts = data.split("_")
            key = "_".join(parts[2:-1])  # Handle keys with underscores
            value = parts[-1] == "true"
            await self.update_boolean_setting(query, key, value)

        elif data == "bset_back":
            # Go back to the correct page
            page = getattr(self, 'current_page', 0)
            await self.show_settings_menu(query.message, page)

    async def show_setting_details(self, message: Message, key: str):
        """Show details for a specific setting"""
        settings = await self.settings_service.get_all_settings()

        if key not in settings:
            await message.edit_text("❌ Setting not found!")
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

        protection_status = ""
        if key in self.PROTECTED_SETTINGS:
            protection_status = "\n🔒 <b>Protected:</b> This setting cannot be changed via bot"

        text = (
            f"⚙️ <b>Setting: {self._get_display_name(key)}</b>\n\n"
            f"📝 <b>Description:</b> {description}\n"
            f"🔧 <b>Type:</b> <code>{setting_type}</code>\n"
            f"📌 <b>Current Value:</b> <code>{current_display}</code>\n"
            f"🔄 <b>Default Value:</b> <code>{default_display}</code>\n"
            f"{protection_status}"
        )

        buttons = []
        if key not in self.PROTECTED_SETTINGS:
            if setting_type == 'bool':
                # Boolean settings get True/False buttons
                buttons.append([
                    InlineKeyboardButton(
                        "✅ True" if current_value else "☐ True",
                        callback_data=f"bset_bool_{key}_true"
                    ),
                    InlineKeyboardButton(
                        "✅ False" if not current_value else "☐ False",
                        callback_data=f"bset_bool_{key}_false"
                    )
                ])
            else:
                # Other types get Edit button
                buttons.append([
                    InlineKeyboardButton("✏️ Edit Value", callback_data=f"bset_edit_{key}")
                ])

            # Use Default button if current != default
            if current_display != default_display:
                buttons.append([
                    InlineKeyboardButton("🔄 Use Default Value", callback_data=f"bset_default_{key}")
                ])

        # Always add Back and Close buttons (for both protected and non-protected)
        buttons.append([
            InlineKeyboardButton("⬅️ Back", callback_data="bset_back"),
            InlineKeyboardButton("❌ Close", callback_data="bset_close")
        ])

        await message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    async def start_edit_session(self, message: Message, key: str, user_id: int):
        """Start an edit session for a setting using unified session manager"""
        if not self.session_manager:
            await message.reply("❌ Session management not available")
            return

        session_data = {
            'key': key,
            'message_id': message.id,
            'chat_id': message.chat.id
        }
        
        # Create session using unified session manager
        await self.session_manager.create_edit_session(user_id, session_data)

        settings = await self.settings_service.get_all_settings()
        setting = settings.get(key)

        if not setting:
            return

        setting_type = setting['type']
        current_value = setting['value']

        # Session is now managed by unified session manager

        # Special handling for message templates
        if key == 'AUTO_DELETE_MESSAGE':
            text = (
                f"✏️ <b>Editing: Auto Delete Message</b>\n\n"
                f"Current: `{current_value}`\n\n"
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
                f"Current: `{current_value}`\n\n"
                f"{instruction}\n{example}\n\n"
                f"⏱ You have 60 seconds to respond.\n"
                f"Send /cancel to cancel."
            )
        elif setting_type == 'int':
            instruction = "Send the new integer value:"
            example = "Example: 100"

            text = (
                f"✏️ <b>Editing: {self._get_display_name(key)}</b>\n\n"
                f"Current: `{current_value}`\n\n"
                f"{instruction}\n{example}\n\n"
                f"⏱ You have 60 seconds to respond.\n"
                f"Send /cancel to cancel."
            )
        else:  # str
            instruction = "Send the new text value:"
            example = "Example: your text here"

            text = (
                f"✏️ <b>Editing: {self._get_display_name(key)}</b>\n\n"
                f"Current: `{current_value}`\n\n"
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
            await message.reply_text("❌ Session management not available.")
            return
        
        # Check if user has any active edit session
        session = await self.session_manager.get_edit_session(user_id)
        
        if not session:
            await message.reply_text("❌ No active edit session to cancel.")
            return
            
        # Try to delete the editing message
        try:
            if 'message_id' in session.data:
                editing_msg_id = session.data['message_id']
                await client.delete_messages(message.chat.id, editing_msg_id)
        except Exception as e:
            logger.warning(f"Could not delete editing message: {e}")
            
        # Cancel the session
        await self.session_manager.cancel_edit_session(user_id)
            
        # Delete the cancel message itself
        try:
            await message.delete()
        except:
            pass
            
        logger.info(f"Cancelled edit session for user {user_id}")
        raise StopPropagation  # Prevent any other handlers from processing /cancel

    async def _auto_delete_message(self, message, delay_seconds):
        """Auto-delete a message after specified delay"""
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
                    await client.delete_messages(message.chat.id, editing_msg_id)
            except Exception as e:
                logger.warning(f"Could not delete editing message: {e}")
                
            # Delete the cancel message itself
            try:
                await message.delete()
            except:
                pass
                
            # Clean up session
            await self.session_manager.cancel_edit_session(user_id)
            raise StopPropagation  # Prevent any other handlers from processing this message

        # Update the setting
        key = session.data['key']
        new_value = message.text

        try:
            if key in self.PROTECTED_SETTINGS:
                await message.reply_text(
                    f"⚠️ <b>Security Warning</b>\n\n"
                    f"The setting `{key}` is protected and cannot be changed via bot.\n"
                    f"Changing this setting requires:\n"
                    f"1. Manual update in environment variables\n"
                    f"2. Complete bot restart\n\n"
                    f"This protection prevents accidental bot lockouts."
                )
                await self.session_manager.cancel_edit_session(user_id)
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
                await message.delete()
                
                # Also delete the editing message
                try:
                    if 'message_id' in session.data:
                        editing_msg_id = session.data['message_id']
                        await client.delete_messages(message.chat.id, editing_msg_id)
                except Exception as e:
                    logger.warning(f"Could not delete editing message: {e}")

                # Send success message with restart reminder
                success_msg = await client.send_message(
                    message.chat.id,
                    f"✅ Setting <b>{self._get_display_name(key)}</b> updated successfully!\n\n"
                    f"⚠️ <b>Important:</b> You must restart the bot for changes to take effect.\n\n"
                    f"Use `/restart` command now to apply changes."
                )

                # Clean up session immediately to prevent search triggers
                await self.session_manager.cancel_edit_session(user_id)
                
                # Schedule auto-delete of success message
                asyncio.create_task(self._auto_delete_message(success_msg, 10))
                
                # Prevent any other handlers from processing this message
                raise StopPropagation
            else:
                # Clean up session on failure too
                await self.session_manager.cancel_edit_session(user_id)
                await message.reply_text("❌ Failed to update setting.")
                raise StopPropagation  # Prevent search trigger even on failure
        except StopPropagation:
            # Re-raise StopPropagation without treating it as an error
            raise
        except Exception as e:
            # Clean up session on error
            if self.session_manager:
                await self.session_manager.cancel_edit_session(user_id)
            
            # Better error message handling
            error_msg = str(e).strip() if str(e).strip() else "Unknown error occurred"
            logger.error(f"Error in bot settings edit for user {user_id}: {error_msg}", exc_info=True)
            
            await message.reply_text(f"❌ Error updating setting: {error_msg}")
            raise StopPropagation  # Prevent search trigger on error


    async def update_boolean_setting(self, query: CallbackQuery, key: str, value: bool):

        """Update a boolean setting"""
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
                await query.answer(
                    f"✅ Setting updated! Restart bot for changes to take effect.",
                    show_alert=True
                )
            else:
                await query.answer("❌ Failed to update setting", show_alert=True)
        except Exception as e:
            await query.answer(f"❌ Error: {str(e)}", show_alert=True)

    async def reset_to_default(self, query: CallbackQuery, key: str):
        """Reset a setting to default value"""
        try:
            success = await self.settings_service.reset_to_default(key)

            if success:
                await self.show_setting_details(query.message, key)
                await query.answer(
                    f"✅ Reset to default! Restart bot for changes to take effect.",
                    show_alert=True
                )
            else:
                await query.answer("❌ Failed to reset setting", show_alert=True)
        except Exception as e:
            await query.answer(f"❌ Error: {str(e)}", show_alert=True)

    def _get_git_info(self):
        """Get current git information"""
        import subprocess
        try:
            # Get current commit hash
            hash_result = subprocess.run(['git', 'rev-parse', 'HEAD'], 
                                       capture_output=True, text=True, check=True)
            commit_hash = hash_result.stdout.strip()[:7]  # Short hash
            
            # Get commit date and message
            commit_info = subprocess.run(['git', 'log', '-1', '--format=%cd|%s', '--date=format:%Y-%m-%d %H:%M'], 
                                       capture_output=True, text=True, check=True)
            commit_date, commit_message = commit_info.stdout.strip().split('|', 1)
            
            # Check for uncommitted changes
            status_result = subprocess.run(['git', 'status', '--porcelain'], 
                                         capture_output=True, text=True, check=True)
            has_changes = bool(status_result.stdout.strip())
            
            return {
                'hash': commit_hash,
                'date': commit_date,
                'message': commit_message,
                'has_changes': has_changes,
                'full_hash': hash_result.stdout.strip()
            }
        except Exception as e:
            logger.error(f"Failed to get git info: {e}")
            return None

    async def restart_command(self, client: Client, message: Message):
        """Handle /restart command"""
        import os
        import sys
        import subprocess
        import platform
        import shutil

        # Get current git info before restart
        git_info_before = self._get_git_info()
        
        restart_msg = await message.reply_text("🔄 <b>Restarting bot...</b>")

        # Save restart message info and git info
        restart_data = {
            'chat_id': restart_msg.chat.id,
            'message_id': restart_msg.id,
            'git_before': git_info_before
        }
        
        with open("restart_msg.txt", "w") as f:
            import json
            f.write(json.dumps(restart_data))

        # Get upstream settings
        upstream_repo = await self.settings_service.get_setting('UPSTREAM_REPO')
        upstream_branch = await self.settings_service.get_setting('UPSTREAM_BRANCH')

        if upstream_repo and upstream_branch:
            await restart_msg.edit_text("🔄 <b>Force pulling updates from upstream...</b>")

            try:
                # Force pull from upstream (overwrites local changes)
                subprocess.run(["git", "fetch", "--all"], capture_output=True, text=True, check=True)
                subprocess.run(["git", "reset", "--hard", f"origin/{upstream_branch}"], capture_output=True, text=True, check=True)
                
                # Try git clean with error handling for Docker environments
                try:
                    subprocess.run(["git", "clean", "-fd"], capture_output=True, text=True, check=True)
                except subprocess.CalledProcessError as clean_error:
                    logger.warning(f"Git clean failed (likely permission issue in Docker): {clean_error}")
                    # Try alternative cleanup for Docker environments
                    try:
                        # Clean only files that git can access
                        subprocess.run(["git", "clean", "-f"], capture_output=True, text=True, check=False)
                    except Exception:
                        logger.info("Git clean alternative also failed, continuing anyway")
                
                shutil.rmtree("logs", ignore_errors=True)
                
                # Get updated git info
                git_info_after = self._get_git_info()
                
                if git_info_before and git_info_after:
                    if git_info_before['full_hash'] != git_info_after['full_hash']:
                        update_msg = (
                            f"✅ <b>Updates pulled!</b>\n\n"
                            f"📝 <b>Latest Commit:</b>\n"
                            f"🔗 `{git_info_after['hash']}` - {git_info_after['date']}\n"
                            f"💬 {git_info_after['message']}\n\n"
                            f"🔄 <b>Restarting...</b>"
                        )
                    else:
                        update_msg = "ℹ️ <b>No new updates available. Restarting...</b>"
                else:
                    update_msg = "✅ <b>Updates pulled! Restarting...</b>"
                    
                await restart_msg.edit_text(update_msg)
            except Exception as e:
                logger.error(f"Failed to force pull updates: {e}")
                await restart_msg.edit_text("⚠️ <b>Failed to force pull updates. Restarting anyway...</b>")

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
                await restart_msg.edit_text(f"❌ <b>Restart failed:</b> {str(e)}")
        else:
            # Unix-like systems (Linux, macOS)
            os.execl(sys.executable, sys.executable, *sys.argv)

    def _get_display_name(self, key: str) -> str:
        """Get shortened display name for settings"""
        # Map long names to shorter versions
        display_map = {
            'USE_CAPTION_FILTER': 'Caption Filter',
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
        }

        return display_map.get(key, key)