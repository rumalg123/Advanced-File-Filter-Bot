"""PH-020: live resizing must preserve one in-flight permit budget.

No MongoDB/Redis/Telegram access. Exercises the exact lifecycle of
holder operations, pending tasks, cancellation and repeated limit changes.
"""
import asyncio

import pytest

from core.concurrency.semaphore_manager import ResizableSemaphore, SemaphoreManager


def new_manager(limit=3):
    return SemaphoreManager({"ph020_test": limit})


async def wait_for_count(manager, *, active=None, waiting=None):
    """Avoid using timing sleeps as an assertion of scheduling completion."""
    for _ in range(200):
        m = await manager.get_metrics("ph020_test")
        if (active is None or m["current_active"] == active) and (
            waiting is None or m["queue_length"] == waiting
        ):
            return m
        await asyncio.sleep(0)
    raise AssertionError(f"Metrics did not converge: {await manager.get_metrics('ph020_test')}")


@pytest.mark.asyncio
async def test_shrinking_below_active_keeps_all_holders_and_blocks_new_work():
    manager = new_manager(3)
    semaphore = manager.get_semaphore("ph020_test")
    waiting_entered = asyncio.Event()
    release_waiter = asyncio.Event()

    async def contender():
        async with manager.acquire("ph020_test", operation_id="next"):
            waiting_entered.set()
            await release_waiter.wait()

    try:
        async with manager.acquire("ph020_test", operation_id="holder-1"):
            async with manager.acquire("ph020_test", operation_id="holder-2"):
                async with manager.acquire("ph020_test", operation_id="holder-3"):
                    assert (await manager.get_metrics("ph020_test"))["current_active"] == 3
                    assert await manager.update_limit("ph020_test", 1)
                    assert manager.get_semaphore("ph020_test") is semaphore
                    assert semaphore.limit == 1
                    assert semaphore._value == -2
                    task = asyncio.create_task(contender())
                    await wait_for_count(manager, active=3, waiting=1)
                # Holder 3 exits; still 2 running against new limit of 1.
                assert semaphore._value == -1
                assert not waiting_entered.is_set()
                await wait_for_count(manager, active=2, waiting=1)
            # Holder 2 exits; holder 1 still consumes the new single permit.
            assert semaphore._value == 0
            assert not waiting_entered.is_set()
            await wait_for_count(manager, active=1, waiting=1)

        # All old holders finish: exactly one waiting request can now start.
        await asyncio.wait_for(waiting_entered.wait(), timeout=2)
        await wait_for_count(manager, active=1, waiting=0)
        release_waiter.set()
        await asyncio.wait_for(task, timeout=2)
        assert semaphore._value == 1
        final = await manager.get_metrics("ph020_test")
        assert final["current_active"] == final["queue_length"] == 0
        assert final["max_concurrent"] == 1
    finally:
        release_waiter.set()
        if "task" in locals() and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_growing_limit_wakes_exact_capacity_without_replacing_waiters():
    manager = new_manager(1)
    original = manager.get_semaphore("ph020_test")
    all_entered = asyncio.Event()
    release = asyncio.Event()
    entered = []

    async def contender(index):
        async with manager.acquire("ph020_test", operation_id=f"waiter-{index}"):
            entered.append(index)
            if len(entered) == 2:
                all_entered.set()
            await release.wait()

    try:
        async with manager.acquire("ph020_test", operation_id="first"):
            tasks = [asyncio.create_task(contender(i)) for i in range(3)]
            await wait_for_count(manager, active=1, waiting=3)
            assert await manager.update_limit("ph020_test", 3)
            assert manager.get_semaphore("ph020_test") is original
            await asyncio.wait_for(all_entered.wait(), timeout=2)
            assert entered == [0, 1]
            m = await wait_for_count(manager, active=3, waiting=1)
            assert m["max_concurrent"] == 3
        # Third waiter is now admitted when the original holder exits.
        await wait_for_count(manager, active=3, waiting=0)
        release.set()
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=2)
        m = await manager.get_metrics("ph020_test")
        assert m["current_active"] == m["queue_length"] == 0
        assert m["peak_concurrent"] == 3
        assert original._value == 3
    finally:
        release.set()
        for task in locals().get("tasks", []):
            if not task.done():
                task.cancel()
        await asyncio.gather(*locals().get("tasks", []), return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelled_waiter_during_shrunk_debt_does_not_leak_permits():
    manager = new_manager(2)
    original = manager.get_semaphore("ph020_test")

    async def waiting_task():
        async with manager.acquire("ph020_test"):
            raise AssertionError("Waiter must never enter")

    async with manager.acquire("ph020_test"):
        async with manager.acquire("ph020_test"):
            task = asyncio.create_task(waiting_task())
            await wait_for_count(manager, waiting=1)
            assert await manager.update_limit("ph020_test", 1)
            assert original._value == -1
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            m = await manager.get_metrics("ph020_test")
            assert m["queue_length"] == 0
            assert m["current_active"] == 2
            assert original._value == -1
        assert original._value == 0
    assert original._value == 1
    m = await manager.get_metrics("ph020_test")
    assert m["current_active"] == m["queue_length"] == 0


@pytest.mark.asyncio
async def test_repeated_shrink_grow_with_real_waiters_never_overadmits():
    manager = new_manager(2)
    entered = []
    release = asyncio.Event()
    current = 0
    max_seen = 0

    async def contender(i):
        nonlocal current, max_seen
        async with manager.acquire("ph020_test", operation_id=f"t-{i}"):
            current += 1
            max_seen = max(max_seen, current)
            # Every NEW admission must obey the current limit; an existing
            # running set may temporarily exceed the limit after shrink.
            assert current <= manager.limits["ph020_test"]
            entered.append(i)
            try:
                await release.wait()
            finally:
                current -= 1

    tasks = [asyncio.create_task(contender(i)) for i in range(20)]
    try:
        await wait_for_count(manager, active=2, waiting=18)
        assert await manager.update_limit("ph020_test", 1)
        assert await manager.update_limit("ph020_test", 4)
        await wait_for_count(manager, active=4, waiting=16)
        assert await manager.update_limit("ph020_test", 2)
        assert await manager.update_limit("ph020_test", 3)
        # 4 active are inherited from the previous larger limit; no newly
        # admitted task may enter until active falls below 3.
        assert (await manager.get_metrics("ph020_test"))["current_active"] == 4
        for task in tasks[4:10]:
            task.cancel()
        await asyncio.gather(*tasks[4:10], return_exceptions=True)
        waiting = await manager.get_metrics("ph020_test")
        assert waiting["current_active"] == 4
        assert waiting["queue_length"] == 10
        release.set()
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=3)
        assert len(entered) == 14
        assert len(set(entered)) == 14
        assert max_seen <= 4
        final = await manager.get_metrics("ph020_test")
        assert final["current_active"] == final["queue_length"] == 0
        assert manager.get_semaphore("ph020_test")._value == 3
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_invalid_limits_never_mutate_live_semaphore_or_metrics():
    manager = new_manager(2)
    sem = manager.get_semaphore("ph020_test")
    for invalid in (0, -1, True, 1.2, "5", None):
        assert await manager.update_limit("ph020_test", invalid) is False
        assert manager.get_semaphore("ph020_test") is sem
        assert sem.limit == 2
    assert (await manager.get_metrics("ph020_test"))["max_concurrent"] == 2
    assert manager.limits["ph020_test"] == 2


@pytest.mark.asyncio
async def test_zero_waiters_reconfigure_idle_domain_and_unknown_domain():
    manager = new_manager(1)
    sem = manager.get_semaphore("ph020_test")
    assert await manager.update_limit("ph020_test", 5)
    assert sem._value == 5 and sem.limit == 5
    assert await manager.update_limit("ph020_test", 1)
    assert sem._value == 1 and sem.limit == 1
    assert await manager.update_limit("completely-new", 4)
    new_sem = manager.get_semaphore("completely-new")
    assert isinstance(new_sem, ResizableSemaphore)
    assert new_sem.limit == new_sem._value == 4
    assert (await manager.get_metrics("completely-new"))["max_concurrent"] == 4
    assert manager.get_semaphore("ph020_test") is sem


@pytest.mark.asyncio
async def test_timeout_after_resize_does_not_decrement_unacquired_admission():
    manager = new_manager(1)
    sem = manager.get_semaphore("ph020_test")
    async with manager.acquire("ph020_test"):
        assert await manager.update_limit("ph020_test", 1)
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.02):
                async with manager.acquire("ph020_test"):
                    raise AssertionError("cannot enter while occupied")
        values = await manager.get_metrics("ph020_test")
        assert values["queue_length"] == 0
        assert values["current_active"] == 1
        assert sem._value == 0
    assert sem._value == 1
