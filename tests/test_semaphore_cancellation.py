"""PH-019 regression tests: semaphore permits and metrics under cancellation.

No production services or databases are used; tests exercise asyncio state.
PH-020 live semaphore reconfiguration is deliberately out of scope.
"""
import asyncio

import pytest

from core.concurrency.semaphore_manager import SemaphoreManager


def new_manager(limit=1):
    return SemaphoreManager({"ph019_test": limit})


@pytest.mark.asyncio
async def test_cancellation_before_context_entry_does_not_touch_metrics():
    manager = new_manager()
    gate = asyncio.Event()

    async def never_enter():
        await gate.wait()
        async with manager.acquire("ph019_test"):
            raise AssertionError("cancelled task entered the semaphore")

    task = asyncio.create_task(never_enter())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    metrics = await manager.get_metrics("ph019_test")
    assert metrics["current_active"] == 0
    assert metrics["queue_length"] == 0
    assert metrics["total_requests"] == 0
    assert manager.get_semaphore("ph019_test")._value == 1


@pytest.mark.asyncio
async def test_cancellation_while_waiting_for_permit_preserves_active_count():
    manager = new_manager()
    executed = []

    async def contender():
        async with manager.acquire("ph019_test", operation_id="cancelled"):
            executed.append("entered")

    async with manager.acquire("ph019_test", operation_id="holder"):
        waiter = asyncio.create_task(contender())
        await asyncio.sleep(0)
        waiting = await manager.get_metrics("ph019_test")
        assert waiting["current_active"] == 1
        assert waiting["queue_length"] == 1
        assert waiting["total_requests"] == 1
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        after_cancel = await manager.get_metrics("ph019_test")
        assert after_cancel["current_active"] == 1
        assert after_cancel["queue_length"] == 0
        assert after_cancel["total_requests"] == 1
        assert executed == []

    ended = await manager.get_metrics("ph019_test")
    assert ended["current_active"] == ended["queue_length"] == 0
    assert ended["total_requests"] == 1
    assert ended["peak_concurrent"] == 1
    assert manager.get_semaphore("ph019_test")._value == 1


@pytest.mark.asyncio
async def test_cancellation_before_waiter_is_registered_leaves_no_residue():
    manager = new_manager()
    async def contender():
        async with manager.acquire("ph019_test"):
            raise AssertionError("unreachable")

    async with manager._lock:
        task = asyncio.create_task(contender())
        await asyncio.sleep(0)
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    data = await manager.get_metrics("ph019_test")
    assert data["current_active"] == 0
    assert data["queue_length"] == 0
    assert data["total_requests"] == 0


@pytest.mark.asyncio
async def test_cancellation_after_semaphore_admission_but_before_metric_registration():
    manager = new_manager()
    sem = manager.get_semaphore("ph019_test")
    # Hold a raw permit to orchestrate the exact admission window.
    await sem.acquire()
    assert sem.locked()

    async def contender():
        async with manager.acquire("ph019_test"):
            raise AssertionError("cancelled before metrics were registered")

    task = asyncio.create_task(contender())
    await asyncio.sleep(0)
    assert (await manager.get_metrics("ph019_test"))["queue_length"] == 1

    async with manager._lock:
        sem.release()  # wake contender into semaphore before its metrics lock
        await asyncio.sleep(0)
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    data = await manager.get_metrics("ph019_test")
    assert data["current_active"] == 0
    assert data["queue_length"] == 0
    assert data["total_requests"] == 0
    assert sem._value == 1


@pytest.mark.asyncio
async def test_cancellation_inside_acquired_block_releases_once_and_propagates():
    manager = new_manager()
    entered = asyncio.Event()

    async def operation():
        async with manager.acquire("ph019_test", operation_id="active"):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(operation())
    await entered.wait()
    assert (await manager.get_metrics("ph019_test"))["current_active"] == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    data = await manager.get_metrics("ph019_test")
    assert data["current_active"] == data["queue_length"] == 0
    assert data["total_requests"] == data["peak_concurrent"] == 1
    assert manager._metrics["ph019_test"].start_times == {}
    assert manager.get_semaphore("ph019_test")._value == 1


@pytest.mark.asyncio
async def test_normal_exception_and_timeout_release_metrics_and_permits():
    manager = new_manager()
    with pytest.raises(ValueError):
        async with manager.acquire("ph019_test", operation_id="raising"):
            raise ValueError("expected")
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            async with manager.acquire("ph019_test", operation_id="timed"):
                await asyncio.Event().wait()
    async with manager.acquire("ph019_test", operation_id="next"):
        assert (await manager.get_metrics("ph019_test"))["current_active"] == 1
    data = await manager.get_metrics("ph019_test")
    assert data["total_requests"] == 3
    assert data["peak_concurrent"] == 1
    assert data["current_active"] == data["queue_length"] == 0
    assert manager.get_semaphore("ph019_test")._value == 1


@pytest.mark.asyncio
async def test_contention_and_cancelled_waiters_never_create_negative_or_phantom_active():
    manager = new_manager(limit=2)
    started = asyncio.Event()
    release = asyncio.Event()
    current = 0
    peak = 0
    first_two = 0

    async def operation(index):
        nonlocal current, peak, first_two
        async with manager.acquire("ph019_test", operation_id=f"job-{index}"):
            current += 1
            peak = max(peak, current)
            first_two += 1
            if first_two >= 2:
                started.set()
            try:
                await release.wait()
            finally:
                current -= 1

    tasks = [asyncio.create_task(operation(i)) for i in range(12)]
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        await asyncio.sleep(0)
        metrics = await manager.get_metrics("ph019_test")
        assert metrics["current_active"] == 2
        assert metrics["queue_length"] == 10

        for task in tasks[2:9]:
            task.cancel()
        await asyncio.gather(*tasks[2:9], return_exceptions=True)
        remaining = await manager.get_metrics("ph019_test")
        assert remaining["current_active"] == 2
        assert remaining["queue_length"] == 3

        release.set()
        await asyncio.wait_for(
            asyncio.gather(tasks[0], tasks[1], *tasks[9:]), timeout=2
        )
        after = await manager.get_metrics("ph019_test")
        assert current == 0
        assert peak <= 2
        assert after["peak_concurrent"] == 2
        assert after["total_requests"] == 5
        assert after["current_active"] == after["queue_length"] == 0
        assert manager.get_semaphore("ph019_test")._value == 2
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_auto_generated_operation_ids_do_not_collide_at_sub_millisecond_rate():
    manager = new_manager(limit=3)
    async with manager.acquire("ph019_test"):
        async with manager.acquire("ph019_test"):
            async with manager.acquire("ph019_test"):
                active_ids = manager._metrics["ph019_test"].start_times
                assert len(active_ids) == 3
                assert (await manager.get_metrics("ph019_test"))["current_active"] == 3
    assert manager._metrics["ph019_test"].start_times == {}
    assert (await manager.get_metrics("ph019_test"))["current_active"] == 0
