"""PH-024: FloodWait/backoff must not occupy a Telegram semaphore slot."""
import asyncio
import time

import pytest
from pyrogram.errors import FloodWait

from core.concurrency.semaphore_manager import SemaphoreManager
from core.utils.telegram_api import TelegramAPIWrapper


@pytest.mark.asyncio
async def test_flood_wait_releases_slot_and_other_chat_can_send(monkeypatch):
    manager = SemaphoreManager({"telegram_send": 1})
    monkeypatch.setattr("core.utils.telegram_api.semaphore_manager", manager)
    monkeypatch.setattr("core.utils.telegram_api.random.uniform", lambda a, b: 0.0)
    wrapper = TelegramAPIWrapper(max_retries=2)
    initial = asyncio.Event()
    attempts = 0

    async def send_cached_media():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            initial.set()
            raise FloodWait(value=0.3)
        return "delivered"

    async def send_message():
        return "unrelated delivered"

    main = asyncio.create_task(wrapper.call_api(send_cached_media, chat_id=1))
    try:
        await asyncio.wait_for(initial.wait(), timeout=2)
        # Give the first task a scheduling turn to exit its permit.
        await asyncio.sleep(0)
        assert (await manager.get_metrics("telegram_send"))["current_active"] == 0
        started = time.monotonic()
        assert await asyncio.wait_for(
            wrapper.call_api(send_message, chat_id=2), timeout=0.2
        ) == "unrelated delivered"
        assert time.monotonic() - started < 0.25
        assert await asyncio.wait_for(main, timeout=2) == "delivered"
        assert attempts == 2
        assert (await manager.get_metrics("telegram_send"))["current_active"] == 0
        assert wrapper.flood_metrics()["flood_wait_events"] == 1
    finally:
        if not main.done():
            main.cancel()
        await asyncio.gather(main, return_exceptions=True)


@pytest.mark.asyncio
async def test_shared_chat_cooldown_stops_retry_stampede_without_using_slots(monkeypatch):
    manager = SemaphoreManager({"telegram_send": 2})
    monkeypatch.setattr("core.utils.telegram_api.semaphore_manager", manager)
    monkeypatch.setattr("core.utils.telegram_api.random.uniform", lambda a, b: 0.0)
    wrapper = TelegramAPIWrapper(max_retries=2)
    first_flooded = asyncio.Event()
    attempted = []

    async def send_message(marker):
        attempted.append(marker)
        if marker == "first" and attempted.count("first") == 1:
            first_flooded.set()
            raise FloodWait(value=0.2)
        return marker

    first = asyncio.create_task(wrapper.call_api(send_message, "first", chat_id=44))
    try:
        await asyncio.wait_for(first_flooded.wait(), timeout=2)
        await asyncio.sleep(0)
        second = asyncio.create_task(wrapper.call_api(send_message, "second", chat_id=44))
        await asyncio.sleep(0.05)
        assert attempted == ["first"]
        assert (await manager.get_metrics("telegram_send"))["current_active"] == 0
        assert await asyncio.wait_for(second, timeout=2) == "second"
        assert await asyncio.wait_for(first, timeout=2) == "first"
        assert attempted.count("first") == 2
        assert attempted.count("second") == 1
    finally:
        if not first.done():
            first.cancel()
        await asyncio.gather(first, return_exceptions=True)


@pytest.mark.asyncio
async def test_exhausted_retries_preserve_original_flood_wait_and_leave_permits(monkeypatch):
    manager = SemaphoreManager({"telegram_send": 1})
    monkeypatch.setattr("core.utils.telegram_api.semaphore_manager", manager)
    monkeypatch.setattr("core.utils.telegram_api.random.uniform", lambda a, b: 0.0)
    wrapper = TelegramAPIWrapper(max_retries=1)

    async def send_message():
        raise FloodWait(value=15)

    with pytest.raises(FloodWait) as err:
        await wrapper.call_api(send_message, chat_id=100)
    assert err.value.value == 15
    assert (await manager.get_metrics("telegram_send"))["current_active"] == 0
    assert manager.get_semaphore("telegram_send")._value == 1


@pytest.mark.asyncio
async def test_cancel_during_flood_wait_does_not_leak_slot(monkeypatch):
    manager = SemaphoreManager({"telegram_send": 1})
    monkeypatch.setattr("core.utils.telegram_api.semaphore_manager", manager)
    monkeypatch.setattr("core.utils.telegram_api.random.uniform", lambda a, b: 0.0)
    wrapper = TelegramAPIWrapper(max_retries=2)
    first_flood = asyncio.Event()

    async def send_message():
        first_flood.set()
        raise FloodWait(value=30)

    task = asyncio.create_task(wrapper.call_api(send_message, chat_id=42))
    await asyncio.wait_for(first_flood.wait(), timeout=2)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await manager.get_metrics("telegram_send"))["current_active"] == 0
    assert manager.get_semaphore("telegram_send")._value == 1


@pytest.mark.asyncio
async def test_http_500_backoff_happens_after_semaphore_release(monkeypatch):
    manager = SemaphoreManager({"telegram_send": 1})
    monkeypatch.setattr("core.utils.telegram_api.semaphore_manager", manager)
    monkeypatch.setattr("core.utils.telegram_api.random.uniform", lambda a, b: 0.0)
    class FakeRpcError(Exception):
        CODE = 500
    monkeypatch.setattr("core.utils.telegram_api.RPCError", FakeRpcError)
    wrapper = TelegramAPIWrapper(max_retries=2, base_delay=0.3)
    failed = asyncio.Event()
    tries = 0

    async def send_message():
        nonlocal tries
        tries += 1
        if tries == 1:
            failed.set()
            raise FakeRpcError()
        return "sent"

    async def send_other():
        return "free"

    task = asyncio.create_task(wrapper.call_api(send_message, chat_id=1))
    try:
        await asyncio.wait_for(failed.wait(), timeout=2)
        await asyncio.sleep(0)
        assert (await manager.get_metrics("telegram_send"))["current_active"] == 0
        assert await asyncio.wait_for(
            wrapper.call_api(send_other, chat_id=2), timeout=0.15
        ) == "free"
        assert await asyncio.wait_for(task, timeout=2) == "sent"
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_flood_cooldown_scope_storage_is_bounded():
    wrapper = TelegramAPIWrapper()
    wrapper.MAX_COOLDOWN_SCOPES = 5  # 3 reserved domain slots, 2 user slots
    wrapper._record_flood(("telegram_send", 1), 100)
    wrapper._record_flood(("telegram_send", 2), 100)
    wrapper._record_flood(("telegram_send", 3), 100)
    assert len(wrapper._cooldowns) == 5
    assert wrapper.flood_metrics()["cooldown_scope_overflows"] == 1
    assert wrapper._remaining_delay(("telegram_send", 9)) > 0
    assert wrapper._remaining_delay(("telegram_send", 1)) > 0
