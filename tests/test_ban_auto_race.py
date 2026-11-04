import pytest
from favorites_recent_support import storage
from ban_support import user_repository,UserStatus

pytestmark=pytest.mark.integration


@pytest.mark.asyncio
async def test_delayed_abuse_ban_cannot_undo_an_admin_unban(storage,monkeypatch):
    repo,_,db=await user_repository(storage,monkeypatch,status=UserStatus.BANNED)
    await db.users.update_one({'_id':42},{'$set':{'warning_count':3}})
    assert (await repo.unban_user(42))[0]
    success,_=await repo.auto_ban_for_request_abuse(42)
    assert not success
    assert (await db.users.find_one({'_id':42}))['status']=='active'


@pytest.mark.asyncio
async def test_abuse_ban_requires_current_warning_threshold_and_preserves_manual_ban(storage,monkeypatch):
    repo,_,db=await user_repository(storage,monkeypatch)
    await db.users.update_one({'_id':42},{'$set':{'warning_count':3}})
    assert (await repo.auto_ban_for_request_abuse(42))[0]
    await db.users.update_one({'_id':42},{'$set':{'ban_reason':'Manual moderation'}})
    assert not (await repo.auto_ban_for_request_abuse(42))[0]
    assert (await db.users.find_one({'_id':42}))['ban_reason']=='Manual moderation'
