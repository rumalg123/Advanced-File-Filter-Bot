"""BUG-122 and dashboard acceptance: count semantics, access and bounded reads."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock

import pytest

from dashboard_support import dashboard_fixture
from favorites_recent_support import storage
from handlers.features import FeatureHandler


@pytest.mark.asyncio
@pytest.mark.integration
async def test_dashboard_counts_current_and_legacy_inflight_requests_with_global_feature_totals(storage):
    repository,_,db=storage
    statuses=['pending','pending','processing:completed','processing:available',
              'processing:unavailable','processing:rejected','completed','available',
              'unavailable','rejected','forward_failed']
    await db.content_requests.insert_many([{'_id':str(i),'status':s} for i,s in enumerate(statuses)])
    await db.content_requests.update_one({'_id':'1'},{'$set':{'target_status':'completed'}})
    await db.file_reports.insert_many([{'status':s} for s in ['open','open','resolved']])
    await db.saved_searches.insert_many([{'active':True},{'active':False}])
    await db.user_collections.insert_many([{'file_ids':[]},{'file_ids':['one']}])
    service,_,_,_=dashboard_fixture()
    service.repository=repository
    result=await service.dashboard()
    assert result['pending_requests']==6
    assert result['open_reports']==2 and result['saved_searches']==2 and result['collections']==2


@pytest.mark.asyncio
async def test_size_label_identifies_referenced_file_bytes_instead_of_database_storage():
    handler=object.__new__(FeatureHandler)
    handler.service=SimpleNamespace(dashboard=AsyncMock(return_value={'media':{'total_files':1,'total_size':1024}}))
    message=SimpleNamespace(reply_text=AsyncMock())
    await handler.content_dashboard_command(None,message)
    text=message.reply_text.await_args.args[0]
    assert 'Total file size:' in text and 'Storage:' not in text


@pytest.mark.asyncio
@pytest.mark.parametrize('actor',[1,7,8,None])
async def test_registered_dashboard_filter_accepts_only_configured_admins(actor):
    handler=object.__new__(FeatureHandler)
    handler.bot=SimpleNamespace(config=SimpleNamespace(ADMINS=[1]))
    handler.service=SimpleNamespace(enabled=lambda name:name=='FEATURE_CONTENT_DASHBOARD')
    captured=[]
    handler._register_message_handlers=captured.extend
    handler._register_callback_handlers=Mock()
    handler._handlers=[]
    handler.register_handlers()
    _,rule=next((callback,rule) for callback,rule in captured if callback.__name__=='content_dashboard_command')
    message=SimpleNamespace(text='/content_dashboard',caption=None,sender_chat=None,
                            from_user=SimpleNamespace(id=actor,username=None) if actor else None)
    allowed=bool(await rule(SimpleNamespace(me=SimpleNamespace(username='qa_bot')),message))
    assert allowed==(actor==1)


@pytest.mark.asyncio
async def test_disabled_dashboard_performs_no_repository_or_history_reads():
    service,repository,media,history=dashboard_fixture()
    service.config.FEATURE_CONTENT_DASHBOARD=False
    assert await service.dashboard()=={}
    repository.top_zero_results.assert_not_awaited()
    repository.count_documents.assert_not_awaited()
    media.get_file_stats.assert_not_awaited()
    history.get_global_top_searches.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('caption',[True,False])
async def test_reconciliation_uses_effective_caption_and_advanced_filters(caption):
    row={'_id':'title year:2025','query':'title','count':2}
    service,_,media,_=dashboard_fixture([row],caption=caption)
    assert (await service.dashboard())['zero_results']==[row]
    call=media.has_matching_file.await_args
    assert call.args[0]=='title' and call.kwargs['use_caption']==caption
    assert call.kwargs['advanced_filters']=={'year':2025}


@pytest.mark.asyncio
async def test_dashboard_validates_only_bounded_candidates_with_five_concurrent_checks():
    rows=[{'_id':'missing '+str(i),'query':'Missing '+str(i),'count':30-i} for i in range(30)]
    service,repository,media,_=dashboard_fixture(rows)
    active=peak=0
    async def checker(*args,**kwargs):
        nonlocal active,peak
        active+=1;peak=max(active,peak)
        await asyncio.sleep(.005)
        active-=1
        return False
    media.has_matching_file.side_effect=checker
    result=await service.dashboard()
    assert result['zero_results']==rows[:10]
    assert media.has_matching_file.await_count==30 and peak==5
    assert repository.top_zero_results.await_args.kwargs['limit']==30
