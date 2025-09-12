import asyncio

from pyrogram import Client, filters, enums
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from core.services.connection import ConnectionService
from core.utils.logger import get_logger
from core.utils.telegram_api import telegram_api

logger = get_logger(__name__)


class ConnectionHandler:
    """Handler for connection management commands"""

    def __init__(self, bot, connection_service: ConnectionService):
        self.bot = bot
        self.connection_service = connection_service
        self._handlers = []  # Track handlers
        self._shutdown = asyncio.Event()
        self.register_handlers()

    def register_handlers(self):
        """Register connection handlers"""
        # Check if filters are disabled (connections are mainly for filters)
        if self.bot.config.DISABLE_FILTER:
            logger.info("Connections are disabled via DISABLE_FILTER config")
            return

        # Command handlers
        command_handlers = [
            (self.connect_command, filters.command("connect") & (filters.private | filters.group)),
            (self.disconnect_command, filters.command("disconnect") & (filters.private | filters.group)),
            (self.connections_command, filters.command("connections") & filters.private)
        ]

        for handler_func, handler_filter in command_handlers:
            handler = MessageHandler(handler_func, handler_filter)

            # Use handler_manager if available
            if hasattr(self.bot, 'handler_manager') and self.bot.handler_manager:
                self.bot.handler_manager.add_handler(handler)
            else:
                self.bot.add_handler(handler)

            self._handlers.append(handler)

        # Callback handlers
        callback_handlers = [
            (self.connection_callback, filters.regex(r"^groupcb:")),
            (self.connection_action_callback, filters.regex(
                r"^(connect_group|deactivate_group|delete_connection|disconnect_group|disconnect_group_with_filters):")),
            (self.cleanup_connections_callback, filters.regex(r"^cleanup_connections$")),
            (self.delete_group_filters_callback, filters.regex(r"^delete_group_filters:"))
        ]

        for handler_func, handler_filter in callback_handlers:
            handler = CallbackQueryHandler(handler_func, handler_filter)

            # Use handler_manager if available
            if hasattr(self.bot, 'handler_manager') and self.bot.handler_manager:
                self.bot.handler_manager.add_handler(handler)
            else:
                self.bot.add_handler(handler)

            self._handlers.append(handler)

        logger.info(f"ConnectionHandler registered {len(self._handlers)} handlers")

    async def cleanup(self):
        """Clean up handler resources"""
        logger.info("Cleaning up ConnectionHandler...")

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
            logger.info("ConnectionHandler cleanup complete")
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
        logger.info("ConnectionHandler cleanup complete")

    async def connect_command(self, client: Client, message: Message):
        """Handle /connect command"""
        user_id = message.from_user.id if message.from_user else None
        if not user_id:
            return await message.reply(
                f"You are anonymous admin. Use /connect {message.chat.id} in PM"
            )

        chat_type = message.chat.type
        group_id = None

        if chat_type == enums.ChatType.PRIVATE:
            # Private chat - expect group ID as argument
            try:
                cmd, group_id = message.text.split(" ", 1)
                # Try to parse as integer
                try:
                    group_id = int(group_id)
                except ValueError:
                    # Might be a username, keep as string
                    pass
            except ValueError:
                await message.reply_text(
                    "<b>Enter in correct format!</b>\n\n"
                    "<code>/connect groupid</code>\n\n"
                    "<i>Get your Group id by adding this bot to your group and use <code>/id</code></i>",
                    quote=True
                )
                return

        elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            # Group chat - use current chat ID
            group_id = message.chat.id
        else:
            return await message.reply_text("Unsupported chat type.", quote=True)

        # Try to connect
        try:
            # Get chat info
            chat = await client.get_chat(group_id)
            group_id = chat.id  # Get numeric ID

            success, msg, title = await self.connection_service.connect_to_group(
                client, user_id, group_id
            )

            if success:
                await message.reply_text(msg, quote=True, parse_mode=enums.ParseMode.HTML)

                # If connected from group, send confirmation to PM
                if chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
                    try:
                        await telegram_api.call_api(
                            client.send_message,
                            user_id,
                            f"Connected to <b>{title}</b>!",
                            parse_mode=enums.ParseMode.HTML,
                            chat_id=user_id
                        )
                    except Exception:
                        pass
            else:
                await message.reply_text(msg, quote=True)

        except Exception as e:
            error_msg = str(e).lower()
            if "channel_private" in error_msg or "chat not found" in error_msg:
                await message.reply_text(
                    "❌ <b>Cannot Access Group</b>\n\n"
                    "This group is private or I'm not a member.\n"
                    "Please add me to the group and make me an admin first.",
                    quote=True
                )
            else:
                logger.error(f"Error in connect command: {e}")
                await message.reply_text(
                    "Invalid Group ID or Username!\n\n"
                    "If correct, make sure I'm present in your group!",
                    quote=True
                )

    async def disconnect_command(self, client: Client, message: Message):
        """Handle /disconnect command"""
        user_id = message.from_user.id if message.from_user else None
        if not user_id:
            return await message.reply(
                f"You are anonymous admin. Use /connect {message.chat.id} in PM"
            )

        chat_type = message.chat.type

        if chat_type == enums.ChatType.PRIVATE:
            await message.reply_text(
                "Run /connections to view or disconnect from groups!",
                quote=True
            )

        elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            group_id = message.chat.id

            # Check if user has permission
            if user_id not in self.bot.config.ADMINS:
                try:
                    member = await client.get_chat_member(group_id, user_id)
                    if member.status not in [
                        enums.ChatMemberStatus.ADMINISTRATOR,
                        enums.ChatMemberStatus.OWNER
                    ]:
                        return
                except:
                    return

            success, msg = await self.connection_service.disconnect_from_group(
                client,user_id, group_id
            )

            if success:
                await message.reply_text(msg, quote=True)
                if not self.bot.config.DISABLE_FILTER and self.bot.filter_service:
                    try:
                        filter_count = await self.bot.filter_service.count_filters(str(group_id))
                        if filter_count > 0:
                            buttons = [
                                [
                                    InlineKeyboardButton(
                                        f"🗑 Delete {filter_count} filters",
                                        callback_data=f"delete_group_filters:{group_id}"
                                    )
                                ],
                                [
                                    InlineKeyboardButton(
                                        "✅ Keep filters",
                                        callback_data="close_data"
                                    )
                                ]
                            ]
                            await message.reply_text(
                                f"Group disconnected. Found {filter_count} filters.\n"
                                "Do you want to delete them?",
                                reply_markup=InlineKeyboardMarkup(buttons),
                                quote=True
                            )
                    except Exception as e:
                        logger.error(f"Error checking filters: {e}")
            else:
                await message.reply_text(
                    f"{msg}\nDo /connect to connect.",
                    quote=True
                )

    async def delete_group_filters_callback(self, client: Client, query: CallbackQuery):
        """Handle delete group filters callback"""
        user_id = query.from_user.id
        group_id = query.data.split(":")[1]

        # Check permission
        if user_id not in self.bot.config.ADMINS:
            try:
                member = await client.get_chat_member(int(group_id), user_id)
                if member.status not in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER
                ]:
                    return await query.answer("You need admin rights!", show_alert=True)
            except:
                return await query.answer("Error checking permissions", show_alert=True)

        # Delete filters
        if self.bot.filter_service:
            try:
                success = await self.bot.filter_service.delete_all_filters(str(group_id))
                if success:
                    await query.answer("✅ All filters deleted!", show_alert=True)
                    await query.message.edit_text("✅ All filters have been deleted from the group.")
                else:
                    await query.answer("Failed to delete filters", show_alert=True)
            except Exception as e:
                logger.error(f"Error deleting filters: {e}")
                await query.answer("Error deleting filters", show_alert=True)

    async def connections_command(self, client: Client, message: Message):
        """Handle /connections command"""
        user_id = message.from_user.id

        connections = await self.connection_service.get_all_connections(client, user_id)

        if not connections:
            await message.reply_text(
                "There are no active connections!! Connect to some groups first.",
                quote=True
            )
            return

        buttons = []
        for conn in connections:
            title = conn['title']
            if conn['is_active']:
                title += " ✅"

            buttons.append([
                InlineKeyboardButton(
                    text=title,
                    callback_data=f"groupcb:{conn['id']}:{conn['is_active']}"
                )
            ])

        # Add cleanup button
        buttons.append([
            InlineKeyboardButton(
                "🗑 Clean Invalid Connections",
                callback_data="cleanup_connections"
            )
        ])

        await message.reply_text(
            "Your connected group details:\n\n",
            reply_markup=InlineKeyboardMarkup(buttons),
            quote=True
        )

    async def connection_callback(self, client: Client, query: CallbackQuery):
        """Handle connection selection callback"""
        await query.answer()

        if query.data == "back_to_connections":
            return await self.connections_command(client, query.message)

        data = query.data.split(":")
        if len(data) != 3:
            return

        _, group_id, is_active = data
        user_id = query.from_user.id

        # Build action buttons
        buttons = []

        if is_active == "True":
            buttons.append([
                InlineKeyboardButton(
                    "❌ Deactivate",
                    callback_data=f"deactivate_group:{group_id}"
                )
            ])
        else:
            buttons.append([
                InlineKeyboardButton(
                    "✅ Activate",
                    callback_data=f"connect_group:{group_id}"
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                "🗑 Delete Connection",
                callback_data=f"delete_connection:{group_id}"
            )
        ])

        buttons.append([
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data="back_to_connections"
            )
        ])

        try:
            chat = await client.get_chat(int(group_id))
            title = chat.title
            members_count = chat.members_count

            text = (
                f"<b>Group Details</b>\n\n"
                f"📌 Title: {title}\n"
                f"🆔 ID: <code>{group_id}</code>\n"
                f"👥 Members: {members_count}\n"
                f"✅ Status: {'Active' if is_active == 'True' else 'Inactive'}"
            )
        except Exception:
            text = (
                f"<b>Group Details</b>\n\n"
                f"🆔 ID: <code>{group_id}</code>\n"
                f"✅ Status: {'Active' if is_active == 'True' else 'Inactive'}\n"
                f"⚠️ Unable to fetch group details"
            )

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=enums.ParseMode.HTML
        )

    async def connection_action_callback(self, client: Client, query: CallbackQuery):
        """Handle connection action callbacks"""
        user_id = query.from_user.id
        data = query.data.split(":")

        if len(data) != 2:
            return await query.answer("Invalid data", show_alert=True)

        action, group_id = data

        if action == "connect_group":
            # Make group active (will deactivate others automatically)
            success, msg = await self.connection_service.set_active_connection(
                user_id, group_id
            )

            if success:
                await query.answer("✅ Connection activated!", show_alert=True)
            else:
                await query.answer(msg, show_alert=True)

            # Refresh the current view
            query.data = f"groupcb:{group_id}:True"  # Set is_active to True
            await self.connection_callback(client, query)

        elif action == "deactivate_group":
            # Deactivate the group
            success = await self.connection_service.clear_active_connection(user_id)

            if success:
                await query.answer("✅ Connection deactivated!", show_alert=True)
            else:
                await query.answer("Failed to deactivate", show_alert=True)

            # Refresh the current view
            query.data = f"groupcb:{group_id}:False"  # Set is_active to False
            await self.connection_callback(client, query)

        elif action == "delete_connection":
            # Ask about filters
            buttons = [
                [
                    InlineKeyboardButton(
                        "🗑 Delete filters too",
                        callback_data=f"disconnect_group_with_filters:{group_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📁 Keep filters",
                        callback_data=f"disconnect_group:{group_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Cancel",
                        callback_data=f"groupcb:{group_id}:False"
                    )
                ]
            ]

            await query.message.edit_text(
                "Do you want to delete all filters from this group too?",
                reply_markup=InlineKeyboardMarkup(buttons)
            )

        elif action == "disconnect_group" or action == "disconnect_group_with_filters":
            # Delete connection
            delete_filters = action == "disconnect_group_with_filters"

            success, msg = await self.connection_service.disconnect_from_group(
                client, user_id, int(group_id), delete_filters=delete_filters
            )

            if success:
                # If delete_filters is True, delete all filters
                if delete_filters and not self.bot.config.DISABLE_FILTER:
                    await self.bot.filter_service.delete_all_filters(str(group_id))
                    await query.answer("✅ Connection and filters deleted!", show_alert=True)
                else:
                    await query.answer("✅ Connection deleted!", show_alert=True)
            else:
                await query.answer(msg, show_alert=True)

            # Go back to connections list
            await self.connections_command(client, query.message)

    async def cleanup_connections_callback(self, client: Client, query: CallbackQuery):
        """Handle cleanup connections callback"""
        await query.answer("Cleaning up invalid connections...", show_alert=True)

        user_id = query.from_user.id
        removed = await self.connection_service.cleanup_invalid_connections(
            client, user_id
        )

        if removed > 0:
            await query.answer(
                f"Removed {removed} invalid connection(s)!",
                show_alert=True
            )
        else:
            await query.answer("No invalid connections found!", show_alert=True)

        # Refresh connections list
        await self.connections_command(client, query.message)