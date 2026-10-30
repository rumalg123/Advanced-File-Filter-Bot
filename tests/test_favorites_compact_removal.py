from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from handlers.features import FeatureHandler
from repositories.media import FileType, MediaFile


@pytest.mark.asyncio
@pytest.mark.parametrize('name', ['සිංහල '*6, 'A'*40])
async def test_favorites_menu_keeps_remove_controls_for_long_collection_names(name):
    handler = object.__new__(FeatureHandler)
    file = MediaFile(file_unique_id='qa-file-unique01',file_id='qa-file',file_ref=None,
        file_name='QA.txt',file_size=10,file_type=FileType.DOCUMENT,mime_type=None,caption=None)
    collection = {'name':name,'file_ids':[file.file_unique_id],'callback_token':'aabbccdd'}
    handler.repository = SimpleNamespace(get_collection=AsyncMock(return_value=collection))
    handler.bot = SimpleNamespace(media_repo=SimpleNamespace(find_files_batch=AsyncMock(return_value={file.file_unique_id:file})))
    handler._reply_with_cleanup = AsyncMock()
    message = SimpleNamespace(from_user=SimpleNamespace(id=42),text='/favorites '+name)
    await FeatureHandler.favorites_command.__wrapped__.__wrapped__(handler,None,message)
    markup = handler._reply_with_cleanup.await_args.kwargs['reply_markup']
    remove = [b for row in markup.inline_keyboard for b in row if b.text=='🗑 Remove']
    assert len(remove)==1
    assert name not in remove[0].callback_data and 'aabbccdd' in remove[0].callback_data
    assert len(remove[0].callback_data.encode())<=64


@pytest.mark.asyncio
async def test_old_favorite_menu_removes_by_stable_token_after_rename():
    handler = object.__new__(FeatureHandler)
    handler.service = SimpleNamespace(enabled=lambda flag:flag=='FEATURE_FAVORITES')
    handler.repository = SimpleNamespace(remove_from_collection_by_token=AsyncMock(
        return_value=({'name':'Renamed collection'},'removed')))
    message = SimpleNamespace(reply_markup=SimpleNamespace(inline_keyboard=[]))
    handler._remove_feature_menu_row = AsyncMock()
    query = SimpleNamespace(data='feature#unfavtoken#qa-file#aabbccdd',
        from_user=SimpleNamespace(id=42),message=message,answer=AsyncMock())
    await FeatureHandler.feature_callback.__wrapped__.__wrapped__(handler,None,query)
    handler.repository.remove_from_collection_by_token.assert_awaited_once_with(42,'aabbccdd','qa-file')
    handler._remove_feature_menu_row.assert_awaited_once_with(message,query.data)
    assert 'Renamed collection' in query.answer.await_args.args[0]
