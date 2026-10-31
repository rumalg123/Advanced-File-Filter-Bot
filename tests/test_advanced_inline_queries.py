"""Inline advanced searches keep full filters and distinguish input errors."""
import pytest

from test_inline_search import inline_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize('advanced', [True, False])
async def test_inline_query_retains_all_advanced_filters_with_legacy_cap_unchanged(advanced):
    handler, query = inline_fixture()
    handler.bot.config.FEATURE_ADVANCED_SEARCH = advanced
    query.query = 'winter '*16 + 'type:document minsize:1KB maxsize:2KB'
    await handler.handle_inline_query(None, query)
    passed = handler.bot.file_service.search_files_with_access_check.await_args.kwargs['query']
    assert passed == (query.query if advanced else query.query[:100])


@pytest.mark.asyncio
async def test_inline_invalid_filter_guides_to_search_help_instead_of_premium():
    handler, query = inline_fixture()
    handler.bot.config.FEATURE_ADVANCED_SEARCH = True
    query.query = 'movie year:'
    handler.bot.file_service.search_files_with_access_check.return_value = (
        [], 0, 0, False, "Invalid search filter: Filter 'year' requires a value.")
    await handler.handle_inline_query(None, query)
    answer = query.answer.await_args.kwargs
    assert answer['results'] == [] and answer['cache_time'] == 0
    assert answer['switch_pm_parameter'] == 'start'
    assert 'search filter' in answer['switch_pm_text'].lower()
    assert '/search_help' in answer['switch_pm_text']
