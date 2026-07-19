from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from handlers.commands_handlers import admin as admin_module
from handlers.commands_handlers.admin import AdminCommandHandler


@pytest.mark.asyncio
async def test_performance_command_uses_canonical_process_metrics(monkeypatch):
    metrics = {
        "event_loop": "asyncio",
        "optimization": "Standard Mode",
        "recommendation": "",
        "uptime_seconds": 65,
        "process_memory_rss_mb": 123.45,
        "process_cpu_percent": 6.7,
        "num_threads": 4,
        "num_fds": 8,
        "pending_tasks": 2,
    }
    monkeypatch.setattr(
        admin_module.performance_monitor,
        "get_metrics",
        AsyncMock(return_value=metrics),
    )
    monkeypatch.setattr(
        admin_module.semaphore_manager,
        "get_metrics",
        AsyncMock(return_value={}),
    )

    handler = AdminCommandHandler(
        SimpleNamespace(config=SimpleNamespace(ADMINS=[1]))
    )
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1),
        reply_text=AsyncMock(),
    )

    await handler.performance_command(None, message)

    response = message.reply_text.await_args.args[0]
    assert "Memory: 123.45 MB" in response
    assert "CPU: 6.7%" in response
