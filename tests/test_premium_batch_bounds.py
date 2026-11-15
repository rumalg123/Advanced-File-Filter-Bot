"""Premium batches use the configured inclusive range and resolve source identity."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from config.settings import settings
from core.services.filestore import FileStoreService
from core.utils.link_parser import TelegramLinkParser


@pytest.mark.parametrize('first,last,limit,valid', [(1,1,1,True),(1,10001,500000,True),
    (1,500000,500000,True),(1,500001,500000,False),(2,1,500000,False)])
def test_premium_parser_honors_configured_inclusive_bounds(first,last,limit,valid):
    value=TelegramLinkParser.parse_link_pair(f'https://t.me/c/1234567890/{first}',
        f'https://t.me/c/1234567890/{last}',max_messages=limit)
    assert bool(value) is valid


@pytest.mark.asyncio
@pytest.mark.parametrize('last,expected',[(1,True),(10001,True),(500001,False)])
async def test_premium_service_uses_configured_limit(monkeypatch,last,expected):
    monkeypatch.setattr(settings.processing,'max_batch_messages',500000)
    client=NS(get_messages=AsyncMock(return_value=NS(empty=False)),get_me=AsyncMock(return_value=NS(username='qa_bot')))
    async def api(fn,*args,chat_id=None,**kwargs):return await fn(*args,**kwargs)
    monkeypatch.setattr('core.services.filestore.telegram_api.call_api',api)
    repo=NS(get_user_batch_links=AsyncMock(return_value=[]),create_batch_link=AsyncMock(return_value=True))
    service=FileStoreService(None,None,NS(ADMINS=[1]),repo)
    result=await service.create_premium_batch_link(client,'https://t.me/c/1234567890/1',f'https://t.me/c/1234567890/{last}',created_by=1)
    assert bool(result) is expected
    assert repo.create_batch_link.await_count==int(expected)


@pytest.mark.asyncio
async def test_premium_mixed_source_notation_resolves_the_same_channel(monkeypatch):
    client=NS(get_chat=AsyncMock(return_value=NS(id=-1001234567890)),
              get_messages=AsyncMock(return_value=NS(empty=False)),get_me=AsyncMock(return_value=NS(username='qa_bot')))
    async def api(fn,*args,chat_id=None,**kwargs):return await fn(*args,**kwargs)
    monkeypatch.setattr('core.services.filestore.telegram_api.call_api',api)
    repo=NS(get_user_batch_links=AsyncMock(return_value=[]),create_batch_link=AsyncMock(return_value=True))
    service=FileStoreService(None,None,NS(ADMINS=[1]),repo)
    assert await service.create_premium_batch_link(client,'https://t.me/qa_channel/1','https://t.me/c/1234567890/2',created_by=1)
