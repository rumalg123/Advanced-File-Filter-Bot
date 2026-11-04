"""Daily quotas across both ledger modes, limits, partial failure and rollover."""
import asyncio
from datetime import date
from types import SimpleNamespace

import pytest

from ban_support import Cache
from config.settings import settings
from favorites_recent_support import storage
from repositories.user import User, UserRepository

pytestmark = pytest.mark.integration


async def fixture(storage, monkeypatch, ledger, limit=3):
    _, pool, db = storage
    day = {'value': date(2026, 10, 30)}
    monkeypatch.setattr('repositories.user.quota_day_utc', lambda *args: day['value'])
    monkeypatch.setattr('repositories.user._channel_config', SimpleNamespace(get_admin_list=lambda: [1]))
    monkeypatch.setattr(settings.features, 'feature_quota_delivery_ledger', ledger)
    repo = UserRepository(pool, Cache(), daily_limit=limit)
    await db.users.insert_one(repo._entity_to_dict(User(id=42, name='QA', last_retrieval_date=day['value'])))
    return repo, db, day


@pytest.mark.asyncio
@pytest.mark.parametrize('ledger', [True, False])
@pytest.mark.parametrize('limit', [0, 3])
async def test_concurrent_download_reservations_stop_at_limit(storage, monkeypatch, ledger, limit):
    repo, db, _ = await fixture(storage, monkeypatch, ledger, limit)
    results = await asyncio.gather(*[repo.reserve_quota_atomic(42, 1, limit) for _ in range(16)])
    assert sum(ok for ok, _, _ in results) == limit
    assert (await db.users.find_one({'_id': 42}))['daily_retrieval_count'] == limit


@pytest.mark.asyncio
@pytest.mark.parametrize('ledger', [True, False])
async def test_known_unsent_file_refunds_only_unused_slot(storage, monkeypatch, ledger):
    repo, db, _ = await fixture(storage, monkeypatch, ledger)
    ok, reservation, _ = await repo.reserve_quota_atomic(42, 2, 3)
    assert ok
    assert await repo.release_quota(42, reservation-1)
    stored = await db.users.find_one({'_id': 42})
    assert stored['daily_retrieval_count'] == 1
    if ledger:
        assert stored['quota_delivery_ledger'][0]['status'] == 'settled'
        assert stored['quota_delivery_ledger'][0]['confirmed_count'] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('ledger', [True, False])
async def test_utc_rollover_does_not_apply_yesterdays_refund(storage, monkeypatch, ledger):
    repo, db, day = await fixture(storage, monkeypatch, ledger)
    _, old, _ = await repo.reserve_quota_atomic(42, 1, 3)
    day['value'] = date(2026, 10, 31)
    ok, new, _ = await repo.reserve_quota_atomic(42, 1, 3)
    assert ok and (await db.users.find_one({'_id': 42}))['daily_retrieval_count'] == 1
    assert not await repo.release_quota(42, old)
    assert (await db.users.find_one({'_id': 42}))['daily_retrieval_count'] == 1
    assert await repo.release_quota(42, new)
    assert (await db.users.find_one({'_id': 42}))['daily_retrieval_count'] == 0
