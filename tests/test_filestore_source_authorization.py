"""Unsigned source ranges must not grant access to unrelated bot-readable chats."""
import base64
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from handlers.deeplink import DeepLinkHandler
from core.services.filestore import FileStoreService
from repositories.user import User
from test_repository_crud_contracts import mongo_pool  # noqa: F401


@pytest.mark.asyncio
async def test_forged_legacy_batch_cannot_copy_private_log_channel():
    channel = -1009999999999
    service = NS(count_channel_media_items=AsyncMock(return_value=0),
                 send_channel_files=AsyncMock(return_value=(1, 1, 0)))
    bot = NS(config=NS(ADMINS=[1], CHANNELS=[-1001234567890], LOG_CHANNEL=channel,
                       FILE_STORE_CHANNEL='', DISABLE_PREMIUM=True, MESSAGE_DELETE_SECONDS=0),
             filestore_service=service, user_repo=NS(can_retrieve_file=AsyncMock(return_value=(True, 'free access')),
               get_user=AsyncMock(return_value=User(id=42, name='QA')), can_receive_content=AsyncMock(return_value=True)))
    service.can_read_legacy_batch = FileStoreService(None, None, bot.config).can_read_legacy_batch
    message = NS(from_user=NS(id=42), reply=AsyncMock(return_value=NS(delete=AsyncMock())),reply_text=AsyncMock())
    encoded=base64.urlsafe_b64encode(f'1_2_{channel}_batch'.encode()).decode().rstrip('=')
    await DeepLinkHandler(bot)._send_dstore_files(NS(),message,encoded)
    service.send_channel_files.assert_not_awaited()


@pytest.mark.parametrize('user,channels,store,source,allowed', [
    (42, [-1001], '', -1001, True), (42, '-1001, -1002', '', -1002, True),
    (42, [0], '-1003', -1003, True), (42, [-1001], '', -1009, False),
    (1, [], '', -1009, True), (42, [], '', -1009, False),
])
@pytest.mark.asyncio
async def test_legacy_sources_are_explicitly_allowlisted(user, channels, store, source, allowed):
    service=FileStoreService(None,None,NS(ADMINS=[1],CHANNELS=channels,FILE_STORE_CHANNEL=store))
    assert await service.can_read_legacy_batch(None,user,source) is allowed


@pytest.mark.parametrize('user,public,member,allowed', [
    (1, False, 'left', True), (42, False, 'member', False),
    (42, True, 'member', True), (42, True, 'left', False),
    (42, True, 'unknown', False),
])
@pytest.mark.asyncio
async def test_batch_creation_persists_only_authorized_source_grants(monkeypatch,user,public,member,allowed):
    from pyrogram import enums
    statuses={'member':enums.ChatMemberStatus.MEMBER,'left':enums.ChatMemberStatus.LEFT,'unknown':'unknown'}
    client=NS(get_me=AsyncMock(return_value=NS(username='qa_bot')),
              get_chat_member=AsyncMock(return_value=NS(status=statuses[member])),
              get_messages=AsyncMock(return_value=NS(empty=False)))
    async def api(fn,*args,chat_id=None,**kwargs):return await fn(*args,**kwargs)
    monkeypatch.setattr('core.services.filestore.telegram_api.call_api',api)
    repo=NS(create_batch_link=AsyncMock(return_value=True))
    service=FileStoreService(None,None,NS(ADMINS=[1],PUBLIC_FILE_STORE=public),repo)
    link=await service.create_batch_link(client,'https://t.me/c/1234567890/1','https://t.me/c/1234567890/2',protect=True,created_by=user)
    assert bool(link) is allowed
    assert repo.create_batch_link.await_count==int(allowed)
    if allowed:
        batch=repo.create_batch_link.await_args.args[0]
        assert batch.protected and not batch.premium_only and batch.created_by==user
        assert link.endswith('DSTORE-'+batch.id) and len(link.split('start=')[1])<=64
        assert len(batch.id)==35


@pytest.mark.asyncio
async def test_premium_repository_failure_cannot_downgrade_to_ordinary_link():
    service=FileStoreService(None,None,NS())
    service.create_batch_link=AsyncMock(return_value='unsafe downgrade')
    assert await service.create_premium_batch_link(None,'first','last') is None
    service.create_batch_link.assert_not_awaited()


@pytest.mark.asyncio
async def test_ordinary_route_cannot_open_a_premium_grant():
    service=NS(get_premium_batch_link=AsyncMock(return_value=NS(premium_only=True)),send_channel_files=AsyncMock())
    handler=DeepLinkHandler(NS(filestore_service=service))
    message=NS(from_user=NS(id=42),reply_text=AsyncMock())
    await handler._send_dstore_files(None,message,'BL-'+'a'*32)
    service.send_channel_files.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_item_grant_survives_cache_loss_in_real_mongo(mongo_pool, monkeypatch):
    from repositories.batch_link import BatchLinkRepository
    from test_repository_crud_contracts import Cache
    repo=BatchLinkRepository(mongo_pool,Cache())
    client=NS(get_me=AsyncMock(return_value=NS(username='qa_bot')),get_messages=AsyncMock(return_value=NS(empty=False)))
    async def api(fn,*args,chat_id=None,**kwargs):return await fn(*args,**kwargs)
    monkeypatch.setattr('core.services.filestore.telegram_api.call_api',api)
    service=FileStoreService(None,None,NS(ADMINS=[1]),repo)
    link=await service.create_batch_link(client,'https://t.me/c/1234567890/4','https://t.me/c/1234567890/4',True,created_by=1)
    batch_id=link.split('DSTORE-')[1];repo.cache.data.clear()
    stored=await repo.get_batch_link(batch_id)
    assert stored.protected and stored.from_msg_id==stored.to_msg_id==4
    assert not stored.premium_only and stored.created_by==1

