"""The indexed prefilter may remove work, never legacy matches."""
import os
from copy import deepcopy
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pymongo import MongoClient

from config.settings import FeatureConfig,settings
from core.utils.search_tokens import (media_search_tokens,title_candidate_terms,
    indexed_title_candidates,SEARCH_TOKEN_INDEX,SEARCH_TOKEN_FIELD,SEARCH_TOKEN_VERSION_FIELD)
from core.utils.search_matcher import build_media_search_filter
from core.utils.validators import normalize_query
from repositories.media import MediaRepository,MediaFile,FileType
from scripts.backfill_search_tokens import backfill
from scripts.profile_media_search import is_local


def fixture_file():
    return MediaFile('qa-unique','qa-file','qa-ref','Spring of Youth S01E01 1080p.mkv',10,
        FileType.VIDEO,'video/mkv','QA caption')


def test_indexed_search_defaults_off_and_preserves_legacy_document_shape(monkeypatch):
    assert FeatureConfig(_env_file=None).feature_indexed_media_search is False
    monkeypatch.setattr(settings.features,'feature_indexed_media_search',False)
    repo=MediaRepository(None,None)
    raw=repo._entity_to_dict(fixture_file())
    assert SEARCH_TOKEN_FIELD not in raw and SEARCH_TOKEN_VERSION_FIELD not in raw
    raw.update({SEARCH_TOKEN_FIELD:['spring'],SEARCH_TOKEN_VERSION_FIELD:1})
    restored=repo._dict_to_entity(raw)
    assert restored.file_unique_id=='qa-unique'


@pytest.mark.parametrize('text,expected',[
    ('spring',['spring','springg','sprin','sprng']),('this',['thas','this','thiz','thos','thus']),
    ('Doctor',['doctor']),('x jo',None),('한국어',None),('',None),
])
def test_candidate_terms_cover_typo_alternatives_or_fall_back(text,expected):
    assert title_candidate_terms(text)==(sorted(expected) if expected is not None else None)


def test_future_pattern_shapes_fall_back_instead_of_losing_candidates(monkeypatch):
    monkeypatch.setattr('core.utils.search_tokens.build_typo_tolerant_pattern',lambda text:r'future[syntax]')
    assert indexed_title_candidates('doctor') is None


def test_tokens_cover_scalar_array_ascii_and_unicode_boundary_equivalents():
    result=media_search_tokens(['SHOW','İnk','ıNK','KDrama','ſhow',None],'<b>maße</b>')
    assert {'show','ink','kdrama','ma','e','b'} <= set(result)
    assert result==sorted(set(result))


@pytest.fixture
def mongo_collection():
    uri=os.getenv('TEST_MONGO_URI')
    if not uri:pytest.skip('Requires disposable local MongoDB')
    assert is_local(uri)
    name='qa_indexed_'+uuid4().hex
    with MongoClient(uri,serverSelectionTimeoutMS=5000) as client:
        try:yield client[name].media_files
        finally:client.drop_database(name)


@pytest.mark.parametrize('use_caption',[False,True])
def test_real_mongo_candidate_and_legacy_match_sets_are_identical(mongo_collection,use_caption):
    col=mongo_collection
    names=['Spring of Youth','Sprng of Youth','Youth Spring','Doctor X Mafia in White S01E03 540p',
        'can thus love','can this lobe','İnk show','ıNK show','KDrama','ſhow','maße','theẤ',
        'of\u0307youth','Doctor_X_Mafia','Unrelated title','Dae Jo Yeong']
    docs=[{'_id':str(i),'file_name':name,'caption':'Caption '+name,'indexed_at':i} for i,name in enumerate(names)]
    docs.extend([{'_id':'array-split','file_name':['doctor','mafia']},
        {'_id':'array-whole','file_name':['doctor mafia']},
        {'_id':'cross-field','file_name':'doctor','caption':'mafia'},
        {'_id':'missing','caption':'spring of youth'},
        {'_id':'legacy','file_name':'spring of youth'},
        {'_id':'future','file_name':'spring of youth'},
        {'_id':'nulls','file_name':None,'caption':None}])
    col.insert_many(docs)
    col.create_index(SEARCH_TOKEN_INDEX['keys'],name=SEARCH_TOKEN_INDEX['name'])
    assert backfill(col)['needs_update']==len(docs)
    assert backfill(col,apply=True,batch_size=3)['modified']==len(docs)
    assert backfill(col,apply=True)['modified']==0
    col.update_one({'_id':'legacy'},{'$unset':{SEARCH_TOKEN_FIELD:'',SEARCH_TOKEN_VERSION_FIELD:''}})
    col.update_one({'_id':'future'},{'$set':{SEARCH_TOKEN_VERSION_FIELD:2}})
    for query in ['spring of youth','sprng of youth','youth spring','doctor mafia','doctor x mafia s01e03 540p',
                  'can this love','ink show','kdrama','show','ma','the','youth','한국어','s01e03 540p','zzqa no match']:
        query=normalize_query(query)
        old=build_media_search_filter(query,use_caption=use_caption)
        new=build_media_search_filter(query,use_caption=use_caption,indexed_tokens=True)
        assert sorted(d['_id'] for d in col.find(new))==sorted(d['_id'] for d in col.find(old)),query
    assert backfill(col,apply=True,rollback=True)['modified']>0
    assert col.count_documents({SEARCH_TOKEN_VERSION_FIELD:{'$exists':True}})==0


@pytest.mark.parametrize('batch_size,limit',[(0,1),(1001,1),(1,0),(1,10000001),
    (True,1),(1,True),(1.5,1),(1,1.5)])
def test_backfill_rejects_invalid_bounds(batch_size,limit):
    with pytest.raises(ValueError):backfill(None,batch_size=batch_size,limit=limit)


def test_backfill_bounds_and_concurrent_edits(mongo_collection):
    col=mongo_collection
    col.insert_many([{'_id':str(i),'file_name':'Old doctor'} for i in range(3)])
    report=backfill(col,apply=True,limit=1)
    assert report['scanned']==1 and report['modified']==1 and report['truncated']
    assert col.count_documents({SEARCH_TOKEN_VERSION_FIELD:1})==1
    class ConcurrentEdit:
        def find(self,*args,**kwargs):return col.find(*args,**kwargs)
        def bulk_write(self,operations,**kwargs):
            col.update_many({}, {'$set':{'file_name':'New spring'}})
            return col.bulk_write(operations,**kwargs)
    report=backfill(ConcurrentEdit(),apply=True)
    assert report['needs_update']==2 and report['matched']==0
    assert backfill(col,apply=True)['modified']==3


def test_backfill_does_not_accept_nested_array_as_unchanged_source_text(mongo_collection):
    col=mongo_collection
    original=['doctor','spring']
    col.insert_one({'_id':'array-edit','file_name':original})
    class NestedArrayEdit:
        def find(self,*args,**kwargs):return col.find(*args,**kwargs)
        def bulk_write(self,operations,**kwargs):
            col.update_one({}, {'$set':{'file_name':[original,'mafia']}})
            return col.bulk_write(operations,**kwargs)
    result=backfill(NestedArrayEdit(),apply=True)
    assert result['matched']==0
    legacy=build_media_search_filter('mafia')
    indexed=build_media_search_filter('mafia',indexed_tokens=True)
    assert col.count_documents(legacy)==col.count_documents(indexed)==1


def test_optional_manifest_and_new_media_metadata(monkeypatch):
    from core.database.media_indexes import media_index_manifest
    legacy=media_index_manifest()
    extended=media_index_manifest(include_search_tokens=True)
    assert len(extended)==len(legacy)+2 and extended[-1]==SEARCH_TOKEN_INDEX
    extended[-1]['keys'].clear()
    assert media_index_manifest(include_search_tokens=True)[-1]['keys']
    monkeypatch.setattr(settings.features,'feature_indexed_media_search',True)
    raw=MediaRepository(None,None)._entity_to_dict(fixture_file())
    assert raw[SEARCH_TOKEN_VERSION_FIELD]==1
    assert 'spring' in raw[SEARCH_TOKEN_FIELD]


def test_profiler_deep_page_uses_the_runtime_optional_sort_index(mongo_collection):
    from core.utils.search_tokens import SEARCH_PAGE_INDEX
    from scripts.profile_media_search import profile
    for spec in (SEARCH_TOKEN_INDEX,SEARCH_PAGE_INDEX):
        mongo_collection.create_index(spec['keys'],name=spec['name'])
    mongo_collection.insert_one({'_id':'one','file_name':'show 540p','indexed_at':'2026-10-29'})
    result=profile(mongo_collection.database,('540p',),offsets=(1000,),indexed_tokens=True)
    page=result['queries'][0]['pages'][0]
    assert page['executionSuccess'] is True and SEARCH_PAGE_INDEX['name'] in page['indexesUsed']
    assert 'SORT' not in page['stages']


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled',[False,True])
async def test_text_update_invalidates_tokens_atomically_even_after_flag_rollback(monkeypatch,enabled):
    monkeypatch.setattr(settings.features,'feature_indexed_media_search',enabled)
    repo=MediaRepository(None,SimpleNamespace())
    file=fixture_file();repo.find_file=AsyncMock(return_value=file)
    col=SimpleNamespace(update_one=AsyncMock(return_value=SimpleNamespace(matched_count=1,upserted_id=None)))
    repo.collection=AsyncMock(return_value=col)
    async def run(fn,*args,**kwargs):return await fn(*args,**kwargs)
    repo.db_pool=SimpleNamespace(execute_with_retry=run)
    repo.cache_invalidator=SimpleNamespace(invalidate_file_cache=AsyncMock(),invalidate_file_stats=AsyncMock(),invalidate_all_search_results=AsyncMock())
    repo._base_cache_invalidator=SimpleNamespace(invalidate_cache_key=AsyncMock())
    changes={'file_name':'New title'}
    assert await repo.update('qa-file',changes)
    operation=col.update_one.await_args.args[1]
    assert operation['$set']==changes
    assert set(operation['$unset'])=={SEARCH_TOKEN_FIELD,SEARCH_TOKEN_VERSION_FIELD}
    assert changes=={'file_name':'New title'}


@pytest.mark.asyncio
@pytest.mark.parametrize('multi',[False,True])
@pytest.mark.parametrize('enabled,offset,expected',[(False,1000,False),(True,0,False),(True,1000,True)])
async def test_deep_sort_index_only_used_when_optional_index_is_enabled(monkeypatch,multi,enabled,offset,expected):
    from core.utils.search_tokens import SEARCH_PAGE_INDEX
    monkeypatch.setattr(settings.features,'feature_indexed_media_search',enabled)
    cache=SimpleNamespace(get=AsyncMock(return_value=None),set=AsyncMock(),
        ensure_search_generation=AsyncMock(return_value=1))
    manager=SimpleNamespace(count_across_all_databases=AsyncMock(return_value=1100),
        search_across_all_databases=AsyncMock(return_value=[])) if multi else None
    repo=MediaRepository(None,cache,manager)
    repo._read_search_generation=AsyncMock(return_value=1)
    repo.count=AsyncMock(return_value=1100);repo.find_many=AsyncMock(return_value=[])
    await repo.search_files('540p',offset=offset)
    call=manager.search_across_all_databases if multi else repo.find_many
    assert call.await_args.kwargs.get('sort_index_hint')==(SEARCH_PAGE_INDEX['name'] if expected else None)
