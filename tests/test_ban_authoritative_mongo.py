from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from favorites_recent_support import storage
from ban_support import user_repository,prime,User,UserStatus

pytestmark=pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.parametrize('banned',[True,False])
async def test_access_uses_authoritative_status_instead_of_stale_entity_cache(storage,monkeypatch,banned):
    status=UserStatus.BANNED if banned else UserStatus.ACTIVE
    repo,cache,_=await user_repository(storage,monkeypatch,status=status)
    prime(repo,cache,User(id=42,name='stale',status=UserStatus.ACTIVE if banned else UserStatus.BANNED))
    allowed,_=await repo.can_retrieve_file(42)
    assert allowed is (not banned)


@pytest.mark.asyncio
async def test_authoritative_user_read_does_not_depend_on_redis(storage,monkeypatch):
    repo,cache,_=await user_repository(storage,monkeypatch,status=UserStatus.BANNED)
    cache.get=AsyncMock(side_effect=ConnectionError('QA Redis unavailable'))
    assert (await repo.get_user(42,use_cache=False)).status==UserStatus.BANNED
    cache.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_authorization_database_outage_never_uses_cached_active_user(storage,monkeypatch):
    repo,cache,_=await user_repository(storage,monkeypatch)
    prime(repo,cache,User(id=42,name='stale'))
    repo.db_pool.execute_with_retry=AsyncMock(side_effect=ConnectionError('private fixture backend error'))
    allowed,reason=await repo.can_retrieve_file(42)
    assert not allowed and 'temporarily unavailable' in reason.lower()
    assert 'private fixture' not in reason


@pytest.mark.asyncio
@pytest.mark.parametrize('operation',['ban','unban'])
async def test_ban_mutations_read_current_status_even_when_cache_disagrees(storage,monkeypatch,operation):
    initial=UserStatus.ACTIVE if operation=='ban' else UserStatus.BANNED
    repo,cache,db=await user_repository(storage,monkeypatch,status=initial)
    prime(repo,cache,User(id=42,name='stale',status=UserStatus.BANNED if operation=='ban' else UserStatus.ACTIVE))
    result=await (repo.ban_user(42,'QA') if operation=='ban' else repo.unban_user(42))
    assert result[0] is True
    assert (await db.users.find_one({'_id':42}))['status']==('banned' if operation=='ban' else 'active')


@pytest.mark.asyncio
async def test_ban_unban_preserve_premium_download_quota_and_lifetime_requests(storage,monkeypatch):
    repo,cache,db=await user_repository(storage,monkeypatch)
    await db.users.update_one({'_id':42},{'$set':{'is_premium':True,'daily_retrieval_count':7,
        'warning_count':3,'daily_request_count':2,'total_requests':100}})
    assert (await repo.ban_user(42,'QA reason'))[0]
    assert not (await repo.ban_user(42,'replacement reason'))[0]
    assert (await repo.unban_user(42))[0]
    assert not (await repo.unban_user(42))[0]
    doc=await db.users.find_one({'_id':42})
    assert doc['status']=='active' and doc['ban_reason'] is None
    assert doc['warning_count']==doc['daily_request_count']==0
    assert doc['is_premium'] and doc['daily_retrieval_count']==7 and doc['total_requests']==100
    assert not (await repo.ban_user(123456,'QA'))[0]
    assert not (await repo.unban_user(123456))[0]
