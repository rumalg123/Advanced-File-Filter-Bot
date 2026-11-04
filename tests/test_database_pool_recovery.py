"""Failed/cancelled startup must never leave a usable partial database topology."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock

import pytest
from pymongo.errors import ConnectionFailure

from core.database.pool import DatabaseConnectionPool
from core.database.multi_pool import MultiDatabaseManager


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',[ConnectionFailure('QA unavailable'),asyncio.CancelledError()])
async def test_pool_initialization_failure_closes_client_and_allows_retry(monkeypatch,failure):
    bad=Mock();bad.admin.command=AsyncMock(side_effect=failure)
    good=Mock();good.admin.command=AsyncMock(return_value={'ok':1})
    bad.__getitem__=Mock(return_value=object())
    good.__getitem__=Mock(return_value=object())
    factory=Mock(side_effect=[bad,good])
    monkeypatch.setattr('core.database.pool.AsyncIOMotorClient',factory)
    monkeypatch.setattr('core.database.pool.asyncio.sleep',AsyncMock())
    pool=DatabaseConnectionPool.create_isolated()
    with pytest.raises(type(failure)):
        await pool.initialize('mongodb://qa-only','fixture')
    assert pool._client is None and pool._database is None
    bad.close.assert_called_once()
    await pool.initialize('mongodb://qa-only','fixture')
    assert pool.client is good
    good.admin.command.assert_awaited_once_with('ping')
    await pool.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',[ConnectionFailure('QA second source unavailable'),asyncio.CancelledError()])
async def test_multi_pool_partial_startup_rolls_back_every_opened_pool(monkeypatch,failure):
    first=SimpleNamespace(initialize=AsyncMock(),close=AsyncMock())
    second=SimpleNamespace(initialize=AsyncMock(side_effect=failure),close=AsyncMock())
    third=SimpleNamespace(initialize=AsyncMock(),close=AsyncMock())
    fourth=SimpleNamespace(initialize=AsyncMock(),close=AsyncMock())
    factory=Mock(side_effect=[first,second,third,fourth])
    monkeypatch.setattr(DatabaseConnectionPool,'create_isolated',factory)
    manager=object.__new__(MultiDatabaseManager);manager.__init__()
    manager._update_database_stats_with_circuit_breaker=AsyncMock()
    with pytest.raises(type(failure)):
        await manager.initialize(['mongodb://first','mongodb://second'],['qa-a','qa-b'])
    assert manager.databases==[]
    first.close.assert_awaited_once()
    second.close.assert_awaited_once()
    await manager.initialize(['mongodb://first','mongodb://second'],['qa-a','qa-b'])
    assert len(manager.databases)==2
    assert [d.pool for d in manager.databases]==[third,fourth]
