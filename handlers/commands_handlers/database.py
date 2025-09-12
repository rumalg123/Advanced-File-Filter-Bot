"""
Database management commands for multi-database system
"""

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.enums import ParseMode

from core.utils.validators import admin_only
from handlers.commands_handlers.base import BaseCommandHandler
from core.utils.logger import get_logger

logger = get_logger(__name__)


class DatabaseCommandHandler(BaseCommandHandler):
    """Handler for database management commands"""

    def __init__(self, bot):
        super().__init__(bot)
        self.register_handlers()

    def register_handlers(self):
        """Register database management command handlers"""
        # Register /dbstats command
        self.bot.add_handler(
            MessageHandler(
                self.handle_database_stats, 
                filters.command("dbstats") & filters.private & filters.incoming
            )
        )
        
        # Register /dbswitch command  
        self.bot.add_handler(
            MessageHandler(
                self.handle_database_switch, 
                filters.command("dbswitch") & filters.private & filters.incoming
            )
        )
        
        # Register /dbinfo command
        self.bot.add_handler(
            MessageHandler(
                self.handle_database_info, 
                filters.command("dbinfo") & filters.private & filters.incoming
            )
        )
        
        # Register callback handlers for database management buttons
        self.bot.add_handler(
            CallbackQueryHandler(
                self.handle_database_callback,
                filters.regex(r"^db_(refresh_stats|detailed_info|stats|refresh_info)$")
            )
        )

    @admin_only
    async def handle_database_stats(self, client: Client, message: Message):
        """Handle /dbstats command - show database statistics"""
        try:
            if not hasattr(self.bot, 'multi_db_manager') or not self.bot.multi_db_manager:
                await message.reply_text("❌ Multi-database mode is not enabled.")
                return

            # Get database statistics
            stats = await self.bot.multi_db_manager.get_database_stats()
            
            if not stats:
                await message.reply_text("❌ No database statistics available.")
                return

            # Format statistics
            text = "📊 <b>Database Statistics</b>\n"
            
            for stat in stats:
                status_emoji = "✅" if stat['is_active'] else "❌"
                write_emoji = "✍️" if stat['is_current_write'] else "📖"
                
                text += f"{status_emoji} <b>Database {stat['index'] + 1}</b> {write_emoji}\n"
                text += f"   📝 Name: <code>{stat['name']}</code>\n"
                text += f"   📦 Size: <code>{stat['size_gb']}GB / {stat['size_limit_gb']}GB</code>\n"
                text += f"   📈 Usage: <code>{stat['usage_percentage']}%</code>\n"
                text += f"   📄 Files: <code>{stat['files_count']:,}</code>\n"
                
                if stat['usage_percentage'] >= 90:
                    text += "   ⚠️ <b>Near capacity!</b>\n"
                elif stat['usage_percentage'] >= 75:
                    text += "   🔶 <b>High usage</b>\n"
                    
                text += "\n"
            
            # Add legend
            text += "<b>Legend:</b>\n"
            text += "✅ Active Database | ❌ Inactive Database\n"
            text += "✍️ Current Write DB | 📖 Read-only DB\n"

            # Create management buttons
            buttons = [
                [InlineKeyboardButton("🔄 Refresh Stats", callback_data="db_refresh_stats")],
                [InlineKeyboardButton("🔧 Database Info", callback_data="db_detailed_info")]
            ]

            await message.reply_text(
                text,
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode=ParseMode.HTML
            )

        except Exception as e:
            logger.error(f"Error in database stats command: {e}")
            await message.reply_text(f"❌ Error retrieving database stats: {str(e)}")

    @admin_only
    async def handle_database_switch(self, client: Client, message: Message):
        """Handle /dbswitch command - switch write database"""
        try:
            if not hasattr(self.bot, 'multi_db_manager') or not self.bot.multi_db_manager:
                await message.reply_text("❌ Multi-database mode is not enabled.")
                return

            # Parse command arguments
            if len(message.command) != 2:
                await message.reply_text(
                    "❌ <b>Usage:</b> <code>/dbswitch &lt;database_number&gt;</code>\n"
                    "Example: <code>/dbswitch 2</code> (switch to database 2)"
                )
                return

            try:
                db_index = int(message.command[1]) - 1  # Convert to 0-based index
            except ValueError:
                await message.reply_text("❌ Invalid database number. Please provide a valid number.")
                return

            # Get database stats to validate
            stats = await self.bot.multi_db_manager.get_database_stats()
            if db_index < 0 or db_index >= len(stats):
                await message.reply_text(f"❌ Invalid database number. Available databases: 1-{len(stats)}")
                return

            if not stats[db_index]['is_active']:
                await message.reply_text(f"❌ Database {db_index + 1} is not active.")
                return

            # Switch database
            success = await self.bot.multi_db_manager.set_write_database(db_index)
            
            if success:
                db_name = stats[db_index]['name']
                await message.reply_text(
                    f"✅ <b>Successfully switched to Database {db_index + 1}</b>\n"
                    f"📝 Name: <code>{db_name}</code>\n"
                    f"📦 Size: <code>{stats[db_index]['size_gb']}GB</code>\n"
                    f"📄 Files: <code>{stats[db_index]['files_count']:,}</code>"
                )
            else:
                await message.reply_text("❌ Failed to switch database.")

        except Exception as e:
            logger.error(f"Error in database switch command: {e}")
            await message.reply_text(f"❌ Error switching database: {str(e)}")

    @admin_only
    async def handle_database_info(self, client: Client, message: Message):
        """Handle /dbinfo command - show detailed database information"""
        try:
            if not hasattr(self.bot, 'multi_db_manager') or not self.bot.multi_db_manager:
                if hasattr(self.bot, 'config') and not self.bot.config.is_multi_database_enabled:
                    text = "📊 <b>Database Information</b>\n"
                    text += "<b>Mode:</b> Single Database\n"
                    text += f"<b>URI:</b> <code>{self.bot.config.DATABASE_URI[:50]}...</code>\n"
                    text += f"<b>Name:</b> <code>{self.bot.config.DATABASE_NAME}</code>\n"
                    text += f"<b>Collection:</b> <code>{self.bot.config.COLLECTION_NAME}</code>\n"
                    text += "💡 <b>Multi-database mode is not enabled.</b>\n"
                    text += "To enable, add `DATABASE_URIS` to your environment variables."
                else:
                    text = "❌ Multi-database mode is not properly configured."
                
                await message.reply_text(text)
                return

            # Get detailed information
            stats = await self.bot.multi_db_manager.get_database_stats()
            
            text = "📊 <b>Multi-Database Information</b>\n\n"
            text += f"<b>Mode:</b> Multi-Database ({len(stats)} databases)\n"
            text += f"<b>Auto-switch:</b> <code>{'Enabled' if self.bot.config.DATABASE_AUTO_SWITCH else 'Disabled'}</code>\n"
            text += f"<b>Size Limit:</b> <code>{self.bot.config.DATABASE_SIZE_LIMIT_GB}GB</code> per database\n\n"
            
            # Database details
            for i, stat in enumerate(stats):
                status = "🟢 Active" if stat['is_active'] else "🔴 Inactive"
                write_status = " (Current Write DB)" if stat['is_current_write'] else ""
                
                text += f"<b>Database {i + 1}:</b> {status}{write_status}\n"
                text += f"   📝 Name: <code>{stat['name']}</code>\n"
                text += f"   📦 Storage: `{stat['size_gb']:.3f}GB / {stat['size_limit_gb']:.1f}GB`\n"
                text += f"   📊 Usage: `{stat['usage_percentage']:.1f}%`\n"
                text += f"   📄 Files: <code>{stat['files_count']:,}</code>\n"
                
                if stat['usage_percentage'] >= 90:
                    text += "   ⚠️ <b>Critical: Near capacity!</b>\n"
                elif stat['usage_percentage'] >= 75:
                    text += "   🔶 <b>Warning: High usage</b>\n"
                elif stat['usage_percentage'] < 25:
                    text += "   🔵 <b>Info: Low usage</b>\n"
                    
                text += "\n"

            # Add usage recommendations
            if any(stat['usage_percentage'] >= 80 for stat in stats):
                text += "💡 <b>Recommendations:</b>\n"
                text += "• Consider adding more databases to `DATABASE_URIS`\n"
                text += "• Monitor storage usage regularly\n"
                text += "• Enable auto-switch if disabled\n"

            buttons = [
                [InlineKeyboardButton("📊 View Stats", callback_data="db_stats")],
                [InlineKeyboardButton("🔄 Refresh Info", callback_data="db_refresh_info")]
            ]

            await message.reply_text(
                text,
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode=ParseMode.HTML
            )

        except Exception as e:
            logger.error(f"Error in database info command: {e}")
            await message.reply_text(f"❌ Error retrieving database info: {str(e)}")

    async def handle_database_callback(self, client: Client, callback_query):
        """Handle database management callbacks"""
        try:
            data = callback_query.data
            
            if data == "db_refresh_stats":
                # Refresh and show stats
                await self._refresh_database_stats(callback_query)
            elif data == "db_detailed_info":
                # Show detailed info
                await self._show_detailed_info(callback_query)
            elif data == "db_stats":
                # Show stats
                await self._show_database_stats(callback_query)
            elif data == "db_refresh_info":
                # Refresh info
                await self._refresh_database_info(callback_query)

        except Exception as e:
            logger.error(f"Error in database callback: {e}")
            await callback_query.answer("❌ Error processing request", show_alert=True)

    async def _refresh_database_stats(self, callback_query):
        """Refresh database statistics"""
        if not self.bot.multi_db_manager:
            await callback_query.answer("❌ Multi-database not enabled", show_alert=True)
            return

        await callback_query.answer("🔄 Refreshing stats...")
        
        # Force update stats using circuit breaker protected method
        stats = await self.bot.multi_db_manager.get_database_stats()
        # Force fresh stats by calling with force=True
        await self.bot.multi_db_manager._update_database_stats_with_circuit_breaker(force=True)
        stats = await self.bot.multi_db_manager.get_database_stats()
        
        # Format updated statistics
        text = "📊 <b>Database Statistics</b> (Updated)\n\n"
        
        for stat in stats:
            status_emoji = "✅" if stat['is_active'] else "❌"
            write_emoji = "✍️" if stat['is_current_write'] else "📖"
            
            text += f"{status_emoji} <b>Database {stat['index'] + 1}</b> {write_emoji}\n"
            text += f"   📝 Name: `{stat['name']}`\n"
            text += f"   📦 Size: `{stat['size_gb']}GB / {stat['size_limit_gb']}GB`\n"
            text += f"   📈 Usage: `{stat['usage_percentage']}%`\n"
            text += f"   📄 Files: `{stat['files_count']:,}`\n\n"

        buttons = [
            [InlineKeyboardButton("🔄 Refresh Stats", callback_data="db_refresh_stats")],
            [InlineKeyboardButton("🔧 Database Info", callback_data="db_detailed_info")]
        ]

        await callback_query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML
        )

    async def _show_detailed_info(self, callback_query):
        """Show detailed database information"""
        await callback_query.answer()
        # This would typically show more detailed technical info
        # For now, redirect to info command
        await self.handle_database_info(self.bot, callback_query.message)

    async def _show_database_stats(self, callback_query):
        """Show database statistics"""
        await callback_query.answer()
        # Redirect to stats command
        await self.handle_database_stats(self.bot, callback_query.message)

    async def _refresh_database_info(self, callback_query):
        """Refresh database information"""
        await callback_query.answer("🔄 Refreshing database info...")
        
        if not self.bot.multi_db_manager:
            await callback_query.message.edit_text("❌ Multi-database mode is not enabled.")
            return

        # Force update stats using circuit breaker protected method
        await self.bot.multi_db_manager._update_database_stats_with_circuit_breaker(force=True)
        
        # Show updated info
        await self.handle_database_info(self.bot, callback_query.message)