import hashlib
import re

from pyrogram import Client, enums
from pyrogram.types import CallbackQuery

from handlers.commands_handlers import BaseCommandHandler
from core.utils.logger import get_logger
from handlers.decorators import check_ban
from core.utils.telegram_api import telegram_api
from core.utils.validators import extract_user_id, is_admin, is_group_owner

logger = get_logger(__name__)

class FilterCallBackHandler(BaseCommandHandler):

    @check_ban()
    async def handle_filter_alert_callback(self, client: Client, query: CallbackQuery):
        """Handle filter alert callbacks"""
        if not query.message:
            return await query.answer("No message context", show_alert=True)
        private = query.message.chat.type == enums.ChatType.PRIVATE
        try:
            if query.data.startswith("filteralert:"):
                _, group, index, digest = query.data.split(":")
                group_id, alert_index = int(group), int(index)
                if alert_index < 0 or not re.fullmatch(r"[0-9a-f]{16}", digest):
                    raise ValueError("Invalid alert identity")
                if private:
                    if (query.message.chat.id != query.from_user.id
                            or not await self.bot.connection_service.can_manage_group(client, query.from_user.id, group_id)):
                        return await query.answer("You need to be an admin in the source group!", show_alert=True)
                elif query.message.chat.id != group_id:
                    return await query.answer("This alert belongs to another group", show_alert=True)
                keywords = await self.bot.filter_service.get_all_filters(str(group_id))
                keyword = next((word for word in keywords
                                if hashlib.sha256(word.encode()).hexdigest()[:16] == digest), None)
                if keyword is None:
                    return await query.answer("Alert not found", show_alert=True)
            else:
                _, index, keyword = query.data.split(":", 2)
                alert_index = int(index)
                if alert_index < 0:
                    raise ValueError("Negative alert index")
                if private:
                    return await query.answer("Run the filter again to refresh this alert", show_alert=True)
                group_id = query.message.chat.id
        except (ValueError, IndexError) as e:
            logger.warning(f"Invalid filter alert callback: {query.data}, error: {e}")
            return await query.answer("Invalid data format", show_alert=True)

        reply_text, btn, alerts, fileid = await self.bot.filter_service.get_filter(
            str(group_id), keyword
        )

        if alerts:
            import ast
            try:
                parsed_alerts = ast.literal_eval(alerts)
                if isinstance(parsed_alerts, list) and 0 <= alert_index < len(parsed_alerts) and isinstance(parsed_alerts[alert_index], str):
                    alert = parsed_alerts[alert_index]
                    alert = alert.replace("\\n", "\n").replace("\\t", "\t")
                    if len(alert.encode("utf-8")) > 200:
                        alert = alert.encode("utf-8")[:197].decode("utf-8", errors="ignore") + "…"
                    await query.answer(alert, show_alert=True)
                else:
                    await query.answer("Alert index out of range", show_alert=True)
            except (ValueError, SyntaxError) as e:
                logger.warning(f"Failed to parse alerts data: {e}")
                await query.answer("Error parsing alert data", show_alert=True)
        else:
            await query.answer("Alert not found", show_alert=True)

    @check_ban()
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

    @check_ban()
    async def handle_delall_cancel_callback(self, client: Client, query: CallbackQuery):
        """Handle delete all filters cancellation"""
        await query.message.delete()
        try:
            await query.message.reply_to_message.delete()
        except Exception:
            pass  # Reply message may already be deleted or inaccessible