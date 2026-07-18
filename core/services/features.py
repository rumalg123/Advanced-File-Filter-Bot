"""Feature-flagged orchestration for additive user/content capabilities."""

import asyncio
import html
from typing import Any

from pyrogram.types import InlineKeyboardMarkup

from core.utils.button_builder import ButtonBuilder
from core.utils.helpers import find_similar_queries
from core.utils.logger import get_logger
from core.utils.telegram_api import telegram_api
from repositories.features import FeatureRepository, normalize_feature_text
from repositories.media import MediaFile

logger = get_logger(__name__)


class FeatureService:
    """Safe façade that keeps every optional feature behind its rollout flag."""

    FLAGS = (
        'FEATURE_SAVED_SEARCH_ALERTS',
        'FEATURE_FAVORITES',
        'FEATURE_ADVANCED_SEARCH',
        'FEATURE_RECOMMENDATION_FEEDBACK',
        'FEATURE_FILE_REPORTS',
        'FEATURE_SEARCH_AUTOCOMPLETE',
        'FEATURE_DUPLICATE_GROUPING',
        'FEATURE_REQUEST_TRACKING',
        'FEATURE_RECENT_FILES',
        'FEATURE_RECOMMENDATION_EXPLANATIONS',
        'FEATURE_CONTENT_DASHBOARD',
    )

    def __init__(
        self,
        repository: FeatureRepository,
        media_repo,
        search_history_service,
        config,
        bot=None
    ):
        self.repository = repository
        self.media_repo = media_repo
        self.search_history_service = search_history_service
        self.config = config
        self.bot = bot

    def enabled(self, flag: str) -> bool:
        return bool(getattr(self.config, flag, False))

    def any_enabled(self) -> bool:
        return any(self.enabled(flag) for flag in self.FLAGS)

    async def initialize(self) -> dict[str, bool]:
        if not self.any_enabled():
            logger.info("All additive feature flags are disabled; feature indexes were not created")
            return {}
        return await self.repository.create_indexes()

    async def record_recent_file(self, user_id: int, file_unique_id: str) -> None:
        if not self.enabled('FEATURE_RECENT_FILES'):
            return
        try:
            await self.repository.record_recent_file(user_id, file_unique_id)
        except Exception as e:
            # Successful file delivery must never be converted into a failure.
            logger.warning(f"Could not record recent file for user {user_id}: {e}")

    async def autocomplete(self, user_id: int, query: str, limit: int = 8) -> list[str]:
        if not self.enabled('FEATURE_SEARCH_AUTOCOMPLETE'):
            return []
        normalized = normalize_feature_text(query)
        if not normalized:
            return []

        user_keywords, global_keywords = await asyncio.gather(
            self.search_history_service.get_most_searched_keywords(user_id, limit=50),
            self.search_history_service.get_global_top_searches(limit=100),
        )
        candidates = list(dict.fromkeys(user_keywords + global_keywords))
        prefix_matches = [
            candidate for candidate in candidates
            if normalize_feature_text(candidate).startswith(normalized)
            and normalize_feature_text(candidate) != normalized
        ]
        if len(prefix_matches) >= limit:
            return prefix_matches[:limit]

        fuzzy = find_similar_queries(
            normalized,
            candidates,
            threshold=55.0,
            max_results=limit
        )
        combined = prefix_matches + [candidate for candidate, _ in fuzzy]
        return list(dict.fromkeys(combined))[:limit]

    def schedule_new_media(self, media: MediaFile) -> None:
        """Schedule alert matching without delaying or failing the indexing path."""
        if not self.enabled('FEATURE_SAVED_SEARCH_ALERTS') or not self.bot:
            return
        coroutine = self.notify_saved_search_matches(media)
        manager = getattr(self.bot, 'handler_manager', None)
        if manager:
            manager.create_background_task(coroutine)
        else:
            task = asyncio.create_task(coroutine)
            task.add_done_callback(self._log_task_error)

    @staticmethod
    def _log_task_error(task) -> None:
        if task.cancelled():
            return
        try:
            error = task.exception()
        except Exception:
            return
        if error:
            logger.warning(f"Saved-search notification task failed: {error}")

    async def notify_saved_search_matches(self, media: MediaFile) -> int:
        if not self.enabled('FEATURE_SAVED_SEARCH_ALERTS') or not self.bot:
            return 0

        haystack = normalize_feature_text(
            f"{media.file_name or ''} {media.caption or ''}"
        )
        saved_searches = await self.repository.get_active_saved_searches(limit=500)
        sent = 0
        for saved_search in saved_searches:
            tokens = saved_search.get('normalized_query', '').split()
            if not tokens or not all(token in haystack for token in tokens):
                continue

            search_id = saved_search['_id']
            claimed = await self.repository.claim_saved_search_notification(
                search_id, media.file_unique_id
            )
            if not claimed:
                continue

            user_id = int(saved_search['user_id'])
            try:
                button = ButtonBuilder.file_button(media, user_id=user_id, is_private=True)
                await telegram_api.call_api(
                    self.bot.send_message,
                    user_id,
                    (
                        "🔔 <b>Saved search match</b>\n\n"
                        f"<b>Search:</b> <code>{html.escape(saved_search['query'])}</code>\n"
                        f"<b>File:</b> <code>{html.escape(media.file_name)}</code>"
                    ),
                    reply_markup=InlineKeyboardMarkup([[button]]),
                    chat_id=user_id
                )
                sent += 1
            except Exception as e:
                logger.debug(f"Could not notify saved search {search_id}: {e}")
                await self.repository.release_saved_search_notification(
                    search_id, media.file_unique_id
                )
        return sent

    async def dashboard(self) -> dict[str, Any]:
        """Collect bounded dashboard data from existing and additive sources."""
        if not self.enabled('FEATURE_CONTENT_DASHBOARD'):
            return {}

        zero_results, popular, media_stats, report_count, pending_requests = await asyncio.gather(
            self.repository.top_zero_results(limit=10),
            self.search_history_service.get_global_top_searches(limit=10),
            self.media_repo.get_file_stats(),
            self.repository.count_documents('file_reports', {'status': 'open'}),
            self.repository.count_documents('content_requests', {'status': 'pending'}),
        )
        return {
            'zero_results': zero_results,
            'popular_searches': popular,
            'media': media_stats,
            'open_reports': report_count,
            'pending_requests': pending_requests,
            'saved_searches': await self.repository.count_documents('saved_searches'),
            'collections': await self.repository.count_documents('user_collections'),
        }
