"""Recommendation menus preserve rank and render user-controlled values safely."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from handlers.commands_handlers.user import UserCommandHandler
from test_recommendations_and_similarity import SortedMemoryCache, make_file


async def render(recommendations, files):
    handler = object.__new__(UserCommandHandler)
    handler.bot = SimpleNamespace(
        recommendation_service=SimpleNamespace(get_recommendations_for_user=AsyncMock(return_value=recommendations)),
        media_repo=SimpleNamespace(find_files_batch=AsyncMock(return_value=files)),
        cache=SortedMemoryCache(),
    )
    handler._reply_text_with_auto_delete = AsyncMock()
    await UserCommandHandler.recommendations_command.__wrapped__.__wrapped__(
        handler, None, SimpleNamespace(from_user=SimpleNamespace(id=42)))
    call = handler._reply_text_with_auto_delete.await_args
    return call.args[1], call.kwargs['reply_markup']


@pytest.mark.asyncio
async def test_similar_query_text_is_html_escaped_and_search_reference_kept():
    text, markup = await render({'similar_queries': ['<b>&', '<unknown>really long query name &'],
                                  'based_on_history': [], 'trending_files': []}, {})
    assert '<code>&lt;b&gt;&amp;</code>' in text
    assert '<unknown>' not in text
    assert any(b.callback_data.startswith('search#page#@') for row in markup.inline_keyboard for b in row)


@pytest.mark.asyncio
@pytest.mark.parametrize('section', ['based_on_history', 'trending_files'])
async def test_file_buttons_follow_rank_instead_of_batch_lookup_order(section):
    first, second = make_file('first'), make_file('second')
    recommendations = {'similar_queries': [], 'based_on_history': [], 'trending_files': []}
    recommendations[section] = ['second', 'first']
    _, markup = await render(recommendations, {'first': first, 'second': second})
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data.startswith('file#')]
    assert callbacks == ['file#second', 'file#first']


@pytest.mark.asyncio
async def test_all_deleted_recommendations_show_empty_state():
    text, _ = await render({'similar_queries': [], 'based_on_history': ['deleted'], 'trending_files': ['gone']},
                           {'deleted': None, 'gone': None})
    assert 'No Recommendations Yet' in text


@pytest.mark.asyncio
async def test_same_file_is_not_rendered_twice_across_sections():
    file = make_file('first')
    text, markup = await render({'similar_queries': [], 'based_on_history': ['first'], 'trending_files': ['first']},
                               {'first': file})
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data.startswith('file#')]
    assert callbacks == ['file#first']
    assert 'Trending:' not in text


@pytest.mark.asyncio
async def test_file_names_and_explanations_are_html_escaped():
    file = make_file('first', '<b>dangerous&.mkv')
    text, _ = await render({'similar_queries': [], 'based_on_history': ['first'], 'trending_files': [],
                            'reasons': {'first': 'Because <unknown> &'}}, {'first': file})
    assert '&lt;b&gt;dangerous&amp;.mkv' in text
    assert 'Because &lt;unknown&gt; &amp;' in text
