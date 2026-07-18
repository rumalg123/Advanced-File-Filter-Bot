import re
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pyrogram.types import InlineKeyboardMarkup

from core.utils.button_builder import ButtonBuilder
from handlers.features import FeatureHandler
from repositories.features import FeatureRepository
from repositories.media import FileType, MediaFile


def make_file(identifier: str = "file-1") -> MediaFile:
    return MediaFile(
        file_unique_id=identifier,
        file_id=f"telegram-{identifier}",
        file_ref=None,
        file_name=f"Movie.{identifier}.1080p.mkv",
        file_size=1024,
        file_type=FileType.VIDEO,
        mime_type="video/x-matroska",
        caption=None,
    )


class MemoryCursor:
    def __init__(self, collection, query):
        self.collection = collection
        self.query = query
        self._limit = None
        self._sort = None

    def sort(self, key, direction):
        self._sort = (key, direction)
        return self

    def limit(self, value):
        self._limit = value
        return self

    async def to_list(self, length):
        values = [
            deepcopy(document)
            for document in self.collection.documents.values()
            if self.collection.matches(document, self.query)
        ]
        if self._sort:
            key, direction = self._sort
            values.sort(key=lambda item: item.get(key), reverse=direction < 0)
        limit = min(length, self._limit) if self._limit is not None else length
        return values[:limit]


class MemoryCollection:
    def __init__(self):
        self.documents = {}

    @classmethod
    def matches(cls, document, query):
        for key, expected in query.items():
            if key == '$or':
                if not any(cls.matches(document, option) for option in expected):
                    return False
                continue
            if key == '$expr':
                maximum = expected['$lt'][1]
                if len(document.get('file_ids', [])) >= maximum:
                    return False
                continue
            actual = document.get(key)
            if isinstance(expected, dict):
                if '$regex' in expected:
                    if not re.search(expected['$regex'], str(actual or '')):
                        return False
                elif '$ne' in expected:
                    if isinstance(actual, list):
                        if expected['$ne'] in actual:
                            return False
                    elif actual == expected['$ne']:
                        return False
                else:
                    raise AssertionError(f"Unsupported query operator: {expected}")
            elif isinstance(actual, list):
                if expected not in actual:
                    return False
            elif actual != expected:
                return False
        return True

    async def find_one(self, query):
        for document in self.documents.values():
            if self.matches(document, query):
                return deepcopy(document)
        return None

    def find(self, query):
        return MemoryCursor(self, query)

    async def update_one(self, query, update, upsert=False):
        selected_id = None
        for document_id, document in self.documents.items():
            if self.matches(document, query):
                selected_id = document_id
                break

        upserted_id = None
        if selected_id is None and upsert:
            selected_id = query.get('_id')
            document = {
                key: value
                for key, value in query.items()
                if not key.startswith('$') and not isinstance(value, dict)
            }
            document.update(deepcopy(update.get('$setOnInsert', {})))
            self.documents[selected_id] = document
            upserted_id = selected_id

        if selected_id is None:
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)

        document = self.documents[selected_id]
        before = deepcopy(document)
        for key, value in update.get('$set', {}).items():
            document[key] = deepcopy(value)
        for key, value in update.get('$addToSet', {}).items():
            target = document.setdefault(key, [])
            if value not in target:
                target.append(value)
        for key, value in update.get('$pull', {}).items():
            document[key] = [item for item in document.get(key, []) if item != value]
        self.documents[selected_id] = document
        return SimpleNamespace(
            matched_count=1,
            modified_count=int(document != before),
            upserted_id=upserted_id,
        )

    async def delete_one(self, query):
        for document_id, document in list(self.documents.items()):
            if self.matches(document, query):
                del self.documents[document_id]
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)


class MemoryPool:
    def __init__(self):
        self.collection = MemoryCollection()

    async def get_collection(self, name):
        assert name == 'user_collections'
        return self.collection

    async def execute_with_retry(self, function, *args, **kwargs):
        return await function(*args, **kwargs)


@pytest.mark.asyncio
async def test_collection_repository_supports_owned_full_crud_and_membership():
    pool = MemoryPool()
    repository = FeatureRepository(pool)

    created = await repository.ensure_collection(7, 'Watch Later')
    token = created['callback_token']
    assert re.fullmatch(r'[a-f0-9]{8}', token)
    assert await repository.get_collection_by_token(8, token) is None

    renamed, state = await repository.rename_collection(
        7, 'Watch Later', 'Sci Fi'
    )
    assert state == 'renamed'
    assert renamed['_id'] == created['_id']
    assert renamed['callback_token'] == token

    same_collection = await repository.ensure_collection(7, 'Sci Fi')
    assert same_collection['_id'] == created['_id']
    assert len(pool.collection.documents) == 1

    collection, add_state = await repository.add_to_collection_by_token(
        7, token, 'file-1'
    )
    assert add_state == 'added'
    assert collection['file_ids'] == ['file-1']
    _, duplicate_state = await repository.add_to_collection_by_token(
        7, token, 'file-1'
    )
    assert duplicate_state == 'duplicate'

    assert await repository.clear_collection_by_token(7, token) == 1
    assert await repository.delete_collection_by_token(8, token) is False
    assert await repository.delete_collection_by_token(7, token) is True
    assert pool.collection.documents == {}


@pytest.mark.asyncio
async def test_delivered_file_collection_picker_adds_only_by_owned_token():
    file = make_file('picker-file')
    collection = {
        '_id': '7:watch-later-deadbeef',
        'user_id': 7,
        'name': 'Watch Later',
        'normalized_name': 'watch later',
        'callback_token': 'deadbeef',
        'file_ids': [],
    }
    picker = SimpleNamespace(delete=AsyncMock())
    source_message = SimpleNamespace(reply_text=AsyncMock(return_value=picker))
    query = SimpleNamespace(
        data=f'feature#col_pick#{file.file_unique_id}',
        from_user=SimpleNamespace(id=7),
        message=source_message,
        answer=AsyncMock(),
    )
    repository = SimpleNamespace(
        list_collections=AsyncMock(return_value=[collection]),
        add_to_collection_by_token=AsyncMock(return_value=(collection, 'added')),
    )
    handler = object.__new__(FeatureHandler)
    handler.service = SimpleNamespace(enabled=lambda flag: flag == 'FEATURE_FAVORITES')
    handler.repository = repository
    handler.bot = SimpleNamespace(
        config=SimpleNamespace(MESSAGE_DELETE_SECONDS=30),
        media_repo=SimpleNamespace(find_file=AsyncMock(return_value=file)),
    )
    handler._schedule_auto_delete = Mock()
    callback = FeatureHandler.feature_callback.__wrapped__.__wrapped__

    await callback(handler, None, query)

    markup = source_message.reply_text.await_args.kwargs['reply_markup']
    add_callback = markup.inline_keyboard[0][0].callback_data
    assert add_callback == f'feature#col_add#{file.file_unique_id}#deadbeef'
    assert len(add_callback.encode()) <= 64
    handler._schedule_auto_delete.assert_called_once_with(picker, 30)

    query.data = add_callback
    query.message = picker
    await callback(handler, None, query)

    repository.add_to_collection_by_token.assert_awaited_once_with(
        7, 'deadbeef', file.file_unique_id
    )
    picker.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_collection_delete_callback_requires_confirmation():
    collection = {
        '_id': '7:list-deadbeef',
        'user_id': 7,
        'name': 'My List',
        'callback_token': 'deadbeef',
        'file_ids': [],
    }
    confirmation = SimpleNamespace(delete=AsyncMock())
    source = SimpleNamespace(reply_text=AsyncMock(return_value=confirmation))
    repository = SimpleNamespace(
        get_collection_by_token=AsyncMock(return_value=collection),
        delete_collection_by_token=AsyncMock(return_value=True),
    )
    handler = object.__new__(FeatureHandler)
    handler.service = SimpleNamespace(enabled=lambda flag: flag == 'FEATURE_FAVORITES')
    handler.repository = repository
    handler.bot = SimpleNamespace(config=SimpleNamespace(MESSAGE_DELETE_SECONDS=20))
    handler._schedule_auto_delete = Mock()
    query = SimpleNamespace(
        data='feature#col_delete#deadbeef',
        from_user=SimpleNamespace(id=7),
        message=source,
        answer=AsyncMock(),
    )
    callback = FeatureHandler.feature_callback.__wrapped__.__wrapped__

    await callback(handler, None, query)
    repository.delete_collection_by_token.assert_not_awaited()
    markup = source.reply_text.await_args.kwargs['reply_markup']
    confirm_callback = markup.inline_keyboard[0][0].callback_data
    assert confirm_callback == 'feature#col_delete_confirm#deadbeef'

    query.data = confirm_callback
    query.message = confirmation
    await callback(handler, None, query)
    repository.delete_collection_by_token.assert_awaited_once_with(7, 'deadbeef')
    confirmation.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_recent_and_recommendation_entries_support_individual_delete():
    recent_message = SimpleNamespace(
        reply_markup=InlineKeyboardMarkup([[
            ButtonBuilder.action_button(
                'Remove', callback_data='feature#recent_remove#file-1'
            )
        ]]),
        delete=AsyncMock(),
    )
    repository = SimpleNamespace(
        remove_recent_file=AsyncMock(return_value=True),
        delete_recommendation_feedback=AsyncMock(return_value=True),
    )
    recommendations = SimpleNamespace(
        invalidate_user_recommendations=AsyncMock()
    )
    handler = object.__new__(FeatureHandler)
    handler.service = SimpleNamespace(
        enabled=lambda flag: flag in {
            'FEATURE_RECENT_FILES', 'FEATURE_RECOMMENDATION_FEEDBACK'
        }
    )
    handler.repository = repository
    handler.bot = SimpleNamespace(recommendation_service=recommendations)
    query = SimpleNamespace(
        data='feature#recent_remove#file-1',
        from_user=SimpleNamespace(id=7),
        message=recent_message,
        answer=AsyncMock(),
    )
    callback = FeatureHandler.feature_callback.__wrapped__.__wrapped__

    await callback(handler, None, query)
    repository.remove_recent_file.assert_awaited_once_with(7, 'file-1')
    recent_message.delete.assert_awaited_once()

    query.data = 'feature#rec_reset#file-1'
    query.message = SimpleNamespace()
    await callback(handler, None, query)
    repository.delete_recommendation_feedback.assert_awaited_once_with(7, 'file-1')
    recommendations.invalidate_user_recommendations.assert_awaited_once_with(7)

    feedback_list_message = SimpleNamespace(
        reply_markup=InlineKeyboardMarkup([[
            ButtonBuilder.action_button(
                'Reset', callback_data='feature#rec_reset_list#file-1'
            )
        ]]),
        delete=AsyncMock(),
    )
    query.data = 'feature#rec_reset_list#file-1'
    query.message = feedback_list_message
    await callback(handler, None, query)
    assert repository.delete_recommendation_feedback.await_count == 2
    assert recommendations.invalidate_user_recommendations.await_count == 2
    feedback_list_message.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_recommendation_preferences_lists_names_and_reset_actions():
    file = make_file('preferred')
    sent_menu = SimpleNamespace()
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=7),
        reply_text=AsyncMock(return_value=sent_menu),
    )
    handler = object.__new__(FeatureHandler)
    handler.repository = SimpleNamespace(
        list_recommendation_feedback=AsyncMock(return_value=[{
            'file_unique_id': file.file_unique_id,
            'signal': 'more',
            'updated_at': datetime.now(UTC),
        }])
    )
    handler.bot = SimpleNamespace(
        config=SimpleNamespace(MESSAGE_DELETE_SECONDS=25),
        media_repo=SimpleNamespace(find_files_batch=AsyncMock(return_value={
            file.file_unique_id: file
        })),
    )
    handler._schedule_auto_delete = Mock()
    command = (
        FeatureHandler.recommendation_preferences_command
        .__wrapped__.__wrapped__
    )

    await command(handler, None, message)

    text = message.reply_text.await_args.args[0]
    markup = message.reply_text.await_args.kwargs['reply_markup']
    assert file.file_name in text
    assert 'More like this' in text
    assert markup.inline_keyboard[0][-1].callback_data == (
        f'feature#rec_reset_list#{file.file_unique_id}'
    )
    handler._schedule_auto_delete.assert_called_once_with(sent_menu, 25)
