"""Feature-flagged orchestration for additive user/content capabilities."""

import asyncio
import html
from typing import Any

from pyrogram.types import InlineKeyboardMarkup
from pyrogram.errors import UserIsBlocked, InputUserDeactivated, PeerIdInvalid

from config.settings import settings
from core.database.errors import SearchBackendUnavailableError
from repositories.saved_search_alert_jobs import SavedSearchAlertJobRepository
from repositories.media import FileType
from core.utils.button_builder import ButtonBuilder
from core.utils.helpers import find_similar_queries
from core.utils.logger import get_logger
from core.utils.telegram_api import telegram_api
from repositories.features import (
    FeatureRepository, normalize_feature_text, ACTIVE_CONTENT_REQUEST_STATUSES,
)
from repositories.media import MediaFile

logger = get_logger(__name__)


def _analytics_query(row: dict[str, Any]) -> str:
    """The string analytics ID retains the full query; display text is capped."""
    identifier = row.get('_id')
    if isinstance(identifier, str) and identifier.strip():
        return identifier.strip()
    return str(row.get('query') or '').strip()


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
        # Created lazily, and only exercised by the explicitly opted-in queue.
        self._alert_jobs = None
        self._alert_worker_started = False

    def enabled(self, flag: str) -> bool:
        return bool(getattr(self.config, flag, False))

    def any_enabled(self) -> bool:
        return any(self.enabled(flag) for flag in self.FLAGS)

    async def initialize(self) -> dict[str, bool]:
        if not self.any_enabled():
            logger.info("All additive feature flags are disabled; feature indexes were not created")
            return {}
        results = await self.repository.create_indexes()
        if self.durable_alerts_enabled():
            await self._durable_jobs().ensure_indexes()
        return results

    def durable_alerts_enabled(self):
        return (self.enabled('FEATURE_SAVED_SEARCH_ALERTS')
                and settings.processing.durable_saved_search_alerts)

    def _durable_jobs(self):
        if self._alert_jobs is None:
            self._alert_jobs = SavedSearchAlertJobRepository(self.repository.db_pool)
        return self._alert_jobs

    async def persist_new_media(self, media: MediaFile) -> None:
        """Await queue persistence after indexing when durable mode is opted in.

        The media write and queue insert aren't in one Mongo transaction:
        indexing errors must surface for reconciliation on staging.
        """
        if not self.enabled('FEATURE_SAVED_SEARCH_ALERTS') or not self.bot:
            return
        if not self.durable_alerts_enabled():
            self.schedule_new_media(media)
            return
        await self._durable_jobs().enqueue(media)

    def start_alert_workers(self) -> None:
        """Start a fixed-size pool, not one task per incoming media file."""
        if not self.durable_alerts_enabled() or not self.bot or self._alert_worker_started:
            return
        manager = getattr(self.bot, 'handler_manager', None)
        if manager is None:
            logger.error("Durable saved-search workers require a handler manager")
            return
        self._alert_worker_started = True
        for index in range(settings.processing.saved_search_alert_workers):
            manager.create_background_task(
                self._run_alert_worker(),
                name=f"saved_alert_worker_{index}",
            )

    async def _alert_heartbeat(self, job, stop, lost):
        try:
            while not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=30)
                    break
                except asyncio.TimeoutError:
                    pass
                if not await self._durable_jobs().renew(job):
                    lost.set()
                    return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            lost.set()
            logger.exception(f"Durable saved-search lease heartbeat failed: {e}")

    async def _run_alert_worker(self):
        """Lease-fenced, bounded-concurrency worker with recoverable retries."""
        jobs = self._durable_jobs()
        while self.durable_alerts_enabled():
            try:
                job = await jobs.claim()
                if not job:
                    await asyncio.sleep(1)
                    continue
                stop, lost = asyncio.Event(), asyncio.Event()
                heartbeat = asyncio.create_task(self._alert_heartbeat(job, stop, lost))
                try:
                    await self._notify_durable_job(job, lost)
                    if lost.is_set() or not await jobs.acknowledge(job):
                        raise RuntimeError("Lost saved-search job lease before acknowledgement")
                except asyncio.CancelledError:
                    # Leave the leased job to expire and recover on another worker.
                    raise
                except Exception as exc:
                    state = await jobs.fail(job, exc)
                    logger.warning(
                        "Saved-search alert job retry state=%s error_type=%s",
                        state, type(exc).__name__,
                    )
                finally:
                    stop.set()
                    heartbeat.cancel()
                    await asyncio.gather(heartbeat, return_exceptions=True)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception(f"Saved-search alert worker unavailable: {e}")
                await asyncio.sleep(5)

    async def _notify_durable_job(self, job, lost) -> int:
        """Checkpoint only after every recipient in a page is resolved."""
        snapshot = job['media']
        media = MediaFile(
            file_unique_id=snapshot['file_unique_id'],
            file_id=snapshot['file_id'], file_ref=snapshot.get('file_ref'),
            file_name=snapshot['file_name'], file_size=snapshot['file_size'],
            file_type=FileType(snapshot['file_type']),
            mime_type=snapshot.get('mime_type'), caption=snapshot.get('caption'),
        )
        haystack = normalize_feature_text(
            f"{media.file_name or ''} {media.caption or ''}"
        )
        after_id = job.get('after_id')
        sent = 0
        while True:
            if lost.is_set():
                raise RuntimeError("Saved-search job lease lost")
            page = await self.repository.get_active_saved_search_page(
                after_id=after_id, limit=100
            )
            if not page:
                return sent
            if len(page) > 100:
                raise RuntimeError("Oversized saved-search alert page")
            last_id = after_id
            for entry in page:
                if lost.is_set():
                    raise RuntimeError("Saved-search job lease lost during delivery")
                search_id = entry['_id']
                if not isinstance(search_id, str) or (
                    last_id is not None and search_id <= last_id
                ):
                    raise RuntimeError("Saved-search cursor order invalid")
                last_id = search_id
                tokens = entry.get('normalized_query', '').split()
                if not tokens or not all(token in haystack for token in tokens):
                    continue
                user_id = int(entry['user_id'])
                if not await self.bot.user_repo.can_receive_content(user_id):
                    continue

                state, token = await self._durable_jobs().begin_delivery(
                    search_id, media.file_unique_id
                )
                if state == 'delivered':
                    continue
                if state != 'claimed':
                    # A crashed sender still owns a delivery lease. Do not
                    # checkpoint past an unresolved recipient: retry later.
                    raise RuntimeError("Saved-search recipient delivery is in flight")
                user_id = int(entry['user_id'])
                try:
                    button = ButtonBuilder.file_button(media, user_id=user_id, is_private=True)
                    await telegram_api.call_api(
                        self.bot.send_message,
                        user_id,
                        (
                            "🔔 <b>Saved search match</b>\n\n"
                            f"<b>Search:</b> <code>{html.escape(entry['query'])}</code>\n"
                            f"<b>File:</b> <code>{html.escape(media.file_name)}</code>"
                        ),
                        reply_markup=InlineKeyboardMarkup([[button]]),
                        chat_id=user_id,
                    )
                    if not await self._durable_jobs().finish_delivery(
                        search_id, media.file_unique_id, token
                    ):
                        raise RuntimeError("Saved-search delivery lease was lost")
                    sent += 1
                except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid) as error:
                    # An unreachable recipient must not poison this file's fan-out.
                    # Do not record an unsent alert as a successful delivery.
                    released = await self._durable_jobs().release_delivery(
                        search_id, media.file_unique_id, token
                    )
                    if not released:
                        raise RuntimeError("Saved-search recipient lease was lost") from error
                    logger.warning(
                        "Skipping unreachable saved-search recipient user_id=%s error_type=%s",
                        user_id, type(error).__name__,
                    )
                except Exception:
                    await self._durable_jobs().release_delivery(
                        search_id, media.file_unique_id, token
                    )
                    raise
            if lost.is_set() or not await self._durable_jobs().checkpoint(
                job, last_id
            ):
                raise RuntimeError("Lost saved-search lease at page checkpoint")
            after_id = last_id
            await asyncio.sleep(0)
            if len(page) < 100:
                return sent

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
        if type(limit) is not int or limit <= 0:
            return []
        normalized = normalize_feature_text(query)
        if not normalized:
            return []

        user_keywords, global_keywords = await asyncio.gather(
            self.search_history_service.get_most_searched_keywords(user_id, limit=50),
            self.search_history_service.get_global_top_searches(limit=100),
        )
        # Normalize before both prefix and fuzzy matching. Exact queries and
        # differently spaced/cased duplicates must not re-enter through fuzzy.
        unique_candidates = {}
        for candidate in user_keywords + global_keywords:
            if not isinstance(candidate, str):
                continue
            key = normalize_feature_text(candidate)
            if key and key != normalized:
                unique_candidates.setdefault(key, candidate)
        candidates = list(unique_candidates.values())
        prefix_matches = [
            candidate for candidate in candidates
            if normalize_feature_text(candidate).startswith(normalized)
            and normalize_feature_text(candidate) != normalized
        ]
        fuzzy = find_similar_queries(
            normalized,
            candidates,
            threshold=55.0,
            max_results=limit * 3
        )
        combined = prefix_matches + [candidate for candidate, _ in fuzzy]
        if not combined:
            return []
        # Search history can outlive media, or have been collected while
        # advanced filters were disabled. Validate against current search rules.
        checker = getattr(self.media_repo, 'has_matching_file', None)
        if not callable(checker):
            raise SearchBackendUnavailableError('Autocomplete media lookup unavailable')
        validation_slots = asyncio.Semaphore(5)

        async def valid_candidate(candidate):
            search_query = candidate
            advanced_filters = None
            file_type = None
            if self.enabled('FEATURE_ADVANCED_SEARCH'):
                from core.utils.feature_search import parse_advanced_search_query
                from core.utils.file_type import get_file_type_from_string
                try:
                    search_query, advanced_filters = parse_advanced_search_query(candidate)
                except (TypeError, ValueError):
                    return False
                if advanced_filters.get('file_type'):
                    file_type = get_file_type_from_string(str(advanced_filters['file_type']))
            async with validation_slots:
                try:
                    return bool(await checker(
                        search_query, file_type=file_type,
                        use_caption=getattr(self.config, 'USE_CAPTION_FILTER', True),
                        advanced_filters=advanced_filters,
                    ))
                except Exception as error:
                    logger.warning('Autocomplete media validation unavailable', exc_info=True)
                    raise SearchBackendUnavailableError('Autocomplete lookup failed') from error

        candidates = list(dict.fromkeys(combined))[:limit * 3]
        matches = await asyncio.gather(
            *(valid_candidate(candidate) for candidate in candidates),
            return_exceptions=True,
        )
        for match in matches:
            if isinstance(match, BaseException):
                raise match
        return [candidate for candidate, match in zip(candidates, matches) if match][:limit]

    def schedule_new_media(self, media: MediaFile) -> None:
        """Schedule alert matching without delaying or failing the indexing path."""
        if not self.enabled('FEATURE_SAVED_SEARCH_ALERTS') or not self.bot:
            return
        if self.durable_alerts_enabled():
            # External legacy synchronous callers cannot await Mongo persistence.
            # All production media indexing entrypoints use persist_new_media().
            logger.error("Sync saved-search scheduler used in durable mode; caller must await persist_new_media")
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
        except Exception as e:
            logger.error(f"Error occurred while fetching task exception: {e}")
            return
        if error:
            logger.warning(f"Saved-search notification task failed: {error}")

    async def notify_saved_search_matches(self, media: MediaFile) -> int:
        """PH-017: visit every eligible search in bounded keyset pages.

        One invocation streams pages of at most 100 docs and yields after each
        page. PH-018 will address crash-durable delivery and queue admission.
        """
        if not self.enabled('FEATURE_SAVED_SEARCH_ALERTS') or not self.bot:
            return 0

        haystack = normalize_feature_text(
            f"{media.file_name or ''} {media.caption or ''}"
        )
        page_size = 100
        after_id = None
        sent = 0
        scanned = 0
        pages = 0

        while True:
            saved_searches = await self.repository.get_active_saved_search_page(
                after_id=after_id, limit=page_size
            )
            if not saved_searches:
                break
            if len(saved_searches) > page_size:
                raise RuntimeError("Saved-search repository returned an oversized page")

            pages += 1
            for saved_search in saved_searches:
                search_id = saved_search['_id']
                if (not isinstance(search_id, str) or
                        (after_id is not None and search_id <= after_id)):
                    raise RuntimeError("Saved-search page order/cursor contract violated")
                after_id = search_id
                scanned += 1

                tokens = saved_search.get('normalized_query', '').split()
                if not tokens or not all(token in haystack for token in tokens):
                    continue

                user_id = int(saved_search['user_id'])
                if not await self.bot.user_repo.can_receive_content(user_id):
                    continue

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

            if len(saved_searches) < page_size:
                break
            await asyncio.sleep(0)

        logger.debug(
            "Saved-search matching completed: scanned=%d pages=%d sent=%d",
            scanned, pages, sent
        )
        return sent

    async def dashboard(self) -> dict[str, Any]:
        """Collect bounded dashboard data from existing and additive sources."""
        if not self.enabled('FEATURE_CONTENT_DASHBOARD'):
            return {}

        zero_results, popular, media_stats, report_count, pending_requests = await asyncio.gather(
            # Fetch a bounded surplus so stale resolved rows can be removed
            # while still returning up to ten real unmet searches.
            self.repository.top_zero_results(limit=30),
            self.search_history_service.get_global_top_searches(limit=10),
            self.media_repo.get_file_stats(),
            self.repository.count_documents('file_reports', {'status': 'open'}),
            self.repository.count_documents(
                'content_requests', {'status': {'$in': list(ACTIVE_CONTENT_REQUEST_STATUSES)}}
            ),
        )
        zero_results = await self._reconcile_zero_results(zero_results, limit=10)
        return {
            'zero_results': zero_results,
            'popular_searches': popular,
            'media': media_stats,
            'open_reports': report_count,
            'pending_requests': pending_requests,
            'saved_searches': await self.repository.count_documents('saved_searches'),
            'collections': await self.repository.count_documents('user_collections'),
        }

    async def _reconcile_zero_results(
            self, rows: list[dict[str, Any]], limit: int
    ) -> list[dict[str, Any]]:
        """Drop analytics rows whose query now matches an indexed file."""
        checker = getattr(self.media_repo, 'has_matching_file', None)
        resolver = getattr(self.repository, 'resolve_zero_result', None)
        if not checker:
            return rows[:limit]

        validation_limit = asyncio.Semaphore(5)

        async def query_has_match(row: dict[str, Any]) -> bool:
            query = _analytics_query(row)
            if not query:
                return None

            search_query = query
            advanced_filters = None
            file_type = None
            if self.enabled('FEATURE_ADVANCED_SEARCH'):
                from core.utils.feature_search import parse_advanced_search_query
                from core.utils.file_type import get_file_type_from_string

                try:
                    search_query, advanced_filters = parse_advanced_search_query(query)
                except ValueError:
                    # A historical literal query can be invalid with filters on.
                    # Keep its record for a future flag change, without listing
                    # it as a valid unmet search under the current settings.
                    return None
                if advanced_filters and advanced_filters.get('file_type'):
                    file_type = get_file_type_from_string(
                        str(advanced_filters['file_type'])
                    )

            async with validation_limit:
                return await checker(
                    search_query,
                    file_type=file_type,
                    use_caption=getattr(self.config, 'USE_CAPTION_FILTER', True),
                    advanced_filters=advanced_filters
                )

        match_results = await asyncio.gather(
            *(query_has_match(row) for row in rows),
            return_exceptions=True
        )

        unresolved = []
        resolved_rows = []
        for row, match_result in zip(rows, match_results):
            if isinstance(match_result, BaseException):
                if not isinstance(match_result, Exception):
                    raise match_result
                logger.debug(
                    "Could not validate zero-result query %s: %s",
                    row.get('query', row.get('_id')),
                    match_result
                )
                raise SearchBackendUnavailableError(
                    "Zero-result search verification unavailable"
                ) from match_result
            elif match_result is None:
                continue
            elif match_result:
                resolved_rows.append(row)
            else:
                unresolved.append(row)

        if resolver and resolved_rows:
            cleanup_results = await asyncio.gather(
                *(resolver(_analytics_query(row), observed=row) for row in resolved_rows),
                return_exceptions=True
            )
            for row, cleanup_result in zip(resolved_rows, cleanup_results):
                query = _analytics_query(row)
                if isinstance(cleanup_result, asyncio.CancelledError):
                    raise cleanup_result
                if isinstance(cleanup_result, Exception):
                    logger.debug(
                        "Could not resolve stale zero-result query %s: %s",
                        query,
                        cleanup_result
                    )

        return unresolved[:limit]
