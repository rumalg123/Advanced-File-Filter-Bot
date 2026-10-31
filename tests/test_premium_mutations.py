"""Premium mutations must use current MongoDB state and preserve active grants."""
import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from ban_support import Cache, prime
from favorites_recent_support import storage
from repositories.user import User, UserRepository
from core.utils.validators import normalize_expiry_date

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.parametrize('requested,stored,cached', [
    (True, False, True), (False, True, False), (True, True, False),
])
async def test_premium_mutations_ignore_stale_profile(storage, requested, stored, cached):
    _, pool, db = storage
    cache = Cache()
    repo = UserRepository(pool, cache)
    expiry = datetime.now(UTC) + timedelta(days=9)
    actual = User(id=42, name='QA', is_premium=stored,
                  premium_expiry_date=expiry if stored else None)
    await db.users.insert_one(repo._entity_to_dict(actual))
    prime(repo, cache, User(id=42, name='Old profile', is_premium=cached,
                           premium_expiry_date=expiry if cached else None))

    success, _, _ = await repo.update_premium_status(42, requested, duration_days=1)

    assert success is (requested != stored)
    doc = await db.users.find_one({'_id': 42})
    assert doc['is_premium'] is requested
    if requested and stored:
        assert datetime.fromisoformat(doc['premium_expiry_date']) == expiry


@pytest.mark.asyncio
@pytest.mark.parametrize('expiry', [None, 'expired'])
async def test_expired_raw_flag_can_receive_new_grant(storage, expiry):
    _, pool, db = storage
    repo = UserRepository(pool, Cache())
    user = User(id=42, name='QA', is_premium=True,
                premium_expiry_date=datetime.now(UTC)-timedelta(days=1) if expiry else None)
    await db.users.insert_one(repo._entity_to_dict(user))

    success, _, granted = await repo.update_premium_status(42, True, duration_days=7)

    assert success
    assert granted.premium_expiry_date > datetime.now(UTC)
    assert granted.premium_expiry_date-granted.premium_activation_date == timedelta(days=7)
    assert (await db.users.find_one({'_id': 42}))['is_premium'] is True


@pytest.mark.asyncio
async def test_concurrent_grants_have_one_winner(storage, monkeypatch):
    _, pool, db = storage
    repo = UserRepository(pool, Cache())
    await db.users.insert_one(repo._entity_to_dict(User(id=42, name='QA')))
    original = repo.get_user
    arrived = 0
    ready = asyncio.Event()

    async def snapshot(*args, **kwargs):
        nonlocal arrived
        user = await original(*args, **kwargs)
        arrived += 1
        if arrived == 12:
            ready.set()
        await asyncio.wait_for(ready.wait(), 5)
        return user

    monkeypatch.setattr(repo, 'get_user', snapshot)
    results = await asyncio.gather(*[
        repo.update_premium_status(42, True, duration_days=i+1) for i in range(12)
    ])
    winners = [user for success, _, user in results if success]
    assert len(winners) == 1
    stored = await original(42, use_cache=False)
    assert normalize_expiry_date(stored.premium_expiry_date) == winners[0].premium_expiry_date


@pytest.mark.asyncio
@pytest.mark.parametrize('days', [0, -1, True, 1.5, 10**12])
async def test_invalid_grant_duration_leaves_document_unchanged(storage, days):
    _, pool, db = storage
    repo = UserRepository(pool, Cache())
    await db.users.insert_one(repo._entity_to_dict(User(id=42, name='QA')))
    before = await db.users.find_one({'_id': 42})
    assert not (await repo.update_premium_status(42, True, duration_days=days))[0]
    assert await db.users.find_one({'_id': 42}) == before


@pytest.mark.asyncio
async def test_premium_write_failure_is_reported_without_claiming_success(storage, monkeypatch):
    _, pool, db = storage
    repo = UserRepository(pool, Cache())
    await db.users.insert_one(repo._entity_to_dict(User(id=42, name='QA')))
    original = pool.execute_with_retry

    async def unavailable(operation, *args, **kwargs):
        if operation.__name__ == 'find_one_and_update':
            raise ConnectionError('Injected local write failure')
        return await original(operation, *args, **kwargs)

    monkeypatch.setattr(pool, 'execute_with_retry', unavailable)
    success, message, _ = await repo.update_premium_status(42, True)
    assert not success and 'Failed' in message
    assert not (await db.users.find_one({'_id': 42}))['is_premium']
