"""
Database management commands for multi-database system
"""

from pyrogram import Client, filters
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from core.utils.button_builder import ButtonBuilder
from core.utils.caption import CaptionFormatter
from core.utils.error_formatter import ErrorMessageFormatter
from core.utils.logger import get_logger
from core.utils.validators import admin_only
from handlers.commands_handlers.base import BaseCommandHandler

logger = get_logger(__name__)


class DatabaseCommandHandler(BaseCommandHandler):
    """Handler for database management commands"""

    def __init__(self, bot):
        super().__init__(bot)
        self.register_handlers()

    def register_handlers(self):
        """Register database management command handlers"""
        self.bot.add_handler(
            MessageHandler(
                self.handle_database_stats,
                filters.command("dbstats") & filters.private & filters.incoming
            )
        )

        self.bot.add_handler(
            MessageHandler(
                self.handle_database_switch,
                filters.command("dbswitch") & filters.private & filters.incoming
            )
        )

        self.bot.add_handler(
            MessageHandler(
                self.handle_database_info,
                filters.command("dbinfo") & filters.private & filters.incoming
            )
        )

        self.bot.add_handler(
            CallbackQueryHandler(
                self.handle_database_callback,
                filters.regex(r"^db_(refresh_stats|detailed_info|stats|refresh_info)$")
            )
        )

    def _get_stats_buttons(self):
        return [
            [ButtonBuilder.action_button("🔄 Refresh Stats", callback_data="db_refresh_stats")],
            [ButtonBuilder.action_button("🔧 Database Info", callback_data="db_detailed_info")]
        ]

    def _get_info_buttons(self):
        return [
            [ButtonBuilder.action_button("📊 View Stats", callback_data="db_stats")],
            [ButtonBuilder.action_button("🔄 Refresh Info", callback_data="db_refresh_info")]
        ]

    def _format_database_stats(self, stats, updated: bool = False) -> str:
        title_suffix = " (Updated)" if updated else ""
        text = f"📊 <b>Database Statistics</b>{title_suffix}\n\n"

        for stat in stats:
            status_emoji = "✅" if stat["is_active"] else "❌"
            write_emoji = "✍️" if stat["is_current_write"] else "📖"

            text += f"{status_emoji} <b>Database {stat['index'] + 1}</b> {write_emoji}\n"
            text += f"   📝 Name: <code>{stat['name']}</code>\n"
            text += f"   📦 Size: <code>{stat['size_gb']}GB / {stat['size_limit_gb']}GB</code>\n"
            text += f"   📈 Usage: <code>{stat['usage_percentage']}%</code>\n"
            text += f"   📄 Files: <code>{stat['files_count']:,}</code>\n"

            if stat["usage_percentage"] >= 90:
                text += "   ⚠️ <b>Near capacity!</b>\n"
            elif stat["usage_percentage"] >= 75:
                text += "   🔶 <b>High usage</b>\n"

            text += "\n"

        text += "<b>Legend:</b>\n"
        text += "✅ Active Database | ❌ Inactive Database\n"
        text += "✍️ Current Write DB | 📖 Read-only DB\n"
        return text

    async def _build_database_info_payload(self):
        """Build database information text and optional buttons."""
        if not hasattr(self.bot, "multi_db_manager") or not self.bot.multi_db_manager:
            if hasattr(self.bot, "config") and not self.bot.config.is_multi_database_enabled:
                text = "📊 <b>Database Information</b>\n"
                text += "<b>Mode:</b> Single Database\n"
                text += f"<b>URI:</b> <code>{self.bot.config.DATABASE_URI[:50]}...</code>\n"
                text += f"<b>Name:</b> <code>{self.bot.config.DATABASE_NAME}</code>\n"
                text += f"<b>Collection:</b> <code>{self.bot.config.COLLECTION_NAME}</code>\n"
                text += "💡 <b>Multi-database mode is not enabled.</b>\n"
                text += "To enable, add `DATABASE_URIS` to your environment variables."
            else:
                text = ErrorMessageFormatter.format_error("Multi-database mode is not properly configured.")
            return text, None

        stats = await self.bot.multi_db_manager.get_database_stats()

        text = "📊 <b>Multi-Database Information</b>\n\n"
        text += f"<b>Mode:</b> Multi-Database ({len(stats)} databases)\n"
        text += f"<b>Auto-switch:</b> <code>{'Enabled' if self.bot.config.DATABASE_AUTO_SWITCH else 'Disabled'}</code>\n"
        text += f"<b>Size Limit:</b> <code>{self.bot.config.DATABASE_SIZE_LIMIT_GB}GB</code> per database\n\n"

        for i, stat in enumerate(stats):
            status = "🟢 Active" if stat["is_active"] else "🔴 Inactive"
            write_status = " (Current Write DB)" if stat["is_current_write"] else ""

            text += f"<b>Database {i + 1}:</b> {status}{write_status}\n"
            text += f"   📝 Name: <code>{stat['name']}</code>\n"
            text += f"   📦 Storage: `{stat['size_gb']:.3f}GB / {stat['size_limit_gb']:.1f}GB`\n"
            text += f"   📊 Usage: `{stat['usage_percentage']:.1f}%`\n"
            text += f"   📄 Files: <code>{stat['files_count']:,}</code>\n"

            if stat["usage_percentage"] >= 90:
                text += "   ⚠️ <b>Critical: Near capacity!</b>\n"
            elif stat["usage_percentage"] >= 75:
                text += "   🔶 <b>Warning: High usage</b>\n"
            elif stat["usage_percentage"] < 25:
                text += "   🔵 <b>Info: Low usage</b>\n"

            text += "\n"

        if any(stat["usage_percentage"] >= 80 for stat in stats):
            text += "💡 <b>Recommendations:</b>\n"
            text += "• Consider adding more databases to `DATABASE_URIS`\n"
            text += "• Monitor storage usage regularly\n"
            text += "• Enable auto-switch if disabled\n"

        return text, self._get_info_buttons()

    @admin_only
    async def handle_database_stats(self, client: Client, message: Message):
        """Handle /dbstats command - show database statistics"""
        try:
            if not hasattr(self.bot, "multi_db_manager") or not self.bot.multi_db_manager:
                await message.reply_text(ErrorMessageFormatter.format_error("Multi-database mode is not enabled"))
                return

            stats = await self.bot.multi_db_manager.get_database_stats()
            if not stats:
                await message.reply_text(ErrorMessageFormatter.format_not_found("Database statistics"))
                return

            await message.reply_text(
                self._format_database_stats(stats),
                reply_markup=InlineKeyboardMarkup(self._get_stats_buttons()),
                parse_mode=CaptionFormatter.get_parse_mode()
            )

        except Exception as e:
            logger.error(f"Error in database stats command: {e}")
            await message.reply_text(
                ErrorMessageFormatter.format_error(f"Error retrieving database stats: {str(e)}")
            )

    @admin_only
    async def handle_database_switch(self, client: Client, message: Message):
        """Handle /dbswitch command - switch write database"""
        try:
            if not hasattr(self.bot, "multi_db_manager") or not self.bot.multi_db_manager:
                await message.reply_text(ErrorMessageFormatter.format_error("Multi-database mode is not enabled"))
                return

            if len(message.command) != 2:
                await message.reply_text(
                    ErrorMessageFormatter.format_error(
                        "<b>Usage:</b> <code>/dbswitch &lt;database_number&gt;</code>\n"
                        "Example: <code>/dbswitch 2</code> (switch to database 2)",
                        title="Usage"
                    )
                )
                return

            try:
                db_index = int(message.command[1]) - 1
            except ValueError:
                await message.reply_text(
                    ErrorMessageFormatter.format_invalid("database number", "Please provide a valid number")
                )
                return

            stats = await self.bot.multi_db_manager.get_database_stats()
            if db_index < 0 or db_index >= len(stats):
                await message.reply_text(
                    ErrorMessageFormatter.format_invalid(
                        "database number",
                        f"Available databases: 1-{len(stats)}"
                    )
                )
                return

            if not stats[db_index]["is_active"]:
                await message.reply_text(
                    ErrorMessageFormatter.format_error(f"Database {db_index + 1} is not active")
                )
                return

            success = await self.bot.multi_db_manager.set_write_database(db_index)

            if success:
                db_name = stats[db_index]["name"]
                await message.reply_text(
                    ErrorMessageFormatter.format_success(
                        f"Successfully switched to Database {db_index + 1}",
                        title="Database Switch"
                    ) + "\n"
                    f"📝 Name: <code>{db_name}</code>\n"
                    f"📦 Size: <code>{stats[db_index]['size_gb']}GB</code>\n"
                    f"📄 Files: <code>{stats[db_index]['files_count']:,}</code>"
                )
            else:
                await message.reply_text(ErrorMessageFormatter.format_failed("to switch database"))

        except Exception as e:
            logger.error(f"Error in database switch command: {e}")
            await message.reply_text(
                ErrorMessageFormatter.format_error(f"Error switching database: {str(e)}")
            )

    @admin_only
    async def handle_database_info(self, client: Client, message: Message):
        """Handle /dbinfo command - show detailed database information"""
        try:
            text, buttons = await self._build_database_info_payload()
            await message.reply_text(
                text,
                reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
                parse_mode=CaptionFormatter.get_parse_mode()
            )
        except Exception as e:
            logger.error(f"Error in database info command: {e}")
            await message.reply_text(
                ErrorMessageFormatter.format_error(f"Error retrieving database info: {str(e)}")
            )

    @admin_only
    async def handle_database_callback(self, client: Client, callback_query: CallbackQuery):
        """Handle database management callbacks"""
        try:
            data = callback_query.data

            if data == "db_refresh_stats":
                await self._refresh_database_stats(callback_query)
            elif data == "db_detailed_info":
                await self._show_detailed_info(callback_query)
            elif data == "db_stats":
                await self._show_database_stats(callback_query)
            elif data == "db_refresh_info":
                await self._refresh_database_info(callback_query)

        except Exception as e:
            logger.error(f"Error in database callback: {e}")
            await callback_query.answer(
                ErrorMessageFormatter.format_error("Error processing request", plain_text=True),
                show_alert=True
            )

    async def _refresh_database_stats(self, callback_query: CallbackQuery):
        """Refresh database statistics"""
        if not self.bot.multi_db_manager:
            await callback_query.answer(
                ErrorMessageFormatter.format_error("Multi-database not enabled", plain_text=True),
                show_alert=True
            )
            return

        await callback_query.answer("🔄 Refreshing stats...")

        await self.bot.multi_db_manager._update_database_stats_with_circuit_breaker(force=True)
        stats = await self.bot.multi_db_manager.get_database_stats()

        await callback_query.message.edit_text(
            self._format_database_stats(stats, updated=True),
            reply_markup=InlineKeyboardMarkup(self._get_stats_buttons()),
            parse_mode=CaptionFormatter.get_parse_mode()
        )

    async def _show_detailed_info(self, callback_query: CallbackQuery):
        """Show detailed database information"""
        await callback_query.answer()
        text, buttons = await self._build_database_info_payload()
        await callback_query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
            parse_mode=CaptionFormatter.get_parse_mode()
        )

    async def _show_database_stats(self, callback_query: CallbackQuery):
        """Show database statistics"""
        await callback_query.answer()

        if not self.bot.multi_db_manager:
            await callback_query.message.edit_text(
                ErrorMessageFormatter.format_error("Multi-database mode is not enabled")
            )
            return

        stats = await self.bot.multi_db_manager.get_database_stats()
        if not stats:
            await callback_query.message.edit_text(
                ErrorMessageFormatter.format_not_found("Database statistics")
            )
            return

        await callback_query.message.edit_text(
            self._format_database_stats(stats),
            reply_markup=InlineKeyboardMarkup(self._get_stats_buttons()),
            parse_mode=CaptionFormatter.get_parse_mode()
        )

    async def _refresh_database_info(self, callback_query: CallbackQuery):
        """Refresh database information"""
        await callback_query.answer("🔄 Refreshing database info...")

        if not self.bot.multi_db_manager:
            await callback_query.message.edit_text(
                ErrorMessageFormatter.format_error("Multi-database mode is not enabled")
            )
            return

        await self.bot.multi_db_manager._update_database_stats_with_circuit_breaker(force=True)

        text, buttons = await self._build_database_info_payload()
        await callback_query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
            parse_mode=CaptionFormatter.get_parse_mode()
        )
