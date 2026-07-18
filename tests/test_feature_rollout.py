from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from config.settings import FeatureConfig
from core.cache.config import CacheKeyGenerator
from core.services.bot_settings import BotSettingsService
from core.services.features import FeatureService
from core.services.file_access import FileAccessService
from core.services.recommendation import RecommendationService
from core.services.search_results import SearchResultsService
from core.utils.feature_search import (
    group_media_variants,
    parse_advanced_search_query,
)
from handlers.callbacks_handlers.file import FileCallbackHandler
from handlers.callbacks_handlers.pagination import PaginationCallbackHandler
from handlers.features import FeatureHandler
from repositories.features import FeatureRepository
from repositories.media import FileType, MediaFile, MediaRepository

FEATURE_FLAGS = FeatureService.FLAGS


def feature_config(*enabled):
    values = dict.fromkeys(FEATURE_FLAGS, False)
    values.update(dict.fromkeys(enabled, True))
    return SimpleNamespace(**values)


def make_file(identifier="file-1", name="Movie.2025.1080p.x265.mkv"):
    return MediaFile(
        file_unique_id=identifier,
        file_id=f"telegram-{identifier}",
        file_ref=None,
        file_name=name,
        file_size=1024,
        file_type=FileType.VIDEO,
        mime_type="video/x-matroska",
        caption=None,
        resolution="1080p"
    )


class SortedCache:
    def __init__(self):
        self.values = {}
        self.sorted_sets = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, expire=None):
        self.values[key] = value
        return True

    async def delete(self, key):
        self.values.pop(key, None)
        return True

    async def zrevrange(self, key, start, end, with_scores=False):
        values = sorted(
            self.sorted_sets.get(key, {}).items(),
            key=lambda item: item[1],
            reverse=True
        )
        stop = None if end == -1 else end + 1
        selected = values[start:stop]
        return selected if with_scores else [item[0] for item in selected]


def test_all_new_feature_flags_default_off_and_are_database_configurable():
    config = FeatureConfig()
    for flag in FEATURE_FLAGS:
        assert getattr(config, flag.lower()) is False
        assert BotSettingsService.SETTINGS_METADATA[flag]["default"] is False


@pytest.mark.asyncio
async def test_disabled_feature_service_is_inert():
    repository = SimpleNamespace(
        create_indexes=AsyncMock(),
        record_recent_file=AsyncMock()
    )
    history = SimpleNamespace(
        get_most_searched_keywords=AsyncMock(),
        get_global_top_searches=AsyncMock()
    )
    service = FeatureService(
        repository,
        SimpleNamespace(),
        history,
        feature_config()
    )

    assert await service.initialize() == {}
    await service.record_recent_file(1, "file")
    assert await service.autocomplete(1, "matrix") == []
    assert await service.dashboard() == {}

    repository.create_indexes.assert_not_awaited()
    repository.record_recent_file.assert_not_awaited()
    history.get_most_searched_keywords.assert_not_awaited()

    bot = SimpleNamespace(
        feature_service=service,
        feature_repo=repository,
        config=SimpleNamespace(ADMINS=[])
    )
    handler = FeatureHandler(bot)
    assert handler._handlers == []


def test_enabled_feature_handler_registers_only_additive_routes():
    config = feature_config(*FEATURE_FLAGS)
    config.ADMINS = [1]
    manager = SimpleNamespace(add_handler=Mock())
    service = SimpleNamespace(enabled=lambda flag: flag in FEATURE_FLAGS)
    bot = SimpleNamespace(
        feature_service=service,
        feature_repo=SimpleNamespace(),
        config=config,
        handler_manager=manager
    )

    handler = FeatureHandler(bot)

    assert len(handler._handlers) == 17
    assert manager.add_handler.call_count == 17


def test_advanced_search_parser_validates_and_extracts_all_filters():
    query, filters = parse_advanced_search_query(
        "The Matrix type:video year:1999 lang:English quality:1080p "
        "season:1 episode:4 minsize:700MB maxsize:2GB"
    )

    assert query == "The Matrix"
    assert filters == {
        'file_type': 'video',
        'year': 1999,
        'language': 'english',
        'resolution': '1080p',
        'season': '01',
        'episode': '04',
        'min_size': 700 * 1024 ** 2,
        'max_size': 2 * 1024 ** 3,
    }

    with pytest.raises(ValueError, match="minsize"):
        parse_advanced_search_query("movie minsize:3GB maxsize:2GB")


@pytest.mark.asyncio
async def test_advanced_search_flag_preserves_legacy_path_and_enables_filters():
    media_repo = SimpleNamespace(search_files=AsyncMock(return_value=([], 0, 0)))
    rate_limiter = SimpleNamespace(check_rate_limit=AsyncMock(return_value=(True, 0)))
    user_repo = SimpleNamespace(can_retrieve_file=AsyncMock(return_value=(True, None)))

    disabled = FileAccessService(
        user_repo, media_repo, SimpleNamespace(), rate_limiter,
        SimpleNamespace(USE_CAPTION_FILTER=True, FEATURE_ADVANCED_SEARCH=False)
    )
    await disabled.search_files_with_access_check(1, "matrix type:video", 1)
    assert media_repo.search_files.await_args.args[0] == "matrix type:video"
    assert media_repo.search_files.await_args.kwargs['advanced_filters'] is None

    media_repo.search_files.reset_mock()
    enabled = FileAccessService(
        user_repo, media_repo, SimpleNamespace(), rate_limiter,
        SimpleNamespace(USE_CAPTION_FILTER=True, FEATURE_ADVANCED_SEARCH=True)
    )
    await enabled.search_files_with_access_check(
        1, "matrix type:video maxsize:2GB", 1
    )
    assert media_repo.search_files.await_args.args[0] == "matrix"
    assert media_repo.search_files.await_args.kwargs['advanced_filters']['max_size'] == 2 * 1024 ** 3


def test_advanced_mongo_filter_and_variant_grouping_keep_every_file():
    repository = object.__new__(MediaRepository)
    mongo_filter = repository._build_search_filter(
        "matrix",
        FileType.VIDEO,
        True,
        {'year': 1999, 'resolution': '1080p', 'max_size': 2 * 1024 ** 3}
    )
    assert '$and' in mongo_filter
    assert {'file_size': {'$lte': 2 * 1024 ** 3}} in mongo_filter['$and']

    files = [
        make_file("720", "Movie.2025.720p.x264.mkv"),
        make_file("1080", "Movie.2025.1080p.x265.mkv"),
        make_file("other", "Different.Movie.2025.1080p.mkv"),
    ]
    groups = group_media_variants(files)
    assert [file.file_unique_id for _, group in groups for file in group] == [
        "720", "1080", "other"
    ]
    assert len(groups[0][1]) == 2

    service = SearchResultsService(
        SimpleNamespace(),
        SimpleNamespace(FEATURE_DUPLICATE_GROUPING=True)
    )
    buttons = service._build_buttons(
        files,
        "search-key",
        7,
        True,
        SimpleNamespace(build_pagination_buttons=lambda: []),
        3,
        10,
        "@deadbeef"
    )
    callbacks = [button.callback_data for row in buttons for button in row]
    assert len([value for value in callbacks if value.startswith('file#')]) == 3
    assert 'noop' in callbacks


@pytest.mark.asyncio
async def test_variant_grouping_survives_forward_and_back_pagination():
    page_two_files = [
        make_file("p2-540", "Glory.E25.AMZN.540p.mkv"),
        make_file("p2-720", "Glory.E25.AMZN.720p.mkv"),
        make_file("p2-1080", "Glory.E25.AMZN.1080p.mkv"),
    ]
    page_one_files = [
        make_file("p1-540", "Glory.E24.AMZN.540p.mkv"),
        make_file("p1-720", "Glory.E24.AMZN.720p.mkv"),
        make_file("p1-1080", "Glory.E24.AMZN.1080p.mkv"),
    ]
    search = AsyncMock(side_effect=[
        (page_two_files, 20, 30, True, None),
        (page_one_files, 10, 30, True, None),
    ])
    bot = SimpleNamespace(
        cache=SortedCache(),
        config=SimpleNamespace(
            MAX_BTN_SIZE=10,
            FEATURE_DUPLICATE_GROUPING=True
        ),
        file_service=SimpleNamespace(search_files_with_access_check=search),
        user_repo=SimpleNamespace()
    )
    message = SimpleNamespace(photo=None, edit_text=AsyncMock())
    query = SimpleNamespace(
        data="search#next#glory#10#30#7",
        from_user=SimpleNamespace(id=7),
        message=message,
        answer=AsyncMock()
    )
    handler = PaginationCallbackHandler(bot)

    with patch("handlers.callbacks_handlers.pagination.is_private_chat", return_value=True):
        await handler.handle_search_pagination(None, query)
        query.data = "search#prev#glory#0#30#7"
        await handler.handle_search_pagination(None, query)

    markups = [
        call.kwargs["reply_markup"]
        for call in message.edit_text.await_args_list
    ]
    for markup in markups:
        buttons = [button for row in markup.inline_keyboard for button in row]
        assert any("(3 variants)" in button.text for button in buttons)
        assert len([
            button for button in buttons
            if button.callback_data and button.callback_data.startswith("file#")
        ]) == 3

    assert query.answer.await_count == 2


@pytest.mark.asyncio
async def test_autocomplete_uses_only_non_exact_successful_candidates():
    history = SimpleNamespace(
        get_most_searched_keywords=AsyncMock(return_value=["matrix", "matrix reload"]),
        get_global_top_searches=AsyncMock(return_value=["matrix revolutions"])
    )
    service = FeatureService(
        SimpleNamespace(),
        SimpleNamespace(),
        history,
        feature_config('FEATURE_SEARCH_AUTOCOMPLETE')
    )

    suggestions = await service.autocomplete(1, "matrix")

    assert "matrix" not in suggestions
    assert suggestions[:2] == ["matrix reload", "matrix revolutions"]


@pytest.mark.asyncio
async def test_saved_search_alerts_are_flagged_matched_and_deduplicated():
    media = make_file(name="The.Matrix.1999.1080p.mkv")
    repository = SimpleNamespace(
        get_active_saved_searches=AsyncMock(return_value=[{
            '_id': 'search1',
            'user_id': 7,
            'query': 'The Matrix',
            'normalized_query': 'the matrix'
        }]),
        claim_saved_search_notification=AsyncMock(return_value=True),
        release_saved_search_notification=AsyncMock()
    )
    bot = SimpleNamespace(send_message=AsyncMock())
    service = FeatureService(
        repository,
        SimpleNamespace(),
        SimpleNamespace(),
        feature_config('FEATURE_SAVED_SEARCH_ALERTS'),
        bot=bot
    )

    with patch(
        'core.services.features.telegram_api.call_api',
        new=AsyncMock(return_value=SimpleNamespace())
    ) as call_api:
        assert await service.notify_saved_search_matches(media) == 1

    repository.claim_saved_search_notification.assert_awaited_once_with(
        'search1', media.file_unique_id
    )
    call_api.assert_awaited_once()

    repository.claim_saved_search_notification.return_value = False
    with patch('core.services.features.telegram_api.call_api', new=AsyncMock()) as call_api:
        assert await service.notify_saved_search_matches(media) == 0
    call_api.assert_not_awaited()


@pytest.mark.asyncio
async def test_recent_history_is_fail_open_and_only_written_when_enabled():
    repository = SimpleNamespace(record_recent_file=AsyncMock())
    disabled = FeatureService(
        repository, SimpleNamespace(), SimpleNamespace(), feature_config()
    )
    await disabled.record_recent_file(1, "file")
    repository.record_recent_file.assert_not_awaited()

    enabled = FeatureService(
        repository,
        SimpleNamespace(),
        SimpleNamespace(),
        feature_config('FEATURE_RECENT_FILES')
    )
    await enabled.record_recent_file(1, "file")
    repository.record_recent_file.assert_awaited_once_with(1, "file")

    repository.record_recent_file.side_effect = RuntimeError("database unavailable")
    await enabled.record_recent_file(1, "another")


@pytest.mark.asyncio
async def test_feedback_changes_ranking_and_explanations_without_showing_hidden_files():
    cache = SortedCache()
    cache.sorted_sets[CacheKeyGenerator.file_cooccurrence("liked")] = {
        "related": 2.0,
        "hidden": 1.0,
    }
    feature_repository = SimpleNamespace(
        get_recommendation_feedback=AsyncMock(return_value={
            'more': ['liked'],
            'less': ['hidden'],
        })
    )
    feature_service = SimpleNamespace(
        repository=feature_repository,
        enabled=lambda flag: flag in {
            'FEATURE_RECOMMENDATION_FEEDBACK',
            'FEATURE_RECOMMENDATION_EXPLANATIONS'
        }
    )
    service = RecommendationService(cache)
    service.feature_service = feature_service

    recommendations = await service.get_recommendations_for_user(5)

    assert recommendations['based_on_history'] == ['related']
    assert 'hidden' not in recommendations['based_on_history']
    assert recommendations['reasons']['related'].startswith('Related to')


def test_delivery_action_buttons_are_off_by_default_and_callback_safe_when_enabled():
    handler = object.__new__(FileCallbackHandler)
    handler.bot = SimpleNamespace(config=feature_config())
    assert handler._feature_file_markup(make_file()) is None

    config = feature_config(
        'FEATURE_FAVORITES',
        'FEATURE_RECOMMENDATION_FEEDBACK',
        'FEATURE_FILE_REPORTS'
    )
    handler.bot = SimpleNamespace(config=config)
    markup = handler._feature_file_markup(make_file("AgAD012345678901234567890"))
    callbacks = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
    ]
    assert {callback.split('#')[1] for callback in callbacks} == {
        'fav', 'more', 'less', 'report'
    }
    assert all(len(callback.encode()) <= 64 for callback in callbacks)

    # Oversized optional callbacks are omitted so they can never break delivery.
    oversized = make_file("x" * 60)
    assert handler._feature_file_markup(oversized) is None
    assert handler._broken_file_report_markup(oversized) is None


@pytest.mark.asyncio
async def test_feature_callbacks_mutate_only_the_clicking_users_data():
    file = make_file()
    repository = SimpleNamespace(
        add_to_collection=AsyncMock(return_value=True),
        set_recommendation_feedback=AsyncMock(return_value=True),
        create_file_report=AsyncMock(return_value=({'_id': 'report'}, True))
    )
    service = SimpleNamespace(
        enabled=lambda flag: flag in {
            'FEATURE_FAVORITES',
            'FEATURE_RECOMMENDATION_FEEDBACK',
            'FEATURE_FILE_REPORTS'
        }
    )
    recommendation_service = SimpleNamespace(
        invalidate_user_recommendations=AsyncMock()
    )
    message = SimpleNamespace(reply_text=AsyncMock())
    query = SimpleNamespace(
        data=f"feature#fav#{file.file_unique_id}",
        from_user=SimpleNamespace(id=77),
        message=message,
        answer=AsyncMock()
    )
    handler = object.__new__(FeatureHandler)
    handler.service = service
    handler.repository = repository
    handler.bot = SimpleNamespace(
        media_repo=SimpleNamespace(find_file=AsyncMock(return_value=file)),
        recommendation_service=recommendation_service
    )
    callback = FeatureHandler.feature_callback.__wrapped__.__wrapped__

    await callback(handler, None, query)
    repository.add_to_collection.assert_awaited_once_with(
        77, file.file_unique_id
    )

    query.data = f"feature#less#{file.file_unique_id}"
    await callback(handler, None, query)
    repository.set_recommendation_feedback.assert_awaited_once_with(
        77, file.file_unique_id, 'less'
    )
    recommendation_service.invalidate_user_recommendations.assert_awaited_once_with(77)

    query.data = f"feature#report#{file.file_unique_id}"
    await callback(handler, None, query)
    message.reply_text.assert_awaited_once()

    query.data = f"feature#reason_broken#{file.file_unique_id}"
    await callback(handler, None, query)
    repository.create_file_report.assert_awaited_once_with(
        77, file.file_unique_id, 'broken'
    )


@pytest.mark.asyncio
async def test_duplicate_pending_request_is_returned_without_second_insert():
    existing = {
        '_id': '7:10',
        'user_id': 7,
        'query': 'The Matrix',
        'normalized_query': 'the matrix',
        'status': 'pending'
    }
    collection = SimpleNamespace(
        find_one=AsyncMock(return_value=existing),
        insert_one=AsyncMock()
    )

    class Pool:
        async def get_collection(self, name):
            assert name == 'content_requests'
            return collection

        async def execute_with_retry(self, function, *args, **kwargs):
            return await function(*args, **kwargs)

    repository = FeatureRepository(Pool())
    document, created = await repository.create_content_request(
        7, 11, "  the matrix "
    )

    assert document is existing
    assert created is False
    collection.insert_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_status_notification_transition_is_atomically_claimed():
    result = SimpleNamespace(modified_count=1)
    collection = SimpleNamespace(update_one=AsyncMock(return_value=result))

    class Pool:
        async def get_collection(self, name):
            assert name == 'content_requests'
            return collection

        async def execute_with_retry(self, function, *args, **kwargs):
            return await function(*args, **kwargs)

    repository = FeatureRepository(Pool())
    assert await repository.claim_content_request_transition(
        7, 10, 'completed', 1
    )
    claim_filter = collection.update_one.await_args_list[0].args[0]
    assert claim_filter == {'_id': '7:10', 'status': 'pending'}

    assert await repository.finish_content_request_transition(
        7, 10, 'completed'
    )
    finish_filter = collection.update_one.await_args_list[1].args[0]
    assert finish_filter == {'_id': '7:10', 'status': 'processing:completed'}


@pytest.mark.asyncio
async def test_content_dashboard_uses_bounded_aggregate_sources():
    repository = SimpleNamespace(
        top_zero_results=AsyncMock(return_value=[{'query': 'missing', 'count': 3}]),
        count_documents=AsyncMock(side_effect=[2, 4, 5, 6])
    )
    media_repo = SimpleNamespace(
        get_file_stats=AsyncMock(return_value={'total_files': 10, 'total_size': 2048})
    )
    history = SimpleNamespace(
        get_global_top_searches=AsyncMock(return_value=['matrix'])
    )
    service = FeatureService(
        repository,
        media_repo,
        history,
        feature_config('FEATURE_CONTENT_DASHBOARD')
    )

    dashboard = await service.dashboard()

    assert dashboard['media']['total_files'] == 10
    assert dashboard['open_reports'] == 2
    assert dashboard['pending_requests'] == 4
    assert dashboard['saved_searches'] == 5
    assert dashboard['collections'] == 6
