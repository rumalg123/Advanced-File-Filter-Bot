from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from favorites_recent_support import storage
from handlers.features import FeatureHandler


@pytest.mark.asyncio
@pytest.mark.integration
async def test_saved_search_menu_exposes_all_twenty_five_owned_searches(storage):
    repository,_,db = storage
    now = datetime.now(UTC)
    await db.saved_searches.insert_many([{'_id':f'qa-{i:02d}','user_id':42,
        'query':f'QA saved {i}','normalized_query':f'qa saved {i}',
        'active':i%2==0,'updated_at':now+timedelta(seconds=i)} for i in range(25)]
        +[{'_id':'other','user_id':99,'query':'Other owner','updated_at':now}])
    assert len(await repository.list_saved_searches(42))==25
    assert len(await repository.list_saved_searches(42,limit=5))==5
    handler=object.__new__(FeatureHandler)
    handler.repository=repository
    handler.bot=SimpleNamespace(cache=SimpleNamespace(set=AsyncMock(return_value=True)))
    text,markup=await handler._saved_searches_view(42)
    assert len(markup.inline_keyboard)==25 and 'Other owner' not in text
    delete_callbacks=[b.callback_data for row in markup.inline_keyboard for b in row
                      if b.callback_data.startswith('feature#saved_delete#')]
    assert len(delete_callbacks)==25 and 'feature#saved_delete#qa-00' in delete_callbacks
    assert all(len(b.callback_data.encode())<=64 for row in markup.inline_keyboard for b in row)
