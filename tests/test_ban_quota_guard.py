import pytest
from config.settings import settings
from favorites_recent_support import storage
from ban_support import user_repository,prime,User,UserStatus

pytestmark=pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.parametrize('ledger',[False,True])
async def test_ban_between_access_read_and_reservation_cannot_charge_or_grant_quota(storage,monkeypatch,ledger):
    repo,cache,db=await user_repository(storage,monkeypatch)
    monkeypatch.setattr(settings.features,'feature_quota_delivery_ledger',ledger)
    original=repo.db_pool.execute_with_retry
    raced=False
    async def execute(operation,*args,**kwargs):
        nonlocal raced
        if getattr(operation,'__name__','')=='find_one_and_update' and not raced:
            raced=True
            await db.users.update_one({'_id':42},{'$set':{'status':'banned','ban_reason':'QA concurrent ban'}})
        return await original(operation,*args,**kwargs)
    repo.db_pool.execute_with_retry=execute
    allowed,reserved,reason=await repo.reserve_quota_atomic(42,2,10)
    assert not allowed and reserved==0 and 'banned' in reason.lower()
    doc=await db.users.find_one({'_id':42})
    assert doc['daily_retrieval_count']==0 and not doc.get('quota_delivery_ledger')
