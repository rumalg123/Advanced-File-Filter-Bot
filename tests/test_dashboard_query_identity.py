"""BUG-119: display truncation must never change a historical search predicate."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from dashboard_support import dashboard_fixture
from handlers.features import FeatureHandler
from repositories.media import FileType


@pytest.mark.asyncio
@pytest.mark.parametrize('matches',[True,False])
@pytest.mark.parametrize('advanced',[True,False])
async def test_reconcile_uses_complete_identity_instead_of_short_display_query(matches,advanced):
    full=('Long title '*12).strip()+' type:document maxsize:1B'
    row={'_id':full.lower(),'query':full[:100],'count':3}
    service,repository,media,_=dashboard_fixture([row],advanced=advanced)
    media.has_matching_file.return_value=matches
    result=await service.dashboard()
    call=media.has_matching_file.await_args
    if advanced:
        assert call.kwargs['advanced_filters']['max_size']==1
        assert call.kwargs['file_type']==FileType.DOCUMENT
        assert call.args[0]==' '.join(('long title '*12).split())
    else:assert call.args[0]==full.lower()
    assert result['zero_results']==([] if matches else [row])
    if matches:assert repository.resolve_zero_result.await_args.args[0]==full.lower()
    else:repository.resolve_zero_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_row_without_string_identity_uses_available_query():
    row={'query':'Legacy title','count':1}
    service,_,media,_=dashboard_fixture([row])
    await service.dashboard()
    assert media.has_matching_file.await_args.args[0]=='Legacy title'


@pytest.mark.asyncio
@pytest.mark.parametrize('row',[
    {'query':'<Literal> & title','count':1},
    {'_id':'fallback <literal>','count':2},
    {'_id':'fallback title','query':None,'count':3},
])
async def test_renderer_accepts_legacy_display_shapes_and_escapes_text(row):
    handler=object.__new__(FeatureHandler)
    handler.service=SimpleNamespace(dashboard=AsyncMock(return_value={'zero_results':[row]}))
    message=SimpleNamespace(reply_text=AsyncMock())
    await handler.content_dashboard_command(None,message)
    rendered=message.reply_text.await_args.args[0]
    assert '&lt;' in rendered if '<' in (row.get('query') or row['_id']) else 'fallback title' in rendered
