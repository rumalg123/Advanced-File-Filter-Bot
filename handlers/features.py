"""Commands and callbacks for independently flagged additive features."""

import html
import shlex

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from core.utils.button_builder import ButtonBuilder
from core.utils.caption import CaptionFormatter
from core.utils.helpers import format_file_size
from core.utils.logger import get_logger
from core.utils.pagination import create_search_query_reference
from handlers.base import BaseHandler
from handlers.decorators import check_ban, require_subscription

logger = get_logger(__name__)


class FeatureHandler(BaseHandler):
    """Register only commands whose deployment flag is enabled."""

    REPORT_REASONS = {
        'broken': 'Broken or unavailable',
        'incorrect': 'Incorrect title or metadata',
        'duplicate': 'Duplicate file',
        'quality': 'Poor quality',
    }

    def __init__(self, bot):
        super().__init__(bot)
        self.service = bot.feature_service
        self.repository = bot.feature_repo
        self.register_handlers()

    def register_handlers(self) -> None:
        user_handlers = []
        callback_needed = False

        if self.service.enabled('FEATURE_SAVED_SEARCH_ALERTS'):
            user_handlers.extend([
                (self.save_search_command, filters.command('save_search') & filters.private),
                (self.saved_searches_command, filters.command('saved_searches') & filters.private),
            ])
            callback_needed = True

        if self.service.enabled('FEATURE_FAVORITES'):
            user_handlers.extend([
                (self.favorite_command, filters.command('favorite') & filters.private),
                (self.unfavorite_command, filters.command('unfavorite') & filters.private),
                (self.favorites_command, filters.command('favorites') & filters.private),
                (self.collections_command, filters.command('collections') & filters.private),
                (self.collection_create_command, filters.command('collection_create') & filters.private),
                (self.collection_delete_command, filters.command('collection_delete') & filters.private),
            ])
            callback_needed = True

        if self.service.enabled('FEATURE_RECENT_FILES'):
            user_handlers.extend([
                (self.recent_command, filters.command('recent') & filters.private),
                (self.clear_recent_command, filters.command('clear_recent') & filters.private),
            ])

        if self.service.enabled('FEATURE_SEARCH_AUTOCOMPLETE'):
            user_handlers.append(
                (self.suggest_command, filters.command('suggest') & filters.private)
            )

        if self.service.enabled('FEATURE_ADVANCED_SEARCH'):
            user_handlers.append(
                (self.search_help_command, filters.command('search_help') & filters.private)
            )

        if self.service.enabled('FEATURE_REQUEST_TRACKING'):
            user_handlers.append(
                (self.my_requests_command, filters.command('myrequests') & filters.private)
            )

        if self.service.enabled('FEATURE_RECOMMENDATION_FEEDBACK'):
            callback_needed = True
        if self.service.enabled('FEATURE_FILE_REPORTS'):
            callback_needed = True

        self._register_message_handlers(user_handlers)

        if callback_needed:
            self._register_callback_handlers([
                (self.feature_callback, filters.regex(r'^feature#'))
            ])

        if self.bot.config.ADMINS and self.service.enabled('FEATURE_FILE_REPORTS'):
            self._register_message_handlers([
                (
                    self.file_reports_command,
                    filters.command('file_reports') & filters.user(self.bot.config.ADMINS)
                ),
                (
                    self.resolve_report_command,
                    filters.command('resolve_report') & filters.user(self.bot.config.ADMINS)
                ),
            ])

        if self.bot.config.ADMINS and self.service.enabled('FEATURE_CONTENT_DASHBOARD'):
            self._register_message_handlers([
                (
                    self.content_dashboard_command,
                    filters.command('content_dashboard') & filters.user(self.bot.config.ADMINS)
                )
            ])

        logger.info(f"FeatureHandler registered {len(self._handlers)} handlers")

    @staticmethod
    def _text(message: Message) -> str:
        value = getattr(message, 'text', '') or ''
        return str(value)

    @classmethod
    def _arguments(cls, message: Message) -> list[str]:
        parts = cls._text(message).split(None, 1)
        if len(parts) < 2:
            return []
        try:
            return shlex.split(parts[1])
        except ValueError:
            return [parts[1].strip()]

    @staticmethod
    def _reply_file_identifier(message: Message) -> str | None:
        reply = getattr(message, 'reply_to_message', None)
        if not reply:
            return None
        for field in ('document', 'video', 'audio', 'animation', 'photo'):
            media = getattr(reply, field, None)
            if media and getattr(media, 'file_unique_id', None):
                return media.file_unique_id
        return None

    async def _send_file_list(
        self, message: Message, title: str, file_ids: list[str]
    ) -> None:
        files_by_id = await self.bot.media_repo.find_files_batch(file_ids[:20])
        files = [
            files_by_id[file_id]
            for file_id in file_ids[:20]
            if files_by_id.get(file_id) is not None
        ]
        if not files:
            await message.reply_text(f"{title}\n\nNo available files were found.")
            return
        buttons = ButtonBuilder.file_buttons_row(files, is_private=True)
        await message.reply_text(
            f"{title}\n\n{len(files)} file(s)",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=CaptionFormatter.get_parse_mode()
        )

    @check_ban()
    @require_subscription()
    async def save_search_command(self, client: Client, message: Message):
        arguments = self._arguments(message)
        query = " ".join(arguments).strip()
        if len(query) < 2:
            return await message.reply_text("Usage: <code>/save_search movie title</code>")
        if len(query) > 100:
            return await message.reply_text("Saved searches are limited to 100 characters.")
        try:
            document, created = await self.repository.create_saved_search(
                message.from_user.id, query
            )
        except ValueError as e:
            return await message.reply_text(html.escape(str(e)))
        state = "saved" if created else "already exists"
        await message.reply_text(
            f"🔔 Search <code>{html.escape(document['query'])}</code> {state}."
        )

    @check_ban()
    @require_subscription()
    async def saved_searches_command(self, client: Client, message: Message):
        searches = await self.repository.list_saved_searches(message.from_user.id)
        if not searches:
            return await message.reply_text("You have no saved searches. Use /save_search first.")
        lines = ["🔔 <b>Saved searches</b>"]
        buttons = []
        for saved in searches:
            icon = "✅" if saved.get('active', True) else "⏸"
            lines.append(f"{icon} <code>{html.escape(saved['query'])}</code>")
            action = 'pause' if saved.get('active', True) else 'resume'
            buttons.append([
                ButtonBuilder.action_button(
                    "⏸ Pause" if action == 'pause' else "▶️ Resume",
                    callback_data=f"feature#saved_{action}#{saved['_id']}"
                ),
                ButtonBuilder.action_button(
                    "🗑 Delete", callback_data=f"feature#saved_delete#{saved['_id']}"
                ),
            ])
        await message.reply_text(
            "\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons)
        )

    async def _favorite_mutation(self, message: Message, remove: bool = False):
        arguments = self._arguments(message)
        replied_file = self._reply_file_identifier(message)
        if replied_file:
            file_id = replied_file
            collection_name = " ".join(arguments) if arguments else "Favorites"
        elif arguments:
            file_id = arguments[0]
            collection_name = " ".join(arguments[1:]) or "Favorites"
        else:
            return await message.reply_text(
                "Reply to a delivered file or use "
                "<code>/favorite file_unique_id [collection]</code>."
            )

        file = await self.bot.media_repo.find_file(file_id)
        if not file:
            return await message.reply_text("That file is no longer available.")
        if remove:
            success = await self.repository.remove_from_collection(
                message.from_user.id, file.file_unique_id, collection_name
            )
            action = "removed from"
        else:
            success = await self.repository.add_to_collection(
                message.from_user.id, file.file_unique_id, collection_name
            )
            action = "added to"
        if success:
            await message.reply_text(
                f"⭐ <code>{html.escape(file.file_name)}</code> {action} "
                f"<b>{html.escape(collection_name)}</b>."
            )
        else:
            await message.reply_text("The collection could not be updated.")

    @check_ban()
    @require_subscription()
    async def favorite_command(self, client: Client, message: Message):
        await self._favorite_mutation(message, remove=False)

    @check_ban()
    @require_subscription()
    async def unfavorite_command(self, client: Client, message: Message):
        await self._favorite_mutation(message, remove=True)

    @check_ban()
    @require_subscription()
    async def favorites_command(self, client: Client, message: Message):
        arguments = self._arguments(message)
        name = " ".join(arguments) or "Favorites"
        collection = await self.repository.get_collection(message.from_user.id, name)
        if not collection:
            return await message.reply_text(f"Collection <b>{html.escape(name)}</b> was not found.")
        await self._send_file_list(
            message,
            f"⭐ <b>{html.escape(collection['name'])}</b>",
            collection.get('file_ids', [])
        )

    @check_ban()
    @require_subscription()
    async def collections_command(self, client: Client, message: Message):
        collections = await self.repository.list_collections(message.from_user.id)
        if not collections:
            return await message.reply_text("You have no collections yet.")
        lines = ["⭐ <b>Your collections</b>"]
        for collection in collections:
            lines.append(
                f"• <code>{html.escape(collection['name'])}</code> "
                f"({len(collection.get('file_ids', []))} files)"
            )
        lines.append("\nOpen one with <code>/favorites collection name</code>.")
        await message.reply_text("\n".join(lines))

    @check_ban()
    @require_subscription()
    async def collection_create_command(self, client: Client, message: Message):
        name = " ".join(self._arguments(message)).strip()
        if not name:
            return await message.reply_text("Usage: <code>/collection_create name</code>")
        document = await self.repository.ensure_collection(message.from_user.id, name)
        await message.reply_text(
            f"Collection <b>{html.escape(document['name'])}</b> is ready."
        )

    @check_ban()
    @require_subscription()
    async def collection_delete_command(self, client: Client, message: Message):
        name = " ".join(self._arguments(message)).strip()
        if not name:
            return await message.reply_text("Usage: <code>/collection_delete name</code>")
        deleted = await self.repository.delete_collection(message.from_user.id, name)
        await message.reply_text(
            "Collection deleted." if deleted else "Collection not found."
        )

    @check_ban()
    @require_subscription()
    async def recent_command(self, client: Client, message: Message):
        file_ids = await self.repository.get_recent_files(message.from_user.id)
        await self._send_file_list(message, "🕘 <b>Recently downloaded</b>", file_ids)

    @check_ban()
    @require_subscription()
    async def clear_recent_command(self, client: Client, message: Message):
        count = await self.repository.clear_recent_files(message.from_user.id)
        await message.reply_text(f"Cleared {count} recent file entr{'y' if count == 1 else 'ies'}.")

    @check_ban()
    @require_subscription()
    async def suggest_command(self, client: Client, message: Message):
        query = " ".join(self._arguments(message)).strip()
        if not query:
            return await message.reply_text("Usage: <code>/suggest partial title</code>")
        suggestions = await self.service.autocomplete(message.from_user.id, query)
        if not suggestions:
            return await message.reply_text("No valid suggestions were found.")
        buttons = []
        for suggestion in suggestions:
            reference = await create_search_query_reference(
                self.bot.cache, suggestion, message.from_user.id
            )
            buttons.append([
                ButtonBuilder.action_button(
                    f"🔍 {suggestion[:45]}",
                    callback_data=(
                        f"search#page#{reference}#0#0#{message.from_user.id}"
                    )
                )
            ])
        await message.reply_text(
            "💡 <b>Search suggestions</b>",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    @check_ban()
    @require_subscription()
    async def search_help_command(self, client: Client, message: Message):
        await message.reply_text(
            "🔎 <b>Advanced search</b>\n\n"
            "Add filters after a title:\n"
            "<code>matrix type:video year:1999 quality:1080p</code>\n"
            "<code>show season:1 episode:4 maxsize:2GB</code>\n\n"
            "Available: <code>type, year, lang, quality, season, episode, "
            "minsize, maxsize</code>."
        )

    @check_ban()
    @require_subscription()
    async def my_requests_command(self, client: Client, message: Message):
        requests = await self.repository.list_content_requests(message.from_user.id)
        if not requests:
            return await message.reply_text("You have no tracked requests.")
        lines = ["📮 <b>Your requests</b>"]
        for request in requests:
            status = request['status']
            if status.startswith('processing:'):
                status = status.split(':', 1)[1]
            lines.append(
                f"• <code>{html.escape(request['query'])}</code> — "
                f"<b>{html.escape(status.title())}</b>"
            )
        await message.reply_text("\n".join(lines))

    @check_ban()
    @require_subscription()
    async def feature_callback(self, client: Client, query: CallbackQuery):
        parts = query.data.split('#', 3)
        if len(parts) < 3:
            return await query.answer("Invalid feature action.", show_alert=True)
        action = parts[1]
        value = parts[2]
        user_id = query.from_user.id

        if action == 'fav' and self.service.enabled('FEATURE_FAVORITES'):
            file = await self.bot.media_repo.find_file(value)
            if not file:
                return await query.answer("File is no longer available.", show_alert=True)
            await self.repository.add_to_collection(user_id, file.file_unique_id)
            return await query.answer("⭐ Added to Favorites", show_alert=True)

        if action in {'more', 'less'} and self.service.enabled('FEATURE_RECOMMENDATION_FEEDBACK'):
            file = await self.bot.media_repo.find_file(value)
            if not file:
                return await query.answer("File is no longer available.", show_alert=True)
            await self.repository.set_recommendation_feedback(user_id, file.file_unique_id, action)
            await self.bot.recommendation_service.invalidate_user_recommendations(user_id)
            text = "Show more like this" if action == 'more' else "Hidden from recommendations"
            return await query.answer(text, show_alert=True)

        if action == 'report' and self.service.enabled('FEATURE_FILE_REPORTS'):
            file = await self.bot.media_repo.find_file(value)
            display_name = file.file_name if file else value
            buttons = [
                [ButtonBuilder.action_button(
                    label,
                    callback_data=f"feature#reason_{reason}#{value}"
                )]
                for reason, label in self.REPORT_REASONS.items()
            ]
            await query.message.reply_text(
                f"Report <code>{html.escape(display_name)}</code> as:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            return await query.answer()

        if action.startswith('reason_') and self.service.enabled('FEATURE_FILE_REPORTS'):
            reason = action.removeprefix('reason_')
            if reason not in self.REPORT_REASONS:
                return await query.answer("Invalid report reason.", show_alert=True)
            _report, created = await self.repository.create_file_report(user_id, value, reason)
            text = "Report submitted." if created else "You already submitted this report."
            return await query.answer(text, show_alert=True)

        if action.startswith('saved_') and self.service.enabled('FEATURE_SAVED_SEARCH_ALERTS'):
            operation = action.removeprefix('saved_')
            if operation in {'pause', 'resume'}:
                changed = await self.repository.set_saved_search_active(
                    user_id, value, operation == 'resume'
                )
            elif operation == 'delete':
                changed = await self.repository.delete_saved_search(user_id, value)
            else:
                changed = False
            if changed:
                try:
                    await query.message.delete()
                except Exception as e:
                    logger.debug(f"Could not remove stale saved-search menu: {e}")
                return await query.answer("Saved search updated.")

        await query.answer("Feature action unavailable.", show_alert=True)

    async def file_reports_command(self, client: Client, message: Message):
        arguments = self._arguments(message)
        status = arguments[0].lower() if arguments else 'open'
        if status not in {'open', 'resolved', 'all'}:
            return await message.reply_text("Use /file_reports open, resolved, or all.")
        reports = await self.repository.list_file_reports(status=status)
        if not reports:
            return await message.reply_text("No matching file reports.")
        lines = [f"🚩 <b>{status.title()} file reports</b>"]
        for report in reports:
            lines.append(
                f"• <code>{report['_id']}</code> — {html.escape(report['reason'])} — "
                f"<code>{html.escape(report['file_unique_id'])}</code>"
            )
        lines.append("\nResolve with <code>/resolve_report report_id</code>.")
        await message.reply_text("\n".join(lines))

    async def resolve_report_command(self, client: Client, message: Message):
        arguments = self._arguments(message)
        if not arguments:
            return await message.reply_text("Usage: <code>/resolve_report report_id</code>")
        resolved = await self.repository.resolve_file_report(
            arguments[0], message.from_user.id
        )
        await message.reply_text("Report resolved." if resolved else "Open report not found.")

    async def content_dashboard_command(self, client: Client, message: Message):
        dashboard = await self.service.dashboard()
        media = dashboard.get('media', {})
        lines = [
            "📊 <b>Content dashboard</b>",
            f"Files: <b>{media.get('total_files', 0):,}</b>",
            f"Storage: <b>{format_file_size(media.get('total_size', 0))}</b>",
            f"Open reports: <b>{dashboard.get('open_reports', 0)}</b>",
            f"Pending requests: <b>{dashboard.get('pending_requests', 0)}</b>",
            f"Saved searches: <b>{dashboard.get('saved_searches', 0)}</b>",
            f"Collections: <b>{dashboard.get('collections', 0)}</b>",
        ]
        popular = dashboard.get('popular_searches', [])
        if popular:
            lines.append("\n🔥 <b>Popular:</b> " + ", ".join(
                f"<code>{html.escape(item)}</code>" for item in popular[:5]
            ))
        zero_results = dashboard.get('zero_results', [])
        if zero_results:
            lines.append("\n🔎 <b>Top zero-result searches</b>")
            for item in zero_results[:5]:
                lines.append(
                    f"• <code>{html.escape(item.get('query', item['_id']))}</code> "
                    f"({item.get('count', 0)})"
                )
        await message.reply_text("\n".join(lines))
