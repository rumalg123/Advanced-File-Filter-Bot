"""Autocomplete validates normalized history against current indexed media."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.database.errors import SearchBackendUnavailableError, SEARCH_RETRY_MESSAGE
from core.services.features import FeatureService
from handlers.features import FeatureHandler
from repositories.media import FileType


def service_for(candidates, checker=None, *, advanced=False):
    history = SimpleNamespace(get_most_searched_keywords=AsyncMock(return_value=candidates),
                              get_global_top_searches=AsyncMock(return_value=[]))
    media = SimpleNamespace(has_matching_file=checker or AsyncMock(return_value=True))
    config = SimpleNamespace(FEATURE_SEARCH_AUTOCOMPLETE=True,
                             FEATURE_ADVANCED_SEARCH=advanced, USE_CAPTION_FILTER=False)
    return FeatureService(SimpleNamespace(), media, history, config), media, history


@pytest.mark.asyncio
async def test_empty_history_needs_no_media_lookup():
    service, media, _ = service_for([])
    assert await service.autocomplete(42, 'matrix') == []
    media.has_matching_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_autocomplete_skips_stale_candidates_and_backfills():
    values = ['matrix old1', 'matrix old2', 'matrix alive', 'matrix live2']
    service, _, _ = service_for(values, AsyncMock(side_effect=lambda q, **kw: 'old' not in q))
    assert await service.autocomplete(42, 'matrix', limit=2) == ['matrix alive', 'matrix live2']


@pytest.mark.asyncio
async def test_autocomplete_deduplicates_by_normalized_query():
    service, _, _ = service_for([' Matrix   Alive ', 'matrix alive', 'matrix next'])
    result = await service.autocomplete(42, 'matrix')
    assert len(result) == 2 and result[0].strip().lower().split() == ['matrix', 'alive']


@pytest.mark.asyncio
async def test_autocomplete_excludes_exact_query_even_with_different_spacing():
    service, _, _ = service_for([' Matrix   Alive ', 'matrix alive', 'matrix alive extended'])
    assert await service.autocomplete(42, 'matrix alive') == ['matrix alive extended']


@pytest.mark.asyncio
@pytest.mark.parametrize('limit', [0, -1, True, '3'])
async def test_invalid_autocomplete_limit_does_no_history_or_media_reads(limit):
    service, media, history = service_for(['matrix first', 'matrix second'])
    assert await service.autocomplete(42, 'matrix', limit=limit) == []
    history.get_most_searched_keywords.assert_not_awaited()
    media.has_matching_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_advanced_history_is_checked_with_effective_filters_and_bad_syntax_is_skipped():
    service, media, _ = service_for(['matrix type:document maxsize:1KB', 'matrix year:'], advanced=True)
    assert await service.autocomplete(42, 'matrix') == ['matrix type:document maxsize:1KB']
    media.has_matching_file.assert_awaited_once_with('matrix', file_type=FileType.DOCUMENT,
        use_caption=False, advanced_filters={'file_type': 'document', 'max_size': 1024})


@pytest.mark.asyncio
async def test_backend_failure_is_distinct_from_no_valid_suggestions():
    service, _, _ = service_for(['matrix alive'], AsyncMock(side_effect=ConnectionError('Injected QA read outage')))
    with pytest.raises(SearchBackendUnavailableError):
        await service.autocomplete(42, 'matrix')


@pytest.mark.asyncio
async def test_candidate_validation_is_bounded_and_uses_limited_concurrency():
    active = peak = 0
    async def checker(*args, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.001)
        active -= 1
        return True
    service, _, history = service_for([f'matrix {i}' for i in range(30)], AsyncMock(side_effect=checker))
    assert len(await service.autocomplete(42, 'matrix', limit=4)) == 4
    assert 1 <= peak <= 5 and active == 0
    assert service.media_repo.has_matching_file.await_count <= 12
    history.get_most_searched_keywords.assert_awaited_once_with(42, limit=50)


@pytest.mark.asyncio
@pytest.mark.parametrize('outage', ['media', 'callback-state'])
async def test_suggest_command_reports_retry_for_unavailable_backend_or_buttons(outage):
    handler = object.__new__(FeatureHandler)
    handler.service = SimpleNamespace(autocomplete=AsyncMock(return_value=['matrix alive']))
    if outage == 'media':
        handler.service.autocomplete.side_effect = SearchBackendUnavailableError('QA unavailable')
    handler.bot = SimpleNamespace(cache=SimpleNamespace(set=AsyncMock(return_value=False)))
    handler._reply_with_cleanup = AsyncMock()
    message = SimpleNamespace(text='/suggest matrix', from_user=SimpleNamespace(id=42))
    await FeatureHandler.suggest_command.__wrapped__.__wrapped__(handler, None, message)
    assert handler._reply_with_cleanup.await_args.args[1] == SEARCH_RETRY_MESSAGE
