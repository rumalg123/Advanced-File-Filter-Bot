"""Malformed filters fail before search; byte bounds stay exact and BSON-safe."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.services.file_access import FileAccessService
from core.utils.feature_search import parse_advanced_search_query


@pytest.mark.parametrize('key', ['type', 'year', 'lang', 'language', 'quality', 'season', 'episode', 'minsize', 'maxsize'])
def test_recognized_filter_requires_a_value(key):
    with pytest.raises(ValueError):
        parse_advanced_search_query(f'movie {key}:')


@pytest.mark.parametrize('value', ['lang:"English', "lang:'English", 'lang:"English"junk', 'year:"2026', 'lang:""'])
def test_filter_quotes_must_be_complete_and_delimited(value):
    with pytest.raises(ValueError):
        parse_advanced_search_query('movie '+value)


@pytest.mark.parametrize('value,expected', [
    ('9007199254740993B', 9007199254740993),
    ('9223372036854775807B', 9223372036854775807),
    ('1.5KB', 1536), ('0.25GB', 268435456), ('1234.567KB', 1264196),
])
def test_sizes_are_exact_through_signed_bson_integer_limit(value, expected):
    assert parse_advanced_search_query('movie maxsize:'+value)[1]['max_size'] == expected


@pytest.mark.parametrize('value', ['9223372036854775808B', '9'*350+'TB'])
def test_oversized_byte_filter_is_a_validation_error(value):
    with pytest.raises(ValueError):
        parse_advanced_search_query('movie minsize:'+value)


def test_quoted_language_and_size_preserve_literal_title_and_unknown_keys():
    title, filters = parse_advanced_search_query('Movie <b>& edition:extended language:"Hong Kong" minsize:"1.5 KB"')
    assert title == 'Movie <b>& edition:extended'
    assert filters == {'language': 'hong kong', 'min_size': 1536}


@pytest.mark.asyncio
@pytest.mark.parametrize('query', ['movie year:', 'movie minsize:9223372036854775808B', 'movie minsize:'+'9'*350+'TB'])
async def test_invalid_filter_does_not_reach_media_search(query):
    media = SimpleNamespace(search_files=AsyncMock())
    service = FileAccessService(SimpleNamespace(can_retrieve_file=AsyncMock(return_value=(True, 'ok'))),
        media, SimpleNamespace(), SimpleNamespace(check_rate_limit=AsyncMock(return_value=(True, 0))),
        SimpleNamespace(USE_CAPTION_FILTER=True, FEATURE_ADVANCED_SEARCH=True))
    files, offset, total, allowed, reason = await service.search_files_with_access_check(42, query, 42)
    assert not allowed and 'Invalid search filter:' in reason
    assert (files, offset, total) == ([], 0, 0)
    media.search_files.assert_not_awaited()
