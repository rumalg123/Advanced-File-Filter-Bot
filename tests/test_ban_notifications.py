import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.services.features import FeatureService
from core.services.broadcast import BroadcastService
from test_saved_alert_unreachable import fixture
from test_durable_saved_search_alerts import make_media
from test_production_authorization import make_repo
from repositories.user import User,UserStatus


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['durable','legacy'])
@pytest.mark.parametrize('unavailable',[False,True])
async def test_saved_alerts_recheck_bans_without_creating_delivery_claims(monkeypatch,mode,unavailable):
    service,jobs,job=fixture()
    service.bot.user_repo=SimpleNamespace(can_receive_content=AsyncMock(
        side_effect=ConnectionError('fixture authorization unavailable') if unavailable else None,
        return_value=False))
    service.repository.claim_saved_search_notification=AsyncMock(return_value=True)
    api=AsyncMock();monkeypatch.setattr('core.services.features.telegram_api.call_api',api)
    invoke=service._notify_durable_job(job,asyncio.Event()) if mode=='durable' else service.notify_saved_search_matches(make_media())
    if unavailable:
        with pytest.raises(ConnectionError):await invoke
    else:assert await invoke==0
    api.assert_not_awaited()
    jobs.begin_delivery.assert_not_awaited()
    service.repository.claim_saved_search_notification.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('unavailable',[False,True])
async def test_broadcast_rechecks_status_after_recipient_snapshot(monkeypatch,unavailable):
    repo=SimpleNamespace(can_receive_content=AsyncMock(
        side_effect=ConnectionError('fixture unavailable') if unavailable else None,return_value=False))
    service=BroadcastService(repo,None,None)
    api=AsyncMock();monkeypatch.setattr('core.services.broadcast.telegram_api.call_api',api)
    status,user_id=await service._send_to_user(SimpleNamespace(),SimpleNamespace(text='QA broadcast'),42)
    assert status==('failed' if unavailable else 'blocked') and user_id==42
    api.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('user_id,admins,owner',[(1,(1,),None),(42,(),42)])
async def test_content_status_gate_keeps_admin_and_owner_exemptions(monkeypatch,user_id,admins,owner):
    repo=make_repo(monkeypatch,User(id=user_id,name='Privileged',status=UserStatus.BANNED),admins=admins)
    assert await repo.can_receive_content(user_id,owner)
    repo.get_user.assert_not_awaited()
