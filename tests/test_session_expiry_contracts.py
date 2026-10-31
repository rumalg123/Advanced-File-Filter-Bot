"""Session deadlines and Redis ownership agree with interactive edit prompts."""
import os
from datetime import datetime, timedelta, UTC
from uuid import uuid4

import pytest
from core.session.manager import UnifiedSessionManager, SessionData, SessionType, SessionStatus
from core.cache.redis_cache import CacheManager
from core.cache.config import CacheKeyGenerator
from test_settings_edit_lifecycle import fixture
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_edit_prompt_deadline_matches_stored_session_expiry(monkeypatch):
    from core.session.manager import UnifiedSessionManager
    from test_cache_audit import MemoryCache
    handler,message,client=fixture(monkeypatch)
    cache=MemoryCache();handler.session_manager=UnifiedSessionManager(cache)
    handler.settings_service.get_all_settings=AsyncMock(return_value={'CACHE_TIME':{'type':'int','value':600}})
    message.id=10;message.edit_text=AsyncMock()
    await handler.start_edit_session(message,'CACHE_TIME',1)
    session=await handler.session_manager.get_edit_session(1)
    assert '60 seconds' in message.edit_text.await_args.args[0]
    assert (session.expires_at-session.created_at).total_seconds()==60
    assert {call[2] for call in cache.set_calls}=={60}


@pytest.mark.parametrize('offset,expired',[(-1,True),(0,True),(1,False)])
def test_session_expiry_includes_the_exact_deadline(monkeypatch,offset,expired):
    instant=datetime(2026,10,29,10,tzinfo=UTC)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return instant
    monkeypatch.setattr('core.session.manager.datetime',Clock)
    session=SessionData(user_id=1,session_type=SessionType.EDIT,session_id='qa',
        status=SessionStatus.ACTIVE,created_at=instant-timedelta(seconds=60),
        expires_at=instant+timedelta(microseconds=offset),last_activity=instant,data={})
    assert session.is_expired() is expired
    assert session.is_active() is (not expired)


@pytest.mark.asyncio
async def test_real_redis_edit_ttl_and_stale_cancellation_pointer_ownership():
    uri=os.getenv('TEST_REDIS_CACHE_URI')
    if not uri:pytest.skip('Requires disposable local Redis')
    from urllib.parse import urlsplit
    assert urlsplit(uri).hostname in ('127.0.0.1','localhost','::1')
    user_id=int(uuid4().hex[:12],16)
    cache=CacheManager(uri);await cache.initialize();manager=UnifiedSessionManager(cache)
    old=new=None
    try:
        old=await manager.create_edit_session(user_id,{'key':'CACHE_TIME'})
        pointer=CacheKeyGenerator.session('edit',user_id)
        assert 0<await cache.redis.ttl(pointer)<=60
        new=await manager.create_edit_session(user_id,{'key':'MAX_BTN_SIZE'})
        assert await manager.cancel_edit_session(user_id,session_id=old)
        assert (await manager.get_edit_session(user_id)).session_id==new
        assert await manager.cancel_edit_session(user_id)
        assert await manager.get_edit_session(user_id) is None
    finally:
        for session_id in (old,new):
            if session_id:await manager.cancel_session(user_id,SessionType.EDIT,session_id)
        await cache.close()
