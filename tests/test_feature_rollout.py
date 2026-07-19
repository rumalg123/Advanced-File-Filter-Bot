from copy import deepcopy
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pyrogram.errors import UserIsBlocked
from pyrogram.types import InlineKeyboardMarkup

from config.settings import FeatureConfig
from core.cache.config import CacheKeyGenerator
from core.services.bot_settings import BotSettingsService
from core.services.features import FeatureService
from core.services.file_access import FileAccessService
from core.services.recommendation import RecommendationService
from core.services.search_results import SearchResultsService
from core.utils.button_builder import ButtonBuilder
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

    assert len(handler._handlers) == 20
    assert manager.add_handler.call_count == 20


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

    title_filter = repository._build_search_filter(
        "Agent Kim Reactivated", None, True
    )
    title_pattern = title_filter['$or'][0]['file_name']['$regex']
    assert re.search(
        title_pattern,
        "Agent Kim Reactivated S01E06 NF x264 540p mkv",
        re.IGNORECASE
    )

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
        'fav', 'unfav', 'col_pick', 'more', 'less', 'rec_reset', 'report'
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
        remove_from_collection=AsyncMock(return_value=True),
        set_recommendation_feedback=AsyncMock(return_value=True),
        create_file_report=AsyncMock(return_value=({
            '_id': 'report',
            'file_unique_id': file.file_unique_id,
            'file_name': file.file_name,
            'reason': 'broken',
            'reporter_ids': [77],
        }, 'created'))
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
    message = SimpleNamespace(reply_text=AsyncMock(), delete=AsyncMock())
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
        config=SimpleNamespace(MESSAGE_DELETE_SECONDS=0, LOG_CHANNEL=0),
        media_repo=SimpleNamespace(find_file=AsyncMock(return_value=file)),
        recommendation_service=recommendation_service
    )
    callback = FeatureHandler.feature_callback.__wrapped__.__wrapped__

    await callback(handler, None, query)
    repository.add_to_collection.assert_awaited_once_with(
        77, file.file_unique_id
    )

    query.data = f"feature#unfav#{file.file_unique_id}"
    await callback(handler, None, query)
    repository.remove_from_collection.assert_awaited_once_with(
        77, file.file_unique_id, 'Favorites'
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
        77, file.file_unique_id, 'broken', file.file_name
    )


@pytest.mark.asyncio
async def test_report_menu_updates_in_place_and_log_channel_includes_file_details():
    file = make_file('reported', 'Glory.E24.AMZN.1080p.mkv')
    report = {
        '_id': 'report-1',
        'file_unique_id': file.file_unique_id,
        'file_name': file.file_name,
        'reason': 'quality',
        'reporter_ids': [77],
    }
    repository = SimpleNamespace(
        create_file_report=AsyncMock(return_value=(report, 'created'))
    )
    service = SimpleNamespace(
        enabled=lambda flag: flag == 'FEATURE_FILE_REPORTS'
    )
    report_markup = InlineKeyboardMarkup([[
        ButtonBuilder.action_button(
            '🚩 Report',
            callback_data=f'feature#report#{file.file_unique_id}'
        )
    ]])
    source_message = SimpleNamespace(
        reply_markup=report_markup,
        edit_reply_markup=AsyncMock(),
        reply_text=AsyncMock(),
        delete=AsyncMock()
    )
    query = SimpleNamespace(
        data=f"feature#report#{file.file_unique_id}",
        from_user=SimpleNamespace(
            id=77, first_name='Test', last_name='Reporter', username='tester'
        ),
        message=source_message,
        answer=AsyncMock()
    )
    client = SimpleNamespace(send_message=AsyncMock())
    handler = object.__new__(FeatureHandler)
    handler.service = service
    handler.repository = repository
    handler.bot = SimpleNamespace(
        config=SimpleNamespace(MESSAGE_DELETE_SECONDS=45, LOG_CHANNEL=-100123),
        media_repo=SimpleNamespace(find_file=AsyncMock(return_value=file))
    )
    handler._schedule_auto_delete = Mock()
    callback = FeatureHandler.feature_callback.__wrapped__.__wrapped__

    await callback(handler, client, query)
    handler._schedule_auto_delete.assert_not_called()
    source_message.reply_text.assert_not_awaited()
    reason_markup = source_message.edit_reply_markup.await_args.args[0]
    assert reason_markup.inline_keyboard[-1][0].callback_data == (
        f'feature#reason_quality#{file.file_unique_id}'
    )

    query.data = f"feature#reason_quality#{file.file_unique_id}"
    source_message.reply_markup = reason_markup
    await callback(handler, client, query)

    state_markup = source_message.edit_reply_markup.await_args.args[0]
    assert 'Poor quality' in state_markup.inline_keyboard[-1][0].text
    assert 'Reported' in state_markup.inline_keyboard[-1][0].text
    source_message.delete.assert_not_awaited()
    log_text = client.send_message.await_args.args[1]
    assert file.file_name in log_text
    assert file.file_unique_id in log_text
    assert 'Poor quality' in log_text
    assert 'Test Reporter' in log_text


@pytest.mark.asyncio
async def test_favorites_menu_has_remove_action_and_uses_cleanup_timer():
    file = make_file('favorite-file')
    sent_menu = SimpleNamespace(
        reply_markup=None,
        edit_reply_markup=AsyncMock(),
        delete=AsyncMock()
    )
    command_message = SimpleNamespace(
        reply_text=AsyncMock(return_value=sent_menu)
    )
    repository = SimpleNamespace(
        remove_from_collection=AsyncMock(return_value=True)
    )
    handler = object.__new__(FeatureHandler)
    handler.service = SimpleNamespace(
        enabled=lambda flag: flag == 'FEATURE_FAVORITES'
    )
    handler.repository = repository
    handler.bot = SimpleNamespace(
        config=SimpleNamespace(MESSAGE_DELETE_SECONDS=30),
        media_repo=SimpleNamespace(
            find_files_batch=AsyncMock(return_value={file.file_unique_id: file})
        )
    )
    handler._schedule_auto_delete = Mock()

    await handler._send_file_list(
        command_message,
        '⭐ <b>Favorites</b>',
        [file.file_unique_id],
        collection_name='Favorites'
    )

    markup = command_message.reply_text.await_args.kwargs['reply_markup']
    sent_menu.reply_markup = markup
    remove_button = next(
        button
        for button in markup.inline_keyboard[0]
        if button.callback_data.startswith('feature#unfavlist#')
    )
    handler._schedule_auto_delete.assert_called_once_with(sent_menu, 30)

    query = SimpleNamespace(
        data=remove_button.callback_data,
        from_user=SimpleNamespace(id=77),
        message=sent_menu,
        answer=AsyncMock()
    )
    callback = FeatureHandler.feature_callback.__wrapped__.__wrapped__
    await callback(handler, None, query)

    repository.remove_from_collection.assert_awaited_once_with(
        77, file.file_unique_id, 'Favorites'
    )
    sent_menu.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_favorite_removal_requires_the_file_to_be_in_the_collection():
    collection = SimpleNamespace(
        update_one=AsyncMock(return_value=SimpleNamespace(modified_count=0))
    )

    class Pool:
        async def get_collection(self, name):
            assert name == 'user_collections'
            return collection

        async def execute_with_retry(self, function, *args, **kwargs):
            return await function(*args, **kwargs)

    repository = FeatureRepository(Pool())
    removed = await repository.remove_from_collection(
        77, 'file-1', 'Favorites'
    )

    assert removed is False
    remove_filter = collection.update_one.await_args.args[0]
    assert remove_filter == {
        'user_id': 77,
        'normalized_name': 'favorites',
        'file_ids': 'file-1',
    }


@pytest.mark.asyncio
async def test_file_reports_deduplicate_reporters_and_can_reopen_after_resolution():
    class ReportCollection:
        class Cursor:
            def __init__(self, collection, query):
                self.collection = collection
                self.query = query

            def sort(self, *args, **kwargs):
                return self

            def limit(self, *args, **kwargs):
                return self

            async def to_list(self, length):
                return [
                    deepcopy(document)
                    for document in self.collection.documents.values()
                    if self.collection._matches(document, self.query)
                ][:length]

        def __init__(self):
            self.documents = {}

        @staticmethod
        def _matches(document, query):
            for key, expected in query.items():
                actual = document.get(key)
                if isinstance(expected, dict) and '$ne' in expected:
                    if actual == expected['$ne']:
                        return False
                elif actual != expected:
                    return False
            return True

        async def find_one(self, query):
            for document in self.documents.values():
                if self._matches(document, query):
                    return deepcopy(document)
            return None

        def find(self, query):
            return self.Cursor(self, query)

        async def insert_one(self, document):
            self.documents[document['_id']] = deepcopy(document)
            return SimpleNamespace(inserted_id=document['_id'])

        async def update_one(self, query, update):
            for report_id, document in self.documents.items():
                if not self._matches(document, query):
                    continue
                before = deepcopy(document)
                for key, value in update.get('$set', {}).items():
                    document[key] = deepcopy(value)
                for key in update.get('$unset', {}):
                    document.pop(key, None)
                for key, value in update.get('$addToSet', {}).items():
                    additions = value.get('$each', []) if isinstance(value, dict) else [value]
                    target = document.setdefault(key, [])
                    for addition in additions:
                        if addition not in target:
                            target.append(addition)
                for key, value in update.get('$push', {}).items():
                    document.setdefault(key, []).append(deepcopy(value))
                self.documents[report_id] = document
                return SimpleNamespace(
                    matched_count=1,
                    modified_count=int(document != before)
                )
            return SimpleNamespace(matched_count=0, modified_count=0)

        async def find_one_and_update(self, query, update, **kwargs):
            result = await self.update_one(query, update)
            if not result.matched_count:
                return None
            return await self.find_one({'_id': query['_id']})

    collection = ReportCollection()

    class Pool:
        async def get_collection(self, name):
            assert name == 'file_reports'
            return collection

        async def execute_with_retry(self, function, *args, **kwargs):
            return await function(*args, **kwargs)

    repository = FeatureRepository(Pool())
    first, first_state = await repository.create_file_report(
        1, 'file-1', 'broken', 'Movie.mkv'
    )
    second, second_state = await repository.create_file_report(
        2, 'file-1', 'broken', 'Movie.mkv'
    )
    duplicate, duplicate_state = await repository.create_file_report(
        2, 'file-1', 'broken', 'Movie.mkv'
    )

    assert first_state == 'created'
    assert second_state == 'subscribed'
    assert duplicate_state == 'duplicate'
    assert first['_id'] == second['_id'] == duplicate['_id']
    assert len(collection.documents) == 1
    assert second['reporter_ids'] == [1, 2]

    collection.documents['legacy-duplicate'] = {
        '_id': 'legacy-duplicate',
        'user_id': 4,
        'file_unique_id': 'file-1',
        'file_name': 'Movie.mkv',
        'reason': 'broken',
        'status': 'open',
        'created_at': first['created_at'],
        'updated_at': first['updated_at'],
    }
    listed = await repository.list_file_reports('open')
    assert len(listed) == 1
    assert listed[0]['reporter_ids'] == [1, 2, 4]
    assert listed[0]['duplicate_report_ids'] == ['legacy-duplicate']

    resolved = await repository.resolve_file_report(first['_id'], admin_id=99)
    assert resolved['status'] == 'resolved'
    assert resolved['reporter_ids'] == [1, 2, 4]
    assert resolved['resolution_history'][0]['resolved_by'] == 99
    assert collection.documents['legacy-duplicate']['status'] == 'merged'

    reopened, reopened_state = await repository.create_file_report(
        3, 'file-1', 'broken', 'Movie.mkv'
    )
    assert reopened_state == 'created'
    assert reopened['reporter_ids'] == [3]
    assert len(collection.documents) == 2


@pytest.mark.asyncio
async def test_report_resolution_notifies_subscribers_and_skips_blocked_users():
    file = make_file('reported-file', 'Reported.Movie.2026.1080p.mkv')
    report = {
        '_id': 'report-1',
        'file_unique_id': file.file_unique_id,
        'file_name': file.file_name,
        'reason': 'broken',
        'reporter_ids': [10, 20],
        'status': 'resolved',
    }
    repository = SimpleNamespace(
        resolve_file_report=AsyncMock(return_value=report),
        record_report_notification_results=AsyncMock()
    )
    client = SimpleNamespace(
        get_chat=AsyncMock(side_effect=[SimpleNamespace(id=10), UserIsBlocked()]),
        send_message=AsyncMock()
    )
    message = SimpleNamespace(
        text='/resolve_report report-1',
        from_user=SimpleNamespace(id=99),
        reply_text=AsyncMock()
    )
    handler = object.__new__(FeatureHandler)
    handler.repository = repository
    handler.bot = SimpleNamespace(
        config=SimpleNamespace(LOG_CHANNEL=0),
        media_repo=SimpleNamespace(find_file=AsyncMock(return_value=file))
    )

    await handler.resolve_report_command(client, message)

    client.send_message.assert_awaited_once()
    assert client.send_message.await_args.args[0] == 10
    repository.record_report_notification_results.assert_awaited_once_with(
        'report-1', [10], [20], []
    )
    result_text = message.reply_text.await_args.args[0]
    assert 'Notified 1' in result_text
    assert 'unreachable 1' in result_text


@pytest.mark.asyncio
async def test_admin_report_list_resolves_and_displays_legacy_file_names():
    file = make_file('legacy-report-file', 'Legacy.Reported.Movie.mkv')
    report = {
        '_id': 'legacy-report',
        'user_id': 10,
        'file_unique_id': file.file_unique_id,
        'reason': 'incorrect',
        'status': 'open',
    }
    message = SimpleNamespace(
        text='/file_reports open',
        reply_text=AsyncMock()
    )
    handler = object.__new__(FeatureHandler)
    handler.repository = SimpleNamespace(
        list_file_reports=AsyncMock(return_value=[report])
    )
    handler.bot = SimpleNamespace(
        media_repo=SimpleNamespace(find_files_batch=AsyncMock(return_value={
            file.file_unique_id: file
        }))
    )

    await handler.file_reports_command(None, message)

    report_text = message.reply_text.await_args.args[0]
    assert file.file_name in report_text
    assert file.file_unique_id in report_text
    assert 'Incorrect title or metadata' in report_text
    assert 'Reporters: <b>1</b>' in report_text


@pytest.mark.asyncio
async def test_saved_search_and_suggestion_menus_use_cleanup_timer():
    saved_menu = SimpleNamespace()
    suggestion_menu = SimpleNamespace()
    message = SimpleNamespace(
        text='/saved_searches',
        from_user=SimpleNamespace(id=77),
        reply_text=AsyncMock(side_effect=[saved_menu, suggestion_menu])
    )
    handler = object.__new__(FeatureHandler)
    handler.repository = SimpleNamespace(
        list_saved_searches=AsyncMock(return_value=[{
            '_id': 'saved-1', 'query': 'glory', 'active': True
        }])
    )
    handler.service = SimpleNamespace(
        autocomplete=AsyncMock(return_value=['glory 2026'])
    )
    handler.bot = SimpleNamespace(
        config=SimpleNamespace(MESSAGE_DELETE_SECONDS=35),
        cache=SortedCache()
    )
    handler._schedule_auto_delete = Mock()

    saved_callback = FeatureHandler.saved_searches_command.__wrapped__.__wrapped__
    suggest_callback = FeatureHandler.suggest_command.__wrapped__.__wrapped__
    await saved_callback(handler, None, message)
    message.text = '/suggest glory'
    await suggest_callback(handler, None, message)

    saved_markup = message.reply_text.await_args_list[0].kwargs['reply_markup']
    assert saved_markup.inline_keyboard[0][0].callback_data.startswith(
        'search#page#@'
    )
    assert handler._schedule_auto_delete.call_args_list == [
        ((saved_menu, 35), {}),
        ((suggestion_menu, 35), {}),
    ]


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


@pytest.mark.asyncio
async def test_content_dashboard_removes_queries_that_now_have_files():
    repository = SimpleNamespace(
        top_zero_results=AsyncMock(return_value=[
            {'_id': 'agent kim reactivated', 'query': 'Agent Kim reactivated', 'count': 4},
            {'_id': 'missing title', 'query': 'Missing title', 'count': 3},
        ]),
        resolve_zero_result=AsyncMock(return_value=True),
        count_documents=AsyncMock(side_effect=[0, 0, 0, 0])
    )

    async def has_matching_file(query, **_kwargs):
        return query.lower() == 'agent kim reactivated'

    media_repo = SimpleNamespace(
        get_file_stats=AsyncMock(return_value={'total_files': 1, 'total_size': 1}),
        has_matching_file=has_matching_file
    )
    service = FeatureService(
        repository,
        media_repo,
        SimpleNamespace(get_global_top_searches=AsyncMock(return_value=[])),
        feature_config('FEATURE_CONTENT_DASHBOARD')
    )

    dashboard = await service.dashboard()

    assert [item['query'] for item in dashboard['zero_results']] == ['Missing title']
    repository.resolve_zero_result.assert_awaited_once_with(
        'Agent Kim reactivated'
    )
    repository.top_zero_results.assert_awaited_once_with(limit=30)


@pytest.mark.asyncio
async def test_successful_search_resolves_normalized_zero_result_record():
    result = SimpleNamespace(deleted_count=1)
    collection = SimpleNamespace(delete_one=AsyncMock(return_value=result))

    class Pool:
        async def get_collection(self, name):
            assert name == 'search_analytics'
            return collection

        async def execute_with_retry(self, function, *args, **kwargs):
            return await function(*args, **kwargs)

    repository = FeatureRepository(Pool())

    assert await repository.resolve_zero_result("  Agent Kim Reactivated  ")
    collection.delete_one.assert_awaited_once_with({
        '_id': 'agent kim reactivated'
    })
