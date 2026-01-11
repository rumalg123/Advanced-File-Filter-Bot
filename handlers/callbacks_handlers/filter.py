from pyrogram import Client, enums
from pyrogram.types import CallbackQuery

from handlers.commands_handlers import BaseCommandHandler
from core.utils.logger import get_logger
from core.utils.telegram_api import telegram_api
from core.utils.validators import extract_user_id, is_admin, is_group_owner

logger = get_logger(__name__)

class FilterCallBackHandler(BaseCommandHandler):

    async def handle_filter_alert_callback(self, client: Client, query: CallbackQuery):
        """Handle filter alert callbacks"""
        try:
            data = query.data.split(":")
            if len(data) < 3:
                return await query.answer("Invalid data", show_alert=True)

            _, alert_index, keyword = data[0], data[1], ":".join(data[2:])  # Handle keywords with colons
            alert_index = int(alert_index)
        except (ValueError, IndexError) as e:
            logger.warning(f"Invalid filter alert callback: {query.data}, error: {e}")
            return await query.answer("Invalid data format", show_alert=True)

        # Get the filter to find alerts
        if not query.message:
            return await query.answer("No message context", show_alert=True)
        group_id = query.message.chat.id
        reply_text, btn, alerts, fileid = await self.bot.filter_service.get_filter(
            str(group_id), keyword
        )

        if alerts:
            import ast
            try:
                parsed_alerts = ast.literal_eval(alerts)
                if isinstance(parsed_alerts, list) and alert_index < len(parsed_alerts):
                    alert = parsed_alerts[alert_index]
                    alert = alert.replace("\\n", "\n").replace("\\t", "\t")
                    await query.answer(alert, show_alert=True)
                else:
                    await query.answer("Alert index out of range", show_alert=True)
            except (ValueError, SyntaxError) as e:
                logger.warning(f"Failed to parse alerts data: {e}")
                await query.answer("Error parsing alert data", show_alert=True)
        else:
            await query.answer("Alert not found", show_alert=True)

    async def handle_delall_confirm_callback(self, client: Client, query: CallbackQuery):
        """Handle delete all filters confirmation"""
        user_id = extract_user_id(query)

        # Parse callback data safely
        try:
            parts = query.data.split("#", 1)
            if len(parts) < 2:
                return await query.answer("Invalid callback data", show_alert=True)
            group_id = int(parts[1])
        except (ValueError, IndexError) as e:
            logger.warning(f"Invalid delall callback: {query.data}, error: {e}")
            return await query.answer("Invalid data format", show_alert=True)

        # Check permissions using validators
        is_authorized = is_admin(user_id, self.bot.config.ADMINS) or await is_group_owner(client, group_id, user_id)

        if not is_authorized:
            return await query.answer(
                "You need to be Group Owner or an Auth User to do that!",
                show_alert=True
            )

        # Delete all filters
        success = await self.bot.filter_service.delete_all_filters(str(group_id))

        if success:
            try:
                chat = await telegram_api.call_api(
                    client.get_chat,
                    group_id,
                    chat_id=group_id
                )
                title = chat.title
            except Exception:
                title = f"Group {group_id}"

            await query.message.edit_text(f"All filters from {title} has been removed")
        else:
            await query.message.edit_text("Couldn't remove all filters from group!")

    async def handle_delall_cancel_callback(self, client: Client, query: CallbackQuery):
        """Handle delete all filters cancellation"""
        await query.message.delete()
        try:
            await query.message.reply_to_message.delete()
        except Exception:
            pass  # Reply message may already be deleted or inaccessible