"""BUG-118: request admission and notification claims remain idempotent."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import handlers.request as module
from favorites_recent_support import storage
from handlers.features import FeatureHandler
from handlers.request import RequestHandler
from repositories.features import FeatureRepository
from request_support import callback_fixture,request_fixture,direct_api


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize('target',['completed','rejected','available','unavailable'])
async def test_one_admin_claim_keeps_duplicate_protection_until_notification_finishes(storage,target):
    repo,pool,db=storage
    assert all((await repo.create_indexes()).values())
    first,created=await repo.create_content_request(7,10,'Movie Request')
    assert created
    claims=await asyncio.gather(*(repo.claim_content_request_transition(7,10,target,i+1) for i in range(8)))
    assert sum(claims)==1
    duplicate,created=await repo.create_content_request(7,11,'  movie   REQUEST ')
    assert not created and duplicate['_id']==first['_id']
    assert await db.content_requests.count_documents({})==1
    # A late failed-forward cleanup cannot overwrite a running admin action.
    assert not await repo.update_content_request(7,10,'forward_failed',0)
    restarted=FeatureRepository(pool)
    assert not await restarted.claim_content_request_transition(7,10,target,9)
    assert await restarted.finish_content_request_transition(7,10,target)
    assert not await restarted.finish_content_request_transition(7,10,target)
    assert not await restarted.claim_content_request_transition(7,10,target,9)
    doc=await restarted.get_content_request(7,10)
    assert doc['status']==target and doc['notification_sent_at'] and 'target_status' not in doc
    other,created=await restarted.create_content_request(8,11,'Movie Request')
    assert created and other['user_id']==8
    next_request,created=await restarted.create_content_request(7,12,'Movie Request')
    assert created and next_request['_id']!=first['_id']


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize('terminal',[True,False])
async def test_duplicate_source_message_returns_existing_record_even_if_query_changed(storage,terminal):
    repo,_,_=storage
    first,_=await repo.create_content_request(7,10,'Original query')
    if terminal:assert await repo.update_content_request(7,10,'completed',1)
    again,created=await repo.create_content_request(7,10,'Edited query')
    assert not created and again['_id']==first['_id'] and again['query']=='Original query'


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize('target',['completed','rejected','available','unavailable'])
async def test_legacy_processing_records_also_block_duplicate_admission(storage,target):
    repo,_,db=storage
    await db.content_requests.insert_one({'_id':'7:10','user_id':7,'message_id':10,
        'normalized_query':'movie','query':'Movie','status':'processing:'+target})
    existing,created=await repo.create_content_request(7,11,'MOVIE')
    assert not created and existing['_id']=='7:10'
    assert await db.content_requests.count_documents({})==1


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize('rollback',[True,False])
async def test_legacy_processing_records_can_still_be_finished_or_rolled_back(storage,rollback):
    repo,_,db=storage
    await db.content_requests.insert_one({'_id':'7:10','status':'processing:completed',
        'target_status':'completed','handled_by':1})
    method=repo.rollback_content_request_transition if rollback else repo.finish_content_request_transition
    assert await method(7,10,'completed')
    doc=await repo.get_content_request(7,10)
    assert doc['status']==('pending' if rollback else 'completed')
    assert 'target_status' not in doc


@pytest.mark.asyncio
@pytest.mark.parametrize('stage',['get_content_request','claim_content_request_transition'])
@pytest.mark.parametrize('tracking',[True,False])
async def test_tracking_read_or_claim_failure_cannot_fall_through_to_unclaimed_notification(monkeypatch,stage,tracking):
    monkeypatch.setattr(module.telegram_api,'call_api',direct_api)
    handler,query,client=callback_fixture(tracking=tracking)
    getattr(handler.bot.feature_repo,stage).side_effect=RuntimeError('private database details')
    await handler.handle_request_callback(client,query)
    client.send_message.assert_not_awaited()
    query.message.edit_text.assert_not_awaited()
    assert 'try again' in query.answer.await_args.args[0].lower()
    assert 'private database details' not in query.answer.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('raises',[True,False])
async def test_delivered_notification_with_failed_finalization_does_not_claim_a_finished_card(monkeypatch,raises):
    monkeypatch.setattr(module.telegram_api,'call_api',direct_api)
    handler,query,client=callback_fixture()
    method=handler.bot.feature_repo.finish_content_request_transition
    if raises:method.side_effect=RuntimeError('private database details')
    else:method.return_value=False
    await handler.handle_request_callback(client,query)
    client.send_message.assert_awaited_once()
    query.message.edit_text.assert_not_awaited()
    assert 'tracking' in query.answer.await_args.args[0].lower()
    handler.bot.feature_repo.rollback_content_request_transition.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_notifications_roll_back_then_retry_can_finish(monkeypatch):
    monkeypatch.setattr(module.telegram_api,'call_api',direct_api)
    handler,query,client=callback_fixture()
    client.send_message.side_effect=RuntimeError('delivery unavailable')
    await handler.handle_request_callback(client,query)
    handler.bot.feature_repo.rollback_content_request_transition.assert_awaited_once()
    handler.bot.feature_repo.finish_content_request_transition.assert_not_awaited()
    query.message.edit_text.assert_not_awaited()
    client.send_message.side_effect=None
    await handler.handle_request_callback(client,query)
    handler.bot.feature_repo.finish_content_request_transition.assert_awaited_once()


@pytest.mark.asyncio
async def test_blocked_private_delivery_can_notify_in_support_group(monkeypatch):
    monkeypatch.setattr(module.telegram_api,'call_api',direct_api)
    handler,query,client=callback_fixture()
    client.send_message.side_effect=[RuntimeError('PM unavailable'),None]
    await handler.handle_request_callback(client,query)
    assert client.send_message.await_args_list[1].args[0]==handler.bot.config.SUPPORT_GROUP_ID
    assert client.send_message.await_args_list[1].kwargs['reply_to_message_id']==10
    handler.bot.feature_repo.finish_content_request_transition.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('tracking',[True,False])
async def test_claim_loser_never_notifies_or_rewrites_card(monkeypatch,tracking):
    monkeypatch.setattr(module.telegram_api,'call_api',direct_api)
    handler,query,client=callback_fixture(tracking=tracking)
    handler.bot.feature_repo.claim_content_request_transition.return_value=False
    await handler.handle_request_callback(client,query)
    client.send_message.assert_not_awaited()
    query.message.edit_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_untracked_legacy_card_keeps_established_action_when_tracking_is_off(monkeypatch):
    monkeypatch.setattr(module.telegram_api,'call_api',direct_api)
    handler,query,client=callback_fixture(tracking=False)
    handler.bot.feature_repo.get_content_request.return_value=None
    await handler.handle_request_callback(client,query)
    client.send_message.assert_awaited_once()
    handler.bot.feature_repo.get_content_request.assert_awaited_once()
    handler.bot.feature_repo.claim_content_request_transition.assert_not_awaited()
    query.message.edit_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_replayed_tracked_source_message_never_consumes_another_request_slot():
    handler,message,client=request_fixture()
    handler.bot.feature_repo.get_content_request.return_value={'query':'Missing title','status':'completed'}
    handler._forward_request_to_admins=AsyncMock()
    await RequestHandler.handle_request_message.__wrapped__(handler,client,message)
    handler.bot.user_repo.track_request.assert_not_awaited()
    handler._forward_request_to_admins.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('record',[{'status':'pending','target_status':'completed'}, {'status':'processing:completed'}])
async def test_user_list_reports_inflight_transitions_without_claiming_completion(record):
    handler=object.__new__(FeatureHandler)
    handler.repository=SimpleNamespace(list_content_requests=AsyncMock(return_value=[{**record,'query':'<Movie>'}]))
    handler._reply_with_cleanup=AsyncMock()
    message=SimpleNamespace(from_user=SimpleNamespace(id=7))
    await FeatureHandler.my_requests_command.__wrapped__.__wrapped__(handler,None,message)
    text=handler._reply_with_cleanup.await_args.args[1]
    assert 'Update In Progress' in text and 'Completed' not in text and '&lt;Movie&gt;' in text
