"""Connection mutations must preserve concurrent changes in disposable MongoDB."""
import asyncio

import pytest

from core.services.connection import ConnectionService
from repositories.connection import ConnectionRepository
from test_repository_crud_contracts import Cache, mongo_pool  # noqa: F401


@pytest.mark.asyncio
async def test_stale_activation_keeps_current_connection(mongo_pool):
    repo = ConnectionRepository(mongo_pool, Cache())
    await repo.add_connection('12', '-1001')
    success, _ = await ConnectionService(repo, []).set_active_connection(12, '-9999')
    assert not success
    assert await repo.get_active_connection('12') == '-1001'


@pytest.mark.asyncio
async def test_concurrent_adds_preserve_every_group_and_deduplicate(mongo_pool):
    repo = ConnectionRepository(mongo_pool, Cache())
    groups = [str(-1000 - index) for index in range(24)]
    await repo.add_connection('12', '-999')
    results = await asyncio.gather(*(repo.add_connection('12', group) for group in groups))
    assert all(results)
    assert set(await repo.get_all_connections('12')) == set(groups + ['-999'])
    results = await asyncio.gather(*(repo.add_connection('12', '-2000') for _ in range(12)))
    assert sum(results) == 1
    assert (await repo.get_all_connections('12')).count('-2000') == 1


@pytest.mark.asyncio
async def test_remove_and_add_never_resurrect_or_lose_connections(mongo_pool):
    repo = ConnectionRepository(mongo_pool, Cache())
    await repo.add_connection('12', '-1001')
    await repo.add_connection('12', '-1002')
    results = await asyncio.gather(
        repo.delete_connection('12', '-1001'), repo.add_connection('12', '-1003')
    )
    assert all(results)
    assert set(await repo.get_all_connections('12')) == {'-1002', '-1003'}
    assert await repo.get_active_connection('12') in {'-1002', '-1003'}
    assert not await repo.make_active('99', '-1003')
    assert not await repo.delete_connection('99', '-1003')


@pytest.mark.asyncio
async def test_activation_and_removal_cannot_leave_a_dangling_active_group(mongo_pool):
    repo = ConnectionRepository(mongo_pool, Cache())
    for _ in range(12):
        await repo.add_connection('12', '-1001')
        await repo.add_connection('12', '-1002')
        await asyncio.gather(repo.make_active('12', '-1001'), repo.delete_connection('12', '-1001'))
        assert await repo.get_all_connections('12') == ['-1002']
        assert await repo.get_active_connection('12') == '-1002'
