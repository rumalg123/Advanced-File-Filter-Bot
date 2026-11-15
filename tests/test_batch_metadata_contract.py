"""Legacy metadata downloads validate their shape, expire caches, and clean files."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from core.services.filestore import FileStoreService


def fixture(tmp_path, monkeypatch, payload):
    path=tmp_path/'batch.json';downloads=[]
    async def download(file_id, file_name=None):
        target=Path(file_name) if file_name else path
        downloads.append(target);target.write_text(json.dumps(payload))
        return str(target)
    client=NS(download_media=AsyncMock(side_effect=download))
    repo=NS(find_file=AsyncMock(return_value=NS(file_id='qa-json',file_name='batch.json',mime_type='application/json')))
    service=FileStoreService(repo,None,NS())
    async def api(fn,*args,chat_id=None,**kwargs):return await fn(*args,**kwargs)
    monkeypatch.setattr('core.services.filestore.telegram_api.call_api',api)
    return service,client,downloads


@pytest.mark.asyncio
@pytest.mark.parametrize('payload',[{'file_id':'bad'},['bad'],[{}],[{'file_id':3}],
    [{'file_id':'one','protect':'false'}],[{'file_id':'one','size':-1}]])
async def test_invalid_metadata_is_rejected_and_removed(tmp_path,monkeypatch,payload):
    service,client,downloads=fixture(tmp_path,monkeypatch,payload)
    assert await service.get_batch_data(client,'qa') is None
    assert all(not path.exists() for path in downloads)
    assert not service.batch_cache


@pytest.mark.asyncio
async def test_expired_metadata_cache_reloads_and_returns_independent_rows(tmp_path,monkeypatch):
    payload=[{'file_id':'one'}]
    service,client,downloads=fixture(tmp_path,monkeypatch,payload)
    now=[1000.0]
    monkeypatch.setattr('core.services.filestore.time.time',lambda:now[0])
    monkeypatch.setattr('core.services.filestore.time.monotonic',lambda:now[0])
    first=await service.get_batch_data(client,'qa');first[0]['file_id']='caller mutation'
    assert (await service.get_batch_data(client,'qa'))[0]['file_id']=='one'
    payload[0]['file_id']='two';now[0]+=service.batch_cache_ttl+1
    assert (await service.get_batch_data(client,'qa'))[0]['file_id']=='two'
    assert client.download_media.await_count==2
    assert all(not p.exists() for p in downloads)


@pytest.mark.asyncio
async def test_malformed_json_and_cancelled_download_leave_no_temp_file(tmp_path,monkeypatch):
    service,client,downloads=fixture(tmp_path,monkeypatch,[])
    async def malformed(file_id,file_name=None):
        target=Path(file_name) if file_name else tmp_path/'bad.json';downloads.append(target)
        target.write_text('not JSON');return str(target)
    client.download_media.side_effect=malformed
    assert await service.get_batch_data(client,'qa') is None
    assert all(not p.exists() for p in downloads)
    async def cancelled(file_id,file_name=None):
        target=Path(file_name) if file_name else tmp_path/'cancel.json';downloads.append(target)
        target.write_text('partial');raise asyncio.CancelledError()
    client.download_media.side_effect=cancelled
    with pytest.raises(asyncio.CancelledError):await service.get_batch_data(client,'qa')
    assert all(not p.exists() for p in downloads)


@pytest.mark.asyncio
async def test_non_json_media_is_not_downloaded_as_metadata(tmp_path,monkeypatch):
    service,client,_=fixture(tmp_path,monkeypatch,[])
    service.media_repo.find_file.return_value=NS(file_id='movie',file_name='movie.mkv',mime_type='video/x-matroska')
    assert await service.get_batch_data(client,'qa') is None
    client.download_media.assert_not_awaited()


@pytest.mark.asyncio
async def test_metadata_lru_eviction_clears_all_tracking_maps(tmp_path,monkeypatch):
    service,client,_=fixture(tmp_path,monkeypatch,[{'file_id':'one'}])
    service.max_batch_cache_size=1
    await service.get_batch_data(client,'first');await service.get_batch_data(client,'second')
    assert set(service.batch_cache)==set(service.batch_cache_access_time)==set(service.batch_cache_created_at)=={'second'}


@pytest.mark.asyncio
async def test_denied_retrieval_does_not_download_metadata():
    from test_deeplink_bulk_quota import fixture as deep_fixture
    handler,repo,_,message=deep_fixture()
    repo.can_retrieve_file.return_value=(False,'denied')
    await handler._send_batch(None,message,'qa')
    handler.bot.filestore_service.get_batch_data.assert_not_awaited()
    repo.reserve_quota_atomic.assert_not_awaited()
