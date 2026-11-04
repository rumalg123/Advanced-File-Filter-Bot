"""The suggestion command preserves the same quoted syntax as text search."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from handlers.features import FeatureHandler


@pytest.mark.asyncio
@pytest.mark.parametrize('query', ['movie language:"Hong Kong"', "movie minsize:'1.5 KB'"])
async def test_suggest_preserves_quoted_filter_values(query):
    handler = object.__new__(FeatureHandler)
    handler.service = SimpleNamespace(autocomplete=AsyncMock(return_value=[]))
    handler._reply_with_cleanup = AsyncMock()
    message = SimpleNamespace(text='/suggest '+query, from_user=SimpleNamespace(id=42))
    await FeatureHandler.suggest_command.__wrapped__.__wrapped__(handler, None, message)
    handler.service.autocomplete.assert_awaited_once_with(42, query)
