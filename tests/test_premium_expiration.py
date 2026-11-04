"""Cleanup must not revoke fresh grants or alter consumed quota."""
from datetime import UTC, datetime, timedelta

import pytest

from ban_support import Cache
from favorites_recent_support import storage
from repositories.user import User, UserRepository

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['optimized', 'fallback', 'single'])
async def test_cleanup_candidate_renewed_before_write_keeps_premium(storage, path):
    _, pool, db = storage
    repo = UserRepository(pool, Cache())
    old = User(id=42, name='QA', is_premium=True,
               premium_expiry_date=datetime.now(UTC)-timedelta(days=1))
    await db.users.insert_one(repo._entity_to_dict(old))
    # A grant arrives after the expiration candidate was read.
    future = datetime.now(UTC)+timedelta(days=7)
    await db.users.update_one({'_id': 42}, {'$set': {'premium_expiry_date': future}})
    if path == 'optimized':
        await repo.batch_ops._batch_expire_premium_users([42])
    elif path == 'fallback':
        await repo._batch_expire_premium([42])
    else:
        assert (await UserRepository.check_and_update_premium_status.__wrapped__(repo, old))[0]
    stored = await db.users.find_one({'_id': 42})
    assert stored['is_premium'] is True
    assert stored['premium_expiry_date'] > datetime.now()


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['optimized', 'fallback', 'single'])
async def test_expiration_preserves_consumed_download_quota(storage, path):
    _, pool, db = storage
    repo = UserRepository(pool, Cache())
    old = User(id=42, name='QA', is_premium=True, daily_retrieval_count=3,
               premium_expiry_date=datetime.now(UTC)-timedelta(seconds=1))
    await db.users.insert_one(repo._entity_to_dict(old))
    if path == 'optimized':
        await repo.batch_ops._batch_expire_premium_users([42])
    elif path == 'fallback':
        await repo._batch_expire_premium([42])
    else:
        assert not (await UserRepository.check_and_update_premium_status.__wrapped__(repo, old))[0]
    stored = await db.users.find_one({'_id': 42})
    assert not stored['is_premium']
    assert stored['premium_expiry_date'] is None
    assert stored['daily_retrieval_count'] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('optimized', [True, False])
async def test_cleanup_handles_invalid_legacy_expiry_without_skipping_other_users(storage, optimized):
    _, pool, db = storage
    repo = UserRepository(pool, Cache())
    if not optimized:
        repo.batch_ops = None
    now = datetime.now(UTC)
    await db.users.insert_many([
        {'_id': 41, 'name': 'Active', 'is_premium': True, 'premium_expiry_date': (now+timedelta(days=5)).isoformat()},
        {'_id': 42, 'name': 'Expired', 'is_premium': True, 'premium_expiry_date': now-timedelta(days=1)},
        {'_id': 43, 'name': 'Malformed', 'is_premium': True, 'premium_expiry_date': 'not-a-date'},
        {'_id': 44, 'name': 'Missing', 'is_premium': True},
    ])
    result = await repo.cleanup_expired_premium()
    assert result == {'checked_count': 4, 'expired_count': 3, 'still_active_count': 1}
    assert (await db.users.find_one({'_id': 41}))['is_premium']
    assert await db.users.count_documents({'is_premium': True}) == 1
