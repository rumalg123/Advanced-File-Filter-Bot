import asyncio

import pytest

from core.utils.verify_alignment import AlignmentVerifier
from handlers.base import BaseHandler
from handlers.commands import CommandHandler
from handlers.commands_handlers.database import DatabaseCommandHandler
from handlers.manager import HandlerManager


EXPECTED_HANDLERS = {
    'command',
    'search',
    'delete',
    'channel',
    'indexing',
    'filestore',
    'request',
    'features',
    'database',
}


class _HealthyHandler:
    def __init__(self):
        self._handlers = [object()]
        self._shutdown = asyncio.Event()

    async def cleanup(self):
        return None


class _RunningTask:
    @staticmethod
    def done():
        return False


class _VerifierManager:
    def __init__(self):
        self.handler_instances = {
            name: _HealthyHandler() for name in EXPECTED_HANDLERS
        }
        self.named_tasks = {'maintenance_tasks': _RunningTask()}

    @staticmethod
    def get_stats():
        return {
            'background_tasks': 1,
            'auto_delete_tasks': 0,
            'named_tasks': 1,
            'total_created': 1,
            'total_completed': 0,
        }


class _VerifierBot:
    handler_manager = _VerifierManager()
    config = type('Config', (), {'DISABLE_FILTER': True})()


@pytest.mark.asyncio
async def test_alignment_verifier_accepts_all_intentional_handlers():
    results = await AlignmentVerifier(_VerifierBot()).verify_all()

    assert results['issues'] == []
    assert results['warnings'] == []
    assert results['is_aligned'] is True
    assert results['health_score'] == 100


def test_alignment_score_cannot_hide_issues_by_saturating_at_100():
    verifier = AlignmentVerifier(_VerifierBot())
    verifier.successes = ['ok'] * 32
    verifier.warnings = ['warning'] * 4
    verifier.issues = ['issue'] * 2

    assert verifier._calculate_health_score() == 89


def test_command_and_database_handlers_use_managed_lifecycle():
    assert issubclass(CommandHandler, BaseHandler)
    assert issubclass(DatabaseCommandHandler, BaseHandler)


class _DispatcherBot:
    def __init__(self):
        self.added = []
        self.removed = []

    def add_handler(self, handler, group=0):
        self.added.append((handler, group))

    def remove_handler(self, handler, group=0):
        self.removed.append((handler, group))


@pytest.mark.asyncio
async def test_handler_manager_preserves_dispatcher_group_during_cleanup():
    bot = _DispatcherBot()
    manager = HandlerManager(bot)
    handler = object()

    manager.add_handler(handler, group=10)
    await manager.cleanup()

    assert bot.added == [(handler, 10)]
    assert bot.removed == [(handler, 10)]
    assert manager.handlers == []
    assert manager.handler_groups == {}


@pytest.mark.asyncio
@pytest.mark.parametrize('filters_disabled', [True,False])
async def test_initialized_handler_aliases_refer_to_managed_instances(monkeypatch, filters_disabled):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock,Mock
    from bot import MediaSearchBot

    bot=object.__new__(MediaSearchBot)
    bot.config=SimpleNamespace(DISABLE_FILTER=filters_disabled)
    bot.handler_manager=SimpleNamespace(handler_instances={})
    bot.indexing_service=object();bot.index_request_service=object()
    bot.channel_repo=object();bot.connection_service=object()
    bot._initialize_broadcast_recovery=AsyncMock()
    paths={
        'delete':'handlers.delete.DeleteHandler',
        'command':'handlers.commands.CommandHandler',
        'filestore':'handlers.filestore.FileStoreHandler',
        'indexing':'handlers.indexing.IndexingHandler',
        'channel':'handlers.channel.ChannelHandler',
        'request':'bot.RequestHandler',
        'features':'handlers.features.FeatureHandler',
        'search':'handlers.search.SearchHandler',
        'database':'handlers.commands_handlers.database.DatabaseCommandHandler',
        'connection':'handlers.connection.ConnectionHandler',
        'filter':'handlers.filter.FilterHandler',
    }
    instances={name:object() for name in paths}
    for name,path in paths.items():monkeypatch.setattr(path,Mock(return_value=instances[name]))
    await bot._initialize_handlers()
    expected=set(paths)-({'connection','filter'} if filters_disabled else set())
    assert set(bot.handler_manager.handler_instances)==expected
    for name in expected:
        assert getattr(bot,name+'_handler',None) is instances[name]


@pytest.mark.asyncio
async def test_channel_refresh_releases_old_manager_registrations():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from handlers.channel import ChannelHandler

    bot=_DispatcherBot();bot.handler_manager=HandlerManager(bot)
    handler=object.__new__(ChannelHandler)
    handler.bot=bot;handler._handlers=[];handler._update_lock=asyncio.Lock()
    handler.media_filter=__import__('pyrogram').filters.document
    handler.channel_repo=SimpleNamespace(get_active_channels=AsyncMock(return_value=[SimpleNamespace(channel_id=-100123)]))
    for _ in range(5):
        await handler.update_handlers()
        assert len(bot.handler_manager.handlers)==1
        assert bot.handler_manager.handlers==handler._handlers
    handler.channel_repo.get_active_channels.return_value=[]
    await handler.update_handlers()
    assert bot.handler_manager.handlers==[]


def test_readded_handler_can_be_removed_again():
    bot=_DispatcherBot();manager=HandlerManager(bot);handler=object()
    manager.add_handler(handler);manager.remove_handler(handler)
    manager.add_handler(handler);manager.remove_handler(handler)
    assert manager.handlers==[]
    assert len(bot.removed)==2
