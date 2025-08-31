from pyrogram import Client, enums
from pyrogram.types import CallbackQuery

from handlers.commands_handlers import BaseCommandHandler
from core.utils.logger import get_logger
logger = get_logger(__name__)

class FilterCallBackHandler(BaseCommandHandler):

    async def handle_filter_alert_callback(self, client: Client, query: CallbackQuery):
        """Handle filter alert callbacks"""
        data = query.data.split(":")
        if len(data) < 3:
            return await query.answer("Invalid data", show_alert=True)

        _, alert_index, keyword = data
        alert_index = int(alert_index)

        # Get the filter to find alerts
        if not query.message:
            return await query.answer("No message context", show_alert=True)
        group_id = query.message.chat.id
        reply_text, btn, alerts, fileid = await self.bot.filter_service.get_filter(
            str(group_id), keyword
        )

        if alerts:
            import ast
            alerts = ast.literal_eval(alerts)
            if alert_index < len(alerts):
                alert = alerts[alert_index]
                alert = alert.replace("\\n", "\n").replace("\\t", "\t")
                await query.answer(alert, show_alert=True)
        else:
            await query.answer("Alert not found", show_alert=True)

    async def handle_delall_confirm_callback(self, client: Client, query: CallbackQuery):
        """Handle delete all filters confirmation"""
        user_id = query.from_user.id
        _, group_id = query.data.split("#")
        group_id = int(group_id)

        # Check permissions
        try:
            member = await client.get_chat_member(group_id, user_id)
            is_authorized = (
                    member.status == enums.ChatMemberStatus.OWNER or
                    user_id in self.bot.config.ADMINS
            )
        except:
            is_authorized = user_id in self.bot.config.ADMINS

        if not is_authorized:
            return await query.answer(
                "You need to be Group Owner or an Auth User to do that!",
                show_alert=True
            )

        # Delete all filters
        success = await self.bot.filter_service.delete_all_filters(str(group_id))

        if success:
            try:
                chat = await client.get_chat(group_id)
                title = chat.title
            except:
                title = f"Group {group_id}"

            await query.message.edit_text(f"All filters from {title} has been removed")
        else:
            await query.message.edit_text("Couldn't remove all filters from group!")

    async def handle_delall_cancel_callback(self, client: Client, query: CallbackQuery):
        """Handle delete all filters cancellation"""
        await query.message.delete()
        try:
            await query.message.reply_to_message.delete()
        except:
            pass