"""Regression coverage for POTENTIAL_ISSUES task ownership and shutdown."""
import asyncio
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from handlers.manager import HandlerManager


@pytest.mark.asyncio
@pytest.mark.parametrize("factory", ["create_background_task", "create_auto_delete_task"])
async def test_managed_task_failure_is_retrieved_and_logged(factory, monkeypatch):
    manager = HandlerManager(SimpleNamespace())
    error = Mock()
    monkeypatch.setattr("handlers.manager.logger.error", error)

    async def fail():
        raise RuntimeError("QA task failure")

    task = getattr(manager, factory)(fail())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert task.done()
    # Inspect before retrieving it ourselves: asyncio otherwise emits an
    # unhandled-task warning once the unreferenced task is collected.
    unhandled = task._log_traceback
    task.exception()
    assert not unhandled
    assert error.called
    await manager.cleanup()


@pytest.mark.asyncio
async def test_cleanup_cancels_scheduled_deletions_and_rejects_new_work():
    manager = HandlerManager(SimpleNamespace())
    deleted = AsyncMock()

    async def delayed_delete():
        await asyncio.sleep(3600)
        await deleted()

    task = manager.create_auto_delete_task(delayed_delete())
    await asyncio.sleep(0)
    await manager.cleanup()
    assert task.cancelled()
    deleted.assert_not_awaited()
    coroutine = delayed_delete()
    assert manager.create_auto_delete_task(coroutine) is None
    assert coroutine.cr_frame is None


def test_delivery_paths_do_not_spawn_unmanaged_deletion_tasks():
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for name in ["handlers/deeplink.py", "handlers/commands_handlers/bot_settings.py",
                 "core/services/filestore.py", "core/services/search_results.py"]:
        for node in ast.walk(ast.parse((root / name).read_text())):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "asyncio"
                    and node.func.attr == "create_task"):
                offenders.append(f"{name}:{node.lineno}")
    assert offenders == []


@pytest.mark.asyncio
async def test_service_tasks_use_shared_shutdown_manager():
    from core.utils.service_tasks import ServiceTasks
    manager=HandlerManager(SimpleNamespace())
    service=ServiceTasks(manager)
    tasks=[service.create(asyncio.sleep(3600), auto_delete=auto) for auto in [False,True]]
    await asyncio.sleep(0)
    await manager.cleanup()
    assert all(t.cancelled() for t in tasks)
    coroutine=asyncio.sleep(3600)
    assert service.create(coroutine) is None
    assert coroutine.cr_frame is None


@pytest.mark.asyncio
async def test_standalone_service_owns_and_closes_tasks():
    from core.utils.service_tasks import ServiceTasks
    service=ServiceTasks()
    task=service.create(asyncio.sleep(3600))
    await asyncio.sleep(0)
    assert task in service.pending
    await service.close()
    assert task.cancelled() and not service.pending
