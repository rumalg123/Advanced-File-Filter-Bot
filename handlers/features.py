"""Commands and callbacks for independently flagged additive features."""

import html
import shlex

from pyrogram import Client, filters
from pyrogram.errors import InputUserDeactivated, PeerIdInvalid, UserIsBlocked
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from core.utils.button_builder import ButtonBuilder
from core.utils.caption import CaptionFormatter
from core.utils.helpers import format_file_size
from core.utils.logger import get_logger
from core.utils.pagination import create_search_query_reference
from core.utils.telegram_api import telegram_api
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

    def _schedule_feature_cleanup(self, sent_message: Message | None) -> None:
        """Apply the configured cleanup timer to transient feature messages."""
        delete_time = int(
            getattr(getattr(self.bot, 'config', None), 'MESSAGE_DELETE_SECONDS', 0)
            or 0
        )
        if sent_message and delete_time > 0:
            self._schedule_auto_delete(sent_message, delete_time)

    @staticmethod
    def _reporter_ids(report: dict) -> list[int]:
        values = list(report.get('reporter_ids') or [])
        if report.get('user_id') is not None:
            values.append(report['user_id'])
        reporter_ids = []
        for value in values:
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
            if value not in reporter_ids:
                reporter_ids.append(value)
        return reporter_ids

    async def _send_file_list(
        self,
        message: Message,
        title: str,
        file_ids: list[str],
        collection_name: str | None = None
    ) -> None:
        files_by_id = await self.bot.media_repo.find_files_batch(file_ids[:20])
        files = [
            files_by_id[file_id]
            for file_id in file_ids[:20]
            if files_by_id.get(file_id) is not None
        ]
        if not files:
            sent_message = await message.reply_text(
                f"{title}\n\nNo available files were found."
            )
            self._schedule_feature_cleanup(sent_message)
            return
        buttons = []
        for file in files:
            row = [ButtonBuilder.file_button(file, is_private=True)]
            if collection_name:
                remove_callback = (
                    f"feature#unfavlist#{file.file_unique_id}#{collection_name}"
                )
                if len(remove_callback.encode('utf-8')) <= 64:
                    row.append(ButtonBuilder.action_button(
                        "🗑 Remove", callback_data=remove_callback
                    ))
            buttons.append(row)
        sent_message = await message.reply_text(
            f"{title}\n\n{len(files)} file(s)",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=CaptionFormatter.get_parse_mode()
        )
        self._schedule_feature_cleanup(sent_message)

    async def _send_report_log(self, client: Client, text: str) -> bool:
        log_channel = getattr(
            getattr(self.bot, 'config', None), 'LOG_CHANNEL', None
        )
        if not log_channel:
            return False
        try:
            await telegram_api.call_api(
                client.send_message,
                log_channel,
                text,
                parse_mode=CaptionFormatter.get_parse_mode(),
                chat_id=log_channel
            )
            return True
        except Exception as error:
            logger.warning(f"Could not send file-report event to LOG_CHANNEL: {error}")
            return False

    async def _log_report_submission(
        self,
        client: Client,
        report: dict,
        file,
        reporter,
        state: str
    ) -> None:
        event = (
            "New file report" if state == 'created'
            else "Additional reporter subscribed"
        )
        file_name = (
            getattr(file, 'file_name', None)
            or report.get('file_name')
            or "Unavailable file"
        )
        first_name = getattr(reporter, 'first_name', None) or "User"
        last_name = getattr(reporter, 'last_name', None) or ""
        display_name = " ".join(part for part in (first_name, last_name) if part)
        username = getattr(reporter, 'username', None)
        username_text = f"@{username}" if username else "Not set"
        reason = self.REPORT_REASONS.get(
            report.get('reason'), report.get('reason', 'Unknown')
        )
        reporter_count = len(self._reporter_ids(report))
        await self._send_report_log(
            client,
            "🚩 <b>File report</b>\n"
            f"Event: <b>{html.escape(event)}</b>\n"
            f"Report ID: <code>{html.escape(str(report.get('_id', 'unknown')))}</code>\n"
            f"File: <code>{html.escape(str(file_name))}</code>\n"
            f"File ID: <code>{html.escape(str(report.get('file_unique_id', 'unknown')))}</code>\n"
            f"Reason: <b>{html.escape(str(reason))}</b>\n"
            f"Reporter: <b>{html.escape(display_name)}</b> "
            f"(<code>{getattr(reporter, 'id', 'unknown')}</code>)\n"
            f"Username: <code>{html.escape(username_text)}</code>\n"
            f"Subscribed reporters: <b>{reporter_count}</b>"
        )

    async def _notify_reporters(
        self, client: Client, report: dict, file_name: str
    ) -> dict[str, list[int]]:
        results = {'notified': [], 'unreachable': [], 'failed': []}
        reason = self.REPORT_REASONS.get(
            report.get('reason'), report.get('reason', 'Unknown')
        )
        notification = (
            "✅ <b>Your file report was resolved</b>\n\n"
            f"File: <code>{html.escape(file_name)}</code>\n"
            f"Reason: <b>{html.escape(str(reason))}</b>\n"
            f"Report ID: <code>{html.escape(str(report.get('_id', 'unknown')))}</code>\n\n"
            "Thank you for helping us keep the file library accurate."
        )
        blocked_errors = (UserIsBlocked, InputUserDeactivated, PeerIdInvalid)

        for reporter_id in self._reporter_ids(report):
            try:
                await telegram_api.call_api(
                    client.get_chat, reporter_id, chat_id=reporter_id
                )
            except blocked_errors:
                results['unreachable'].append(reporter_id)
                continue
            except Exception as error:
                logger.warning(
                    f"Could not verify report notification recipient {reporter_id}: {error}"
                )
                results['failed'].append(reporter_id)
                continue

            try:
                await telegram_api.call_api(
                    client.send_message,
                    reporter_id,
                    notification,
                    parse_mode=CaptionFormatter.get_parse_mode(),
                    chat_id=reporter_id
                )
                results['notified'].append(reporter_id)
            except blocked_errors:
                results['unreachable'].append(reporter_id)
            except Exception as error:
                logger.error(
                    f"Failed to notify reporter {reporter_id} for "
                    f"{report.get('_id')}: {error}"
                )
                results['failed'].append(reporter_id)

        return results

    @staticmethod
    async def _remove_collection_menu_row(message: Message, callback_data: str) -> None:
        """Remove a deleted favorite from an already rendered collection menu."""
        markup = getattr(message, 'reply_markup', None)
        rows = list(getattr(markup, 'inline_keyboard', None) or [])
        if not rows:
            return
        remaining = [
            row for row in rows
            if not any(
                getattr(button, 'callback_data', None) == callback_data
                for button in row
            )
        ]
        try:
            if remaining:
                await message.edit_reply_markup(InlineKeyboardMarkup(remaining))
            else:
                await message.delete()
        except Exception as error:
            logger.debug(f"Could not refresh favorites menu after removal: {error}")

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
        sent_message = await message.reply_text(
            "\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons)
        )
        self._schedule_feature_cleanup(sent_message)

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
            collection.get('file_ids', []),
            collection_name=collection['name']
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
        sent_message = await message.reply_text(
            "💡 <b>Search suggestions</b>",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        self._schedule_feature_cleanup(sent_message)

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

        if (
            action in {'unfav', 'unfavlist'}
            and self.service.enabled('FEATURE_FAVORITES')
        ):
            collection_name = parts[3] if len(parts) == 4 else "Favorites"
            removed = await self.repository.remove_from_collection(
                user_id, value, collection_name
            )
            if removed:
                await query.answer(
                    f"Removed from {collection_name}.", show_alert=True
                )
                if action == 'unfavlist' and query.message:
                    await self._remove_collection_menu_row(query.message, query.data)
                return
            return await query.answer(
                f"File is not in {collection_name}.", show_alert=True
            )

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
            await query.answer()
            menu = await query.message.reply_text(
                f"Report <code>{html.escape(display_name)}</code> as:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            self._schedule_feature_cleanup(menu)
            return

        if action.startswith('reason_') and self.service.enabled('FEATURE_FILE_REPORTS'):
            reason = action.removeprefix('reason_')
            if reason not in self.REPORT_REASONS:
                return await query.answer("Invalid report reason.", show_alert=True)
            file = await self.bot.media_repo.find_file(value)
            report, state = await self.repository.create_file_report(
                user_id,
                value,
                reason,
                file.file_name if file else None
            )
            if state == 'created':
                text = "Report submitted."
            elif state == 'subscribed':
                text = (
                    "This issue is already reported. You will be notified when "
                    "it is resolved."
                )
            else:
                text = (
                    "You already reported this issue. You will be notified when "
                    "it is resolved."
                )
            await query.answer(text, show_alert=True)
            if query.message:
                try:
                    await query.message.delete()
                except Exception as error:
                    logger.debug(f"Could not remove selected report menu: {error}")
            if state != 'duplicate':
                await self._log_report_submission(
                    client, report, file, query.from_user, state
                )
            return

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
        file_ids = list({
            report.get('file_unique_id') for report in reports
            if report.get('file_unique_id')
        })
        try:
            files_by_id = await self.bot.media_repo.find_files_batch(file_ids)
        except Exception as error:
            logger.warning(f"Could not resolve report filenames in batch: {error}")
            files_by_id = {}
        lines = [f"🚩 <b>{status.title()} file reports</b>"]
        for report in reports:
            file = files_by_id.get(report.get('file_unique_id'))
            file_name = (
                report.get('file_name')
                or getattr(file, 'file_name', None)
                or "Unavailable file"
            )
            reason = self.REPORT_REASONS.get(
                report.get('reason'), report.get('reason', 'Unknown')
            )
            entry = (
                f"\n• <code>{html.escape(str(report['_id']))}</code>\n"
                f"  File: <code>{html.escape(str(file_name)[:100])}</code>\n"
                f"  File ID: <code>{html.escape(str(report.get('file_unique_id', 'unknown')))}</code>\n"
                f"  Reason: <b>{html.escape(str(reason))}</b>\n"
                f"  Status: <b>{html.escape(str(report.get('status', 'unknown')).title())}</b>\n"
                f"  Reporters: <b>{len(self._reporter_ids(report))}</b>"
            )
            if len("\n".join(lines)) + len(entry) > 3800:
                lines.append("\n… More reports are available; narrow the status filter.")
                break
            lines.append(entry)
        lines.append("\nResolve with <code>/resolve_report report_id</code>.")
        await message.reply_text("\n".join(lines))

    async def resolve_report_command(self, client: Client, message: Message):
        arguments = self._arguments(message)
        if not arguments:
            return await message.reply_text("Usage: <code>/resolve_report report_id</code>")
        report = await self.repository.resolve_file_report(
            arguments[0], message.from_user.id
        )
        if not report:
            return await message.reply_text("Open report not found.")

        file = await self.bot.media_repo.find_file(report['file_unique_id'])
        file_name = (
            report.get('file_name')
            or getattr(file, 'file_name', None)
            or "Unavailable file"
        )
        notification_results = await self._notify_reporters(
            client, report, file_name
        )
        record_results = getattr(
            self.repository, 'record_report_notification_results', None
        )
        if record_results:
            try:
                await record_results(
                    report['_id'],
                    notification_results['notified'],
                    notification_results['unreachable'],
                    notification_results['failed']
                )
            except Exception as error:
                logger.error(
                    f"Could not persist notification results for {report['_id']}: {error}"
                )

        reason = self.REPORT_REASONS.get(
            report.get('reason'), report.get('reason', 'Unknown')
        )
        await self._send_report_log(
            client,
            "✅ <b>File report resolved</b>\n"
            f"Report ID: <code>{html.escape(str(report['_id']))}</code>\n"
            f"File: <code>{html.escape(str(file_name))}</code>\n"
            f"File ID: <code>{html.escape(str(report['file_unique_id']))}</code>\n"
            f"Reason: <b>{html.escape(str(reason))}</b>\n"
            f"Resolved by: <code>{message.from_user.id}</code>\n"
            f"Notified: <b>{len(notification_results['notified'])}</b>\n"
            f"Unreachable: <b>{len(notification_results['unreachable'])}</b>\n"
            f"Failed: <b>{len(notification_results['failed'])}</b>"
        )
        await message.reply_text(
            "Report resolved. "
            f"Notified {len(notification_results['notified'])}; "
            f"unreachable {len(notification_results['unreachable'])}; "
            f"failed {len(notification_results['failed'])}."
        )

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
