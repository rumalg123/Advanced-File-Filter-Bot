"""Real-Mongo advanced-filter matrix across indexed and legacy candidates."""
import pytest

from favorites_recent_support import storage
from core.utils.feature_search import parse_advanced_search_query
from core.utils.search_matcher import build_media_search_filter
from core.utils.search_tokens import media_search_tokens, SEARCH_TOKEN_FIELD, SEARCH_TOKEN_VERSION_FIELD
from core.utils.validators import normalize_query

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.parametrize('indexed', [True, False])
@pytest.mark.parametrize('query,caption,expected', [
    ('qa show', True, 'abcdef'),
    ('qa show type:video', True, 'abcef'),
    ('qa show year:2026', True, 'abdef'),
    ('qa show lang:English type:document', True, 'd'),
    ('qa show quality:720p type:video season:1 episode:1', True, 'ae'),
    ('qa show quality:720p type:video season:1 episode:1', False, 'a'),
    ('qa show quality:1080p season:1 episode:1 minsize:2KB maxsize:2KB', True, 'f'),
    ('qa show quality:1920x1080', True, 'f'),
    ('qa show minsize:2KB maxsize:3KB', True, 'bcf'),
    ('season:1 episode:1 quality:720p', True, 'ade'),
    ('qa show maxsize:0B', True, ''),
])
async def test_advanced_filter_matrix_in_real_mongo(storage, indexed, query, caption, expected):
    _, _, db = storage
    documents = [
        {'_id':'a','file_name':'QA Show S01E01 2026 English 720p','file_type':'video','file_size':1024},
        {'_id':'b','file_name':'QA Show S01E02 2026 English 1080p','file_type':'video','file_size':2048},
        {'_id':'c','file_name':'QA Show S02E01 2025 Tamil 720p','file_type':'video','file_size':3072},
        {'_id':'d','file_name':'QA Show S01E01 2026 English 720p','file_type':'document','file_size':4096},
        {'_id':'e','file_name':'Unrelated archive','caption':'QA Show S01E01 2026 English 720p','file_type':'video','file_size':1024},
        {'_id':'f','file_name':'QA Show 2026 English','file_type':'video','file_size':2048,
         'season':1,'episode':'01','resolution':'1920x1080','quality':'1080p'},
    ]
    # Mixed new token-bearing and untouched legacy documents use the same matcher.
    for doc in documents[::2]:
        doc[SEARCH_TOKEN_FIELD] = media_search_tokens(doc['file_name'], doc.get('caption'))
        doc[SEARCH_TOKEN_VERSION_FIELD] = 1
    await db.media_files.insert_many(documents)
    title, filters = parse_advanced_search_query(query)
    predicate = build_media_search_filter(normalize_query(title), use_caption=caption,
                                         advanced_filters=filters, indexed_tokens=indexed)
    rows = await db.media_files.find(predicate, {'_id':1}).to_list(None)
    assert {row['_id'] for row in rows} == set(expected)
    assert await db.media_files.count_documents({}) == 6
    assert sorted(await db.media_files.index_information()) == ['_id_']


@pytest.mark.asyncio
async def test_large_precise_byte_bounds_match_only_exact_real_mongo_value(storage):
    _, _, db = storage
    await db.media_files.insert_many([
        {'_id':'below','file_name':'Large fixture','file_size':9007199254740992},
        {'_id':'exact','file_name':'Large fixture','file_size':9007199254740993},
    ])
    title, filters = parse_advanced_search_query('large minsize:9007199254740993B maxsize:9007199254740993B')
    predicate = build_media_search_filter(title, advanced_filters=filters)
    assert [r['_id'] for r in await db.media_files.find(predicate).to_list(None)] == ['exact']
