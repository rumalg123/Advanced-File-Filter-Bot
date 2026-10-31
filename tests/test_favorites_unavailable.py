from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from handlers.features import FeatureHandler


@pytest.mark.asyncio
@pytest.mark.parametrize('replied', [False, True])
async def test_unfavorite_can_remove_membership_after_media_was_deleted(replied):
    handler = object.__new__(FeatureHandler)
    handler.bot = SimpleNamespace(media_repo=SimpleNamespace(find_file=AsyncMock(return_value=None)))
    handler.repository = SimpleNamespace(remove_from_collection=AsyncMock(return_value=True))
    handler._reply_with_cleanup = AsyncMock()
    message = SimpleNamespace(from_user=SimpleNamespace(id=42), text='/unfavorite removed-id Watchlist')
    if replied:
        message.text = '/unfavorite Watchlist'
        message.reply_to_message = SimpleNamespace(document=SimpleNamespace(file_unique_id='removed-id'))
    await handler._favorite_mutation(message, remove=True)
    handler.repository.remove_from_collection.assert_awaited_once_with(42, 'removed-id', 'Watchlist')
    assert 'removed from' in handler._reply_with_cleanup.await_args.args[1]


@pytest.mark.asyncio
async def test_favorite_cannot_add_deleted_media():
    handler = object.__new__(FeatureHandler)
    handler.bot = SimpleNamespace(media_repo=SimpleNamespace(find_file=AsyncMock(return_value=None)))
    handler.repository = SimpleNamespace(add_to_collection=AsyncMock())
    handler._reply_with_cleanup = AsyncMock()
    await handler._favorite_mutation(SimpleNamespace(from_user=SimpleNamespace(id=42),
        text='/favorite removed-id'), remove=False)
    handler.repository.add_to_collection.assert_not_awaited()
    assert 'no longer available' in handler._reply_with_cleanup.await_args.args[1]
