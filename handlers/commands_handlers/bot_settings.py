import asyncio

from pyrogram import Client
from pyrogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram import StopPropagation

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
        self.edit_sessions = {}  # Store active edit sessions
        self.current_page = 0
        self.ttl = CacheTTLConfig()
        self._shutdown = asyncio.Event()
        self._handlers = []  # Track handlers
        self.cleanup_task = None

        # Register handlers
        self._register_handlers()
        if hasattr(bot, 'handler_manager') and bot.handler_manager:
            self.cleanup_task = bot.handler_manager.create_background_task(
                self._cleanup_stale_sessions(),
                name="settings_session_cleanup"
            )
        else:
            self.cleanup_task = asyncio.create_task(self._cleanup_stale_sessions())

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

        # Clear edit sessions (always do this)
        for user_id in list(self.edit_sessions.keys()):
            session_key = CacheKeyGenerator.edit_session(user_id)
            await self.bot.cache.delete(session_key)

        self.edit_sessions.clear()

        # If handler_manager is available, let it handle everything
        if hasattr(self.bot, 'handler_manager') and self.bot.handler_manager:
            logger.info("HandlerManager will handle task and handler cleanup")
            self._handlers.clear()
            logger.info("BotSettingsHandler cleanup complete")
            return

        # Manual cleanup only if no handler_manager
        if self.cleanup_task and not self.cleanup_task.done():
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

    async def _cleanup_stale_sessions(self):
        """Periodically clean up stale edit sessions"""
        while not self._shutdown.is_set():
            try:
                # Wait for 5 minutes or shutdown
                await asyncio.wait_for(self._shutdown.wait(), timeout=300)
                break  # Shutdown requested
            except asyncio.TimeoutError:
                # Do cleanup
                current_time = asyncio.get_event_loop().time()
                stale_sessions = []

                for user_id, session in self.edit_sessions.items():
                    if 'created_at' in session:
                        if current_time - session['created_at'] > 120:  # 2 minutes
                            stale_sessions.append(user_id)

                # Clean up stale sessions
                for user_id in stale_sessions:
                    logger.info(f"Cleaning up stale edit session for user {user_id}")
                    del self.edit_sessions[user_id]
                    session_key = CacheKeyGenerator.edit_session(user_id)
                    await self.bot.cache.delete(session_key)

                if stale_sessions:
                    logger.info(f"Cleaned up {len(stale_sessions)} stale edit sessions")

            except Exception as e:
                logger.error(f"Error in session cleanup task: {e}")

        logger.info("Session cleanup task exited")

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
            "⚙️ **Bot Settings**\n\n"
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
            if user_id in self.edit_sessions:
                del self.edit_sessions[user_id]
                session_key = CacheKeyGenerator.edit_session(user_id)
                await self.bot.cache.delete(session_key)
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
            protection_status = "\n🔒 **Protected:** This setting cannot be changed via bot"

        text = (
            f"⚙️ **Setting: {self._get_display_name(key)}**\n\n"
            f"📝 **Description:** {description}\n"
            f"🔧 **Type:** `{setting_type}`\n"
            f"📌 **Current Value:** `{current_display}`\n"
            f"🔄 **Default Value:** `{default_display}`\n"
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
        """Start an edit session for a setting"""
        if user_id in self.edit_sessions:
            logger.warning(f"Cleaning up existing edit session for user {user_id}")
            del self.edit_sessions[user_id]

        session_key = CacheKeyGenerator.edit_session(user_id)
        session_data = {
            'key': key,
            'message_id': message.id,
            'chat_id': message.chat.id,
            'created_at': asyncio.get_event_loop().time()
        }
        await self.bot.cache.set(
            session_key,
            session_data,
            expire=self.ttl.EDIT_SESSION
        )

        settings = await self.settings_service.get_all_settings()
        setting = settings.get(key)

        if not setting:
            return

        setting_type = setting['type']
        current_value = setting['value']

        # Store edit session
        self.edit_sessions[user_id] = {
            'key': key,
            'message_id': message.id,
            'chat_id': message.chat.id,
            'created_at': asyncio.get_event_loop().time()
        }

        # Special handling for message templates
        if key == 'AUTO_DELETE_MESSAGE':
            text = (
                f"✏️ **Editing: Auto Delete Message**\n\n"
                f"Current: `{current_value}`\n\n"
                f"**Available placeholders:**\n"
                f"• `{{content_type}}` - Type of content (file, message, etc.)\n"
                f"• `{{minutes}}` - Minutes until deletion\n\n"
                f"**HTML formatting supported:**\n"
                f"• `<b>bold</b>` - **bold text**\n"
                f"• `<i>italic</i>` - _italic text_\n"
                f"• `<code>code</code>` - `monospace`\n"
                f"• `<u>underline</u>` - underlined\n"
                f"• `<s>strike</s>` - ~~strikethrough~~\n"
                f"• `<a href=\"url\">link</a>` - hyperlink\n\n"
                f"**Example:**\n"
                f"`⏱ <b>Auto-Delete Notice</b>\\n\\nThis {{content_type}} will be <u>automatically deleted</u> after <b>{{minutes}} minutes</b>`\n\n"
                f"⏱ You have 60 seconds to respond.\n"
                f"Send /cancel to cancel."
            )
        elif key == 'START_MESSAGE':
            text = (
                f"✏️ **Editing: Start Message**\n\n"
                f"Current length: {len(current_value)} characters\n\n"
                f"**Available placeholders:**\n"
                f"• `{{mention}}` - User mention\n"
                f"• `{{user_id}}` - User ID\n"
                f"• `{{first_name}}` - User's first name\n"
                f"• `{{bot_name}}` - Bot's name\n"
                f"• `{{bot_username}}` - Bot's username\n\n"
                f"**HTML formatting supported:**\n"
                f"• `<b>bold</b>` - **bold text**\n"
                f"• `<i>italic</i>` - _italic text_\n"
                f"• `<code>code</code>` - `monospace`\n"
                f"• `<u>underline</u>` - underlined\n"
                f"• `<s>strike</s>` - ~~strikethrough~~\n"
                f"• `<a href=\"url\">link</a>` - hyperlink\n"
                f"• `\\n` - New line\n\n"
                f"**Example:**\n"
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
                f"✏️ **Editing: {self._get_display_name(key)}**\n\n"
                f"Current: `{current_value}`\n\n"
                f"{instruction}\n{example}\n\n"
                f"⏱ You have 60 seconds to respond.\n"
                f"Send /cancel to cancel."
            )
        elif setting_type == 'int':
            instruction = "Send the new integer value:"
            example = "Example: 100"

            text = (
                f"✏️ **Editing: {self._get_display_name(key)}**\n\n"
                f"Current: `{current_value}`\n\n"
                f"{instruction}\n{example}\n\n"
                f"⏱ You have 60 seconds to respond.\n"
                f"Send /cancel to cancel."
            )
        else:  # str
            instruction = "Send the new text value:"
            example = "Example: your text here"

            text = (
                f"✏️ **Editing: {self._get_display_name(key)}**\n\n"
                f"Current: `{current_value}`\n\n"
                f"{instruction}\n{example}\n\n"
                f"⏱ You have 60 seconds to respond.\n"
                f"Send /cancel to cancel."
            )

        await message.edit_text(text)

        # Start timeout task
        asyncio.create_task(self._edit_timeout(user_id, 60))

    async def handle_cancel(self, client: Client, message: Message):
        """Handle standalone /cancel command"""
        user_id = message.from_user.id
        session_key = CacheKeyGenerator.edit_session(user_id)
        
        # Check if user has any active session (cache or memory)
        cache_session = await self.bot.cache.get(session_key)
        has_memory_session = user_id in self.edit_sessions
        
        if not cache_session and not has_memory_session:
            await message.reply_text("❌ No active edit session to cancel.")
            return
            
        # Try to delete the editing message
        try:
            if has_memory_session and 'message_id' in self.edit_sessions[user_id]:
                editing_msg_id = self.edit_sessions[user_id]['message_id']
                await client.delete_messages(message.chat.id, editing_msg_id)
            elif cache_session and 'message_id' in cache_session:
                editing_msg_id = cache_session['message_id']
                await client.delete_messages(message.chat.id, editing_msg_id)
        except Exception as e:
            logger.warning(f"Could not delete editing message: {e}")
            
        # Clean up both sessions
        if has_memory_session:
            del self.edit_sessions[user_id]
        if cache_session:
            await self.bot.cache.delete(session_key)
            
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
        """Handle user input during edit session"""
        user_id = message.from_user.id
        session_key = CacheKeyGenerator.edit_session(user_id)
        
        # Double check - user must have both cache session AND in-memory session
        cache_session = await self.bot.cache.get(session_key)
        if not cache_session:
            logger.debug(f"No cache session found for user {user_id} - not processing message: {message.text}")
            return

        # Check if user has active edit session in memory
        if user_id not in self.edit_sessions:
            logger.debug(f"No in-memory session found for user {user_id} - not processing message: {message.text}")
            return

        # This handler should ONLY process messages when user is actively in edit session
        logger.info(f"[EDIT_SESSION] Processing input for user {user_id}: {message.text}")
        
        # Set a temporary flag to prevent search processing of this message
        await self.bot.cache.set(
            CacheKeyGenerator.recent_settings_edit(user_id),
            True,
            expire=10  # 10 seconds to cover full operation
        )

        session = self.edit_sessions[user_id]

        # Handle cancel
        if message.text.lower() == '/cancel':
            # Delete the editing message first
            try:
                editing_msg_id = session['message_id']
                await client.delete_messages(message.chat.id, editing_msg_id)
            except Exception as e:
                logger.warning(f"Could not delete editing message: {e}")
                
            # Delete the cancel message itself
            try:
                await message.delete()
            except:
                pass
                
            # Clean up session
            del self.edit_sessions[user_id]
            await self.bot.cache.delete(session_key)  # Clear cache session
            raise StopPropagation  # Prevent any other handlers from processing this message

        # Update the setting
        key = session['key']
        new_value = message.text

        try:
            if key in self.PROTECTED_SETTINGS:
                await message.reply_text(
                    f"⚠️ **Security Warning**\n\n"
                    f"The setting `{key}` is protected and cannot be changed via bot.\n"
                    f"Changing this setting requires:\n"
                    f"1. Manual update in environment variables\n"
                    f"2. Complete bot restart\n\n"
                    f"This protection prevents accidental bot lockouts."
                )
                del self.edit_sessions[user_id]
                await self.bot.cache.delete(session_key)
                raise StopPropagation  # Prevent other handlers from processing this message
            success = await self.settings_service.update_setting(key, new_value)

            if success:
                await self.invalidate_related_caches(key)
                await self.bot.cache.set(
                    CacheKeyGenerator.recent_settings_edit(user_id),
                    True,
                    expire=10  # 10 seconds to prevent search trigger
                )
                # Delete the message containing the value for security
                await message.delete()
                
                # Also delete the editing message
                try:
                    editing_msg_id = session['message_id']
                    await client.delete_messages(message.chat.id, editing_msg_id)
                except Exception as e:
                    logger.warning(f"Could not delete editing message: {e}")

                # Send success message with restart reminder
                success_msg = await client.send_message(
                    message.chat.id,
                    f"✅ Setting **{self._get_display_name(key)}** updated successfully!\n\n"
                    f"⚠️ **Important:** You must restart the bot for changes to take effect.\n\n"
                    f"Use `/restart` command now to apply changes."
                )

                # Clean up session immediately to prevent search triggers
                del self.edit_sessions[user_id]
                await self.bot.cache.delete(session_key)
                
                # Schedule auto-delete of success message
                asyncio.create_task(self._auto_delete_message(success_msg, 10))
                
                # Prevent any other handlers from processing this message
                raise StopPropagation
            else:
                # Clean up session on failure too
                del self.edit_sessions[user_id]
                await self.bot.cache.delete(session_key)
                await message.reply_text("❌ Failed to update setting.")
                raise StopPropagation  # Prevent search trigger even on failure
        except Exception as e:
            # Clean up session on error
            if user_id in self.edit_sessions:
                del self.edit_sessions[user_id]
            await self.bot.cache.delete(session_key)
            
            # Better error message handling
            error_msg = str(e).strip() if str(e).strip() else "Unknown error occurred"
            logger.error(f"Error in bot settings edit for user {user_id}: {error_msg}", exc_info=True)
            
            await message.reply_text(f"❌ Error updating setting: {error_msg}")
            raise StopPropagation  # Prevent search trigger on error

    async def _edit_timeout(self, user_id: int, timeout: int):
        """Handle edit session timeout"""
        await asyncio.sleep(timeout)

        if user_id in self.edit_sessions:
            del self.edit_sessions[user_id]
            session_key = CacheKeyGenerator.edit_session(user_id)
            await self.bot.cache.delete(session_key)
            logger.info(f"Edit session timed out for user {user_id}")

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

    async def restart_command(self, client: Client, message: Message):
        """Handle /restart command"""
        import os
        import sys
        import subprocess
        import platform
        import shutil
        from pathlib import Path

        restart_msg = await message.reply_text("🔄 **Restarting bot...**")

        # Save restart message info
        with open("restart_msg.txt", "w") as f:
            f.write(f"{restart_msg.chat.id},{restart_msg.id}")

        # Get upstream settings
        upstream_repo = await self.settings_service.get_setting('UPSTREAM_REPO')
        upstream_branch = await self.settings_service.get_setting('UPSTREAM_BRANCH')

        if upstream_repo and upstream_branch:
            await restart_msg.edit_text("🔄 **Pulling updates from upstream...**")

            try:
                # Pull from upstream
                subprocess.run(["git", "stash"])
                subprocess.run(["git", "pull", upstream_repo, upstream_branch], check=True)
                shutil.rmtree("logs", ignore_errors=True)
                await restart_msg.edit_text("✅ **Updates pulled! Restarting...**")
            except Exception as e:
                logger.error(f"Failed to pull updates: {e}")
                await restart_msg.edit_text("⚠️ **Failed to pull updates. Restarting anyway...**")

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
                await restart_msg.edit_text(f"❌ **Restart failed:** {str(e)}")
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
        }

        return display_map.get(key, key)