import ast
import inspect
import textwrap
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from handlers.commands_handlers.base import BaseCommandHandler
from handlers.commands_handlers.user import UserCommandHandler
from handlers.features import FeatureHandler


class _TaskManager:
    def __init__(self):
        self.coroutines = []

    def create_auto_delete_task(self, coroutine):
        self.coroutines.append(coroutine)
        return coroutine


@pytest.mark.asyncio
async def test_temporary_reply_uses_configured_delay_and_shared_task_manager():
    manager = _TaskManager()
    bot = SimpleNamespace(
        config=SimpleNamespace(MESSAGE_DELETE_SECONDS=37),
        handler_manager=manager,
    )
    handler = BaseCommandHandler(bot)
    sent_message = SimpleNamespace(delete=AsyncMock())
    source_message = SimpleNamespace(
        reply_text=AsyncMock(return_value=sent_message)
    )
    deletion = []

    async def record_delete(message, delay):
        deletion.append((message, delay))

    handler._auto_delete_message = record_delete

    result = await handler._reply_text_with_auto_delete(
        source_message, 'temporary', disable_web_page_preview=True
    )

    assert result is sent_message
    source_message.reply_text.assert_awaited_once_with(
        'temporary', disable_web_page_preview=True
    )
    assert len(manager.coroutines) == 1
    await manager.coroutines[0]
    assert deletion == [(sent_message, 37)]


@pytest.mark.asyncio
async def test_zero_delete_time_keeps_command_response():
    manager = SimpleNamespace(create_auto_delete_task=Mock())
    bot = SimpleNamespace(
        config=SimpleNamespace(MESSAGE_DELETE_SECONDS=0),
        handler_manager=manager,
    )
    handler = BaseCommandHandler(bot)
    sent_message = SimpleNamespace(delete=AsyncMock())
    source_message = SimpleNamespace(
        reply_text=AsyncMock(return_value=sent_message)
    )

    await handler._reply_text_with_auto_delete(source_message, 'persistent')

    manager.create_auto_delete_task.assert_not_called()
    sent_message.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_response_is_scheduled_for_auto_delete():
    manager = _TaskManager()
    bot = SimpleNamespace(
        config=SimpleNamespace(
            MESSAGE_DELETE_SECONDS=45,
            LOG_CHANNEL=None,
            PICS=[],
            SUPPORT_GROUP_URL=None,
            SUPPORT_GROUP_NAME=None,
            PAYMENT_LINK='https://example.com',
            START_MESSAGE='Welcome {mention} to {bot_name}',
        ),
        handler_manager=manager,
        user_repo=SimpleNamespace(is_user_exist=AsyncMock(return_value=True)),
        bot_username='filter_bot',
        bot_name='Filter Bot',
    )
    handler = UserCommandHandler(bot)
    sent_message = SimpleNamespace(delete=AsyncMock())
    source_message = SimpleNamespace(
        command=['start'],
        from_user=SimpleNamespace(
            id=123,
            first_name='User',
            mention='<a href="tg://user?id=123">User</a>',
        ),
        reply_text=AsyncMock(return_value=sent_message),
    )
    deletion = []

    async def record_delete(message, delay):
        deletion.append((message, delay))

    handler._auto_delete_message = record_delete

    await UserCommandHandler.start_command.__wrapped__(handler, None, source_message)

    source_message.reply_text.assert_awaited_once()
    assert len(manager.coroutines) == 1
    await manager.coroutines[0]
    assert deletion == [(sent_message, 45)]


def _direct_message_reply_calls(method):
    tree = ast.parse(textwrap.dedent(inspect.getsource(method)))
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if not isinstance(function, ast.Attribute):
            continue
        owner = function.value
        if (
            isinstance(owner, ast.Name)
            and owner.id == 'message'
            and function.attr in {'reply_text', 'reply_photo'}
        ):
            calls.append(function.attr)
    return calls


def test_user_information_commands_all_use_temporary_reply_helpers():
    methods = [
        UserCommandHandler.start_command,
        UserCommandHandler.help_command,
        UserCommandHandler.about_command,
        UserCommandHandler.stats_command,
        UserCommandHandler.plans_command,
        UserCommandHandler.request_stats_command,
        UserCommandHandler.my_keywords_command,
        UserCommandHandler.popular_keywords_command,
        UserCommandHandler.recommendations_command,
    ]

    assert all(_direct_message_reply_calls(method) == [] for method in methods)


def test_user_feature_commands_all_use_tracked_cleanup_helpers():
    methods = [
        FeatureHandler._send_file_list,
        FeatureHandler._favorite_mutation,
        FeatureHandler.save_search_command,
        FeatureHandler.saved_searches_command,
        FeatureHandler.favorite_command,
        FeatureHandler.unfavorite_command,
        FeatureHandler.favorites_command,
        FeatureHandler.collections_command,
        FeatureHandler.collection_create_command,
        FeatureHandler.collection_rename_command,
        FeatureHandler.collection_clear_command,
        FeatureHandler.collection_delete_command,
        FeatureHandler.recent_command,
        FeatureHandler.clear_recent_command,
        FeatureHandler.recommendation_preferences_command,
        FeatureHandler.suggest_command,
        FeatureHandler.search_help_command,
        FeatureHandler.my_requests_command,
    ]

    assert all(_direct_message_reply_calls(method) == [] for method in methods)
