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
