from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from core.cache.config import CacheKeyGenerator, CacheTTLConfig
from core.services.recommendation import RecommendationService
from core.services.search_results import SearchResultsService
from core.utils.button_builder import ButtonBuilder
from core.utils.helpers import find_similar_queries
from core.utils.pagination import resolve_search_query_reference
from handlers.callbacks_handlers.file import FileCallbackHandler
from handlers.callbacks_handlers.user import UserCallbackHandler
from handlers.commands_handlers.user import UserCommandHandler
from handlers.filter import FilterHandler
from handlers.search import SearchHandler
from repositories.media import FileType, MediaFile


class SortedMemoryCache:
    def __init__(self):
        self.values = {}
        self.sorted_sets = {}
        self.deleted = []
        self.expirations = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, expire=None):
        self.values[key] = value
        if expire:
            self.expirations[key] = expire
        return True

    async def delete(self, key):
        self.deleted.append(key)
        self.values.pop(key, None)
        return True

    async def expire(self, key, ttl):
        self.expirations[key] = ttl
        return True

    async def zincrby(self, key, amount, member):
        values = self.sorted_sets.setdefault(key, {})
        values[member] = values.get(member, 0.0) + amount
        return values[member]

    async def zrevrange(self, key, start, end, with_scores=False):
        values = sorted(
            self.sorted_sets.get(key, {}).items(),
            key=lambda item: item[1],
            reverse=True
        )
        stop = None if end == -1 else end + 1
        selected = values[start:stop]
        return selected if with_scores else [member for member, _ in selected]


def make_file(file_unique_id="file-1", name="Movie.mkv"):
    return MediaFile(
        file_unique_id=file_unique_id,
        file_id=f"telegram-{file_unique_id}",
        file_ref=None,
        file_name=name,
        file_size=1024,
        file_type=FileType.VIDEO,
        mime_type="video/x-matroska",
        caption=None
    )


def test_similar_queries_exclude_exact_normalized_candidate():
    matches = find_similar_queries(
        "  The Matrix ",
        ["the matrix", "The Matrx", "unrelated"],
        threshold=60,
        max_results=3
    )

    assert matches
    assert all(match.lower().strip() != "the matrix" for match, _ in matches)


def test_file_buttons_carry_immutable_search_reference_with_legacy_compatibility():
    file = make_file("AgAD012345678901234567890")

    private = ButtonBuilder.file_button(file, query_reference="@deadbeef")
    assert private.callback_data.endswith("#@deadbeef")
    assert len(private.callback_data.encode("utf-8")) <= 64
    assert FileCallbackHandler.parse_file_callback(private.callback_data, 42) == (
        file.file_unique_id, 42, "@deadbeef"
    )

    group = ButtonBuilder.file_button(
        file,
        user_id=42,
        is_private=False,
        query_reference="@deadbeef"
    )
    assert FileCallbackHandler.parse_file_callback(group.callback_data, 42) == (
        file.file_unique_id, 42, "@deadbeef"
    )
    assert FileCallbackHandler.parse_file_callback("file#legacy-id", 42) == (
        "legacy-id", 42, None
    )


@pytest.mark.asyncio
async def test_search_reference_resolves_origin_instead_of_mutable_last_search():
    cache = SortedMemoryCache()
    cache.values[CacheKeyGenerator.search_session(42, "deadbeef")] = {
        "query": "originating search",
        "user_id": 42
    }
    cache.values[CacheKeyGenerator.user_last_search(42)] = {
        "query": "newer search"
    }

    resolved = await resolve_search_query_reference(cache, "@deadbeef", 42)

    assert resolved == "originating search"


@pytest.mark.asyncio
async def test_click_profile_is_recorded_and_recommendations_are_invalidated():
    cache = SortedMemoryCache()
    service = RecommendationService(cache)

    await service.track_file_click(7, "The Matrix", "file-1")

    assert cache.sorted_sets[CacheKeyGenerator.query_files_mapping("the matrix")]["file-1"] == 1.0
    assert cache.sorted_sets[CacheKeyGenerator.user_file_interactions(7)]["file-1"] == 1.0
    assert CacheKeyGenerator.user_recommendations_cache(7) in cache.deleted

    await service.track_file_click(7, "", "file-2")
    assert cache.sorted_sets[CacheKeyGenerator.user_file_interactions(7)]["file-2"] == 1.0
    assert "file-2" not in cache.sorted_sets[CacheKeyGenerator.query_files_mapping("the matrix")]


@pytest.mark.asyncio
async def test_successful_search_sequence_is_persisted_and_time_bounded():
    cache = SortedMemoryCache()
    service = RecommendationService(cache)

    await service.track_successful_search(9, "Matrix")
    await service.track_successful_search(9, "John Wick")

    last_key = CacheKeyGenerator.user_last_search(9)
    assert cache.values[last_key] == {"query": "john wick"}
    assert cache.expirations[last_key] == CacheTTLConfig.USER_LAST_SEARCH
    assert cache.sorted_sets[CacheKeyGenerator.query_cooccurrence("matrix")]["john wick"] == 1.0
    assert cache.sorted_sets[CacheKeyGenerator.query_cooccurrence("john wick")]["matrix"] == 1.0


@pytest.mark.asyncio
async def test_personalized_ranking_consumes_file_interaction_profile():
    cache = SortedMemoryCache()
    cache.sorted_sets[CacheKeyGenerator.user_file_interactions(11)] = {"watched": 3.0}
    cache.sorted_sets[CacheKeyGenerator.file_cooccurrence("watched")] = {
        "related": 4.0,
        "watched": 1.0
    }
    service = RecommendationService(cache)

    recommendations = await service.get_recommendations_for_user(11)

    assert recommendations["based_on_history"] == ["related"]
    assert "watched" not in recommendations["based_on_history"]


@pytest.mark.asyncio
async def test_file_only_post_search_recommendations_are_rendered():
    cache = SortedMemoryCache()
    file = make_file("recommended")
    media_repo = SimpleNamespace(
        find_files_batch=AsyncMock(return_value={"recommended": file})
    )
    sent_message = SimpleNamespace()
    message = SimpleNamespace(reply_text=AsyncMock(return_value=sent_message))
    cleanup = Mock()
    service = SearchResultsService(
        cache,
        SimpleNamespace(MESSAGE_DELETE_SECONDS=25),
        media_repo=media_repo
    )

    await service._send_recommendations(
        None,
        message,
        "matrix",
        ["recommended"],
        [],
        5,
        "@deadbeef",
        cleanup
    )

    message.reply_text.assert_awaited_once()
    markup = message.reply_text.await_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data.endswith("#@deadbeef")
    cleanup.assert_called_once_with(sent_message, 25)


@pytest.mark.asyncio
async def test_refresh_callback_forces_recommendation_recomputation():
    recommendation_service = SimpleNamespace(
        invalidate_user_recommendations=AsyncMock()
    )
    handler = object.__new__(UserCallbackHandler)
    handler.bot = SimpleNamespace(recommendation_service=recommendation_service)
    callback_message = SimpleNamespace(
        chat=SimpleNamespace(id=5),
        reply_text=AsyncMock(),
        reply=AsyncMock(),
        id=10,
        date=None
    )
    query = SimpleNamespace(
        from_user=SimpleNamespace(id=5),
        message=callback_message,
        answer=AsyncMock()
    )

    with patch.object(UserCommandHandler, "recommendations_command", new=AsyncMock()) as command:
        await UserCallbackHandler.handle_refresh_recommendations_callback.__wrapped__(
            handler, None, query
        )

    recommendation_service.invalidate_user_recommendations.assert_awaited_once_with(5)
    command.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_private_search_is_not_added_to_keyword_history():
    search_history = SimpleNamespace(
        track_search=AsyncMock(),
        find_similar_queries=AsyncMock(return_value=[])
    )
    recommendation_service = SimpleNamespace(track_successful_search=AsyncMock())
    bot = SimpleNamespace(
        config=SimpleNamespace(
            MAX_BTN_SIZE=10,
            DISABLE_FILTER=True,
            SUPPORT_GROUP_URL=None,
            SUPPORT_GROUP_NAME=None,
            NO_RESULTS_MESSAGE="No results for {query}"
        ),
        file_service=SimpleNamespace(
            search_files_with_access_check=AsyncMock(
                return_value=([], None, 0, True, None)
            )
        )
    )
    handler = object.__new__(SearchHandler)
    handler.bot = bot
    handler.search_history_service = search_history
    handler.recommendation_service = recommendation_service
    handler.search_results_service = SimpleNamespace(send_results=AsyncMock())
    handler._schedule_auto_delete = lambda *_: None
    message = SimpleNamespace(reply_text=AsyncMock())

    await handler._handle_private_search(None, message, "misspelled title", 17)

    search_history.track_search.assert_not_awaited()
    recommendation_service.track_successful_search.assert_not_awaited()


@pytest.mark.asyncio
async def test_near_duplicate_filter_is_shown_and_blocked():
    filter_service = SimpleNamespace(
        get_active_group_id=AsyncMock(return_value=(-1001, "Test Group")),
        get_all_filters=AsyncMock(return_value=["matrix"]),
        add_filter=AsyncMock()
    )
    handler = object.__new__(FilterHandler)
    handler.filter_service = filter_service
    handler._check_admin_rights = AsyncMock(return_value=True)
    handler._extract_filter_data = AsyncMock()
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1),
        text=SimpleNamespace(html='/add "matrixx" response'),
        reply_text=AsyncMock(),
        reply=AsyncMock()
    )

    await handler.add_filter_command(None, message)

    filter_service.add_filter.assert_not_awaited()
    handler._extract_filter_data.assert_not_awaited()
    warning = message.reply_text.await_args.args[0]
    assert "blocked automatically" in warning
