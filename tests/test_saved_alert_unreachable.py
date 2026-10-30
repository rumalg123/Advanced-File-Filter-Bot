import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyrogram.errors import UserIsBlocked, InputUserDeactivated, PeerIdInvalid

from core.services.features import FeatureService
from repositories.saved_search_alert_jobs import SavedSearchAlertJobRepository
from test_durable_saved_search_alerts import make_media
from favorites_recent_support import storage


def fixture():
    entries=[{'_id':'a','user_id':1,'query':'Matrix','normalized_query':'matrix'},
             {'_id':'b','user_id':2,'query':'Matrix','normalized_query':'matrix'}]
    repo=SimpleNamespace(get_active_saved_search_page=AsyncMock(return_value=entries))
    service=FeatureService(repo,None,None,SimpleNamespace(FEATURE_SAVED_SEARCH_ALERTS=True),
                           bot=SimpleNamespace(send_message=AsyncMock()))
    jobs=SimpleNamespace(begin_delivery=AsyncMock(return_value=('claimed','lease')),
        finish_delivery=AsyncMock(return_value=True),release_delivery=AsyncMock(return_value=True),
        checkpoint=AsyncMock(return_value=True))
    service._alert_jobs=jobs
    media=make_media()
    job={'media':{'file_unique_id':media.file_unique_id,'file_id':media.file_id,
        'file_ref':media.file_ref,'file_name':media.file_name,'file_size':media.file_size,
        'file_type':media.file_type.value,'mime_type':media.mime_type,'caption':None}}
    return service,jobs,job


@pytest.mark.asyncio
@pytest.mark.parametrize('error',[UserIsBlocked,InputUserDeactivated,PeerIdInvalid])
async def test_unreachable_subscriber_does_not_hold_up_other_saved_search_alerts(monkeypatch,error):
    service,jobs,job=fixture()
    api=AsyncMock(side_effect=[error(),SimpleNamespace()])
    monkeypatch.setattr('core.services.features.telegram_api.call_api',api)
    assert await service._notify_durable_job(job,asyncio.Event())==1
    assert api.await_count==2
    jobs.release_delivery.assert_awaited_once_with('a','unique-test-media','lease')
    jobs.finish_delivery.assert_awaited_once_with('b','unique-test-media','lease')
    jobs.checkpoint.assert_awaited_once_with(job,'b')


@pytest.mark.asyncio
async def test_unreachable_recipient_lease_loss_stops_checkpointing(monkeypatch):
    service,jobs,job=fixture();jobs.release_delivery.return_value=False
    monkeypatch.setattr('core.services.features.telegram_api.call_api',AsyncMock(side_effect=UserIsBlocked()))
    with pytest.raises(RuntimeError,match='lease'):
        await service._notify_durable_job(job,asyncio.Event())
    jobs.checkpoint.assert_not_awaited()


@pytest.mark.asyncio
async def test_transient_send_failure_remains_retryable_without_checkpoint(monkeypatch):
    service,jobs,job=fixture()
    monkeypatch.setattr('core.services.features.telegram_api.call_api',AsyncMock(side_effect=TimeoutError('fixture timeout')))
    with pytest.raises(TimeoutError):await service._notify_durable_job(job,asyncio.Event())
    jobs.release_delivery.assert_awaited_once()
    jobs.checkpoint.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_real_queue_completes_with_blocked_and_reachable_subscribers(monkeypatch,storage):
    repository,_,db=storage
    jobs=SavedSearchAlertJobRepository(repository.db_pool)
    await jobs.ensure_indexes()
    await db.saved_searches.insert_many([{'_id':'a','user_id':1,'active':True,'query':'Matrix','normalized_query':'matrix'},
        {'_id':'b','user_id':2,'active':True,'query':'Matrix','normalized_query':'matrix'}])
    await jobs.enqueue(make_media());job=await jobs.claim()
    service=FeatureService(repository,None,None,SimpleNamespace(FEATURE_SAVED_SEARCH_ALERTS=True),
                           bot=SimpleNamespace(send_message=AsyncMock()))
    service._alert_jobs=jobs
    async def send(operation,user_id,*args,**kwargs):
        if user_id==1:raise UserIsBlocked()
        return SimpleNamespace()
    monkeypatch.setattr('core.services.features.telegram_api.call_api',send)
    assert await service._notify_durable_job(job,asyncio.Event())==1
    assert await jobs.acknowledge(job)
    assert await db.saved_search_alert_jobs.count_documents({'status':'done'})==1
    blocked=await db.saved_search_notifications.find_one({'search_id':'a'})
    reached=await db.saved_search_notifications.find_one({'search_id':'b'})
    assert blocked is None and reached['status']=='sent'
    assert (await jobs.begin_delivery('b','unique-test-media'))[0]=='delivered'
