"""CRUD contracts against a real disposable MongoDB, including failure semantics."""
import asyncio,os
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne
from pymongo.errors import DuplicateKeyError

from core.database.base import BaseRepository,AggregationMixin
from scripts.profile_media_search import is_local


class Cache:
    def __init__(self):self.data={};self.deleted=[]
    async def get(self,key):return deepcopy(self.data.get(key))
    async def set(self,key,value,expire=None):self.data[key]=deepcopy(value);return True
    async def delete(self,key):self.data.pop(key,None);self.deleted.append(key);return True
    async def delete_pattern(self,pattern):
        from fnmatch import fnmatch
        keys=[key for key in self.data if fnmatch(key,pattern)]
        for key in keys:await self.delete(key)
        return len(keys)


class Documents(BaseRepository,AggregationMixin):
    def _entity_to_dict(self,entity):return dict(entity)
    def _dict_to_entity(self,data):
        if 'value' not in data:raise ValueError('incomplete QA document')
        return dict(data)
    def _get_cache_key(self,identifier):return 'qa-document:'+str(identifier)


@pytest.fixture
async def mongo_pool():
    uri=os.getenv('TEST_MONGO_URI')
    if not uri:pytest.skip('Requires disposable local MongoDB')
    assert is_local(uri)
    client=AsyncIOMotorClient(uri,serverSelectionTimeoutMS=5000)
    name='qa_contract_'+uuid4().hex
    class Pool:
        database=client[name]
        calls=0
        async def get_collection(self,collection):self.calls+=1;return self.database[collection]
        async def execute_with_retry(self,fn,*args,**kwargs):return await fn(*args,**kwargs)
    pool=Pool()
    try:yield pool
    finally:await client.drop_database(name);client.close()


@pytest.mark.asyncio
async def test_real_crud_cache_upsert_duplicate_and_aggregate(mongo_pool):
    cache=Cache();repo=Documents(mongo_pool,cache,'qa_docs')
    assert await repo.find_by_id('absent') is None
    assert await repo.create({'_id':'a','value':1,'kind':'alpha'})
    with pytest.raises(DuplicateKeyError):await repo.create({'_id':'a','value':2})
    first=await repo.find_by_id('a');assert first['value']==1
    await mongo_pool.database.qa_docs.update_one({'_id':'a'},{'$set':{'value':9}})
    assert (await repo.find_by_id('a'))['value']==1
    assert (await repo.find_by_id('a',use_cache=False))['value']==9
    cache.data[repo._get_cache_key('a')]={'_id':'a'}
    assert (await repo.find_by_id('a'))['value']==9
    assert await repo.update('a',{'value':3})
    assert (await repo.find_by_id('a'))['value']==3
    assert not await repo.update('absent',{'value':1})
    assert await repo.update('b',{'value':4,'kind':'beta'},upsert=True)
    assert await repo.count()==2
    assert await repo.count({'kind':'alpha'})==1
    assert [r['_id'] for r in await repo.find_many({},sort=[('value',-1)],skip=1,limit=1)]==['a']
    assert len(await repo.find_many({}))==2
    assert await repo.aggregate([{'$group':{'_id':None,'total':{'$sum':'$value'}}}])==[{'_id':None,'total':7}]
    assert sorted(await repo.distinct('kind'))==['alpha','beta']
    assert await repo.distinct('kind',{'_id':'a'})==['alpha']
    assert await repo.bulk_write([])
    assert await repo.bulk_write([UpdateOne({'_id':'b'},{'$set':{'value':7}})])
    assert await repo.create_index([('kind',1)],name='qa_kind')
    assert await repo.delete('a')
    assert not await repo.delete('a')
    assert await repo.count()==1


@pytest.mark.asyncio
async def test_lazy_collection_is_initialized_once_under_concurrency(mongo_pool):
    repo=Documents(mongo_pool,Cache(),'qa_docs')
    results=await asyncio.gather(*(repo.get_collection() for _ in range(30)))
    assert all(x is results[0] for x in results)
    assert mongo_pool.calls==1


@pytest.mark.asyncio
@pytest.mark.parametrize('method,args,fallback',[
    ('find_by_id',('x',),None),('find_many',({},),[]),('create',({'_id':'x','value':1},),False),
    ('update',('x',{'value':2}),False),('delete',('x',),False),('count',(),0),
    ('bulk_write',([object()],),False),('create_index',([('value',1)],),False),
    ('aggregate',([],),[]),('distinct',('value',),[])])
async def test_repository_service_failure_contracts(method,args,fallback):
    pool=SimpleNamespace(get_collection=AsyncMock(side_effect=ConnectionError('QA unavailable')))
    repo=Documents(pool,Cache(),'qa_docs')
    assert await getattr(repo,method)(*args)==fallback


@pytest.mark.asyncio
@pytest.mark.parametrize('method',['find_many','count'])
async def test_strict_search_calls_preserve_backend_error(method):
    repo=Documents(SimpleNamespace(get_collection=AsyncMock(side_effect=ConnectionError('QA'))),Cache(),'qa_docs')
    with pytest.raises(ConnectionError):
        await getattr(repo,method)({},raise_on_error=True)


@pytest.mark.asyncio
async def test_connection_cache_and_group_removal_contract(mongo_pool):
    from repositories.connection import ConnectionRepository
    repo=ConnectionRepository(mongo_pool,Cache())
    assert await repo.find_by_id('12') is None
    assert await repo.add_connection('12','-1001')
    assert await repo.add_connection('12','-1002')
    assert await repo.make_active('12','-1002')
    assert (await repo.find_by_id('12')).active_group=='-1002'
    assert await repo.delete_connection('12','-1002')
    assert (await repo.find_by_id('12')).active_group=='-1001'
    assert await repo.deactivate_all_connections('12')
    assert (await repo.find_by_id('12')).active_group is None
    assert await repo.delete_all_connections('12')
    assert not await repo.delete_connection('12','-1001')


@pytest.mark.asyncio
async def test_filter_repository_real_mutation_invalidates_lookup_and_list(mongo_pool):
    from repositories.filter import FilterRepository
    cache=Cache();repo=FilterRepository(mongo_pool,cache)
    assert await repo.find_filter('-1001','qa')==(None,None,None,None)
    assert await repo.get_filters('-1001')==[]
    assert await repo.add_filter('-1001','qa','First','[]','')
    assert (await repo.find_filter('-1001','qa'))[0]=='First'
    assert await repo.get_filters('-1001')==['qa']
    assert await repo.add_filter('-1001','qa','Second','[]','')
    assert (await repo.find_filter('-1001','qa'))[0]=='Second'
    assert await repo.delete_filter('-1001','qa')==1
    assert await repo.get_filters('-1001')==[]
    assert await repo.add_filter('-1001','one','One','[]','')
    assert await repo.add_filter('-1001','two','Two','[]','')
    await repo.find_filter('-1001','one')
    assert await repo.delete_all_filters('-1001')
    assert await repo.find_filter('-1001','one')==(None,None,None,None)


@pytest.mark.asyncio
async def test_update_is_idempotent_and_returns_boolean_for_every_inserted_id(mongo_pool):
    repo=Documents(mongo_pool,Cache(),'qa_docs')
    assert await repo.create({'_id':'same','value':1})
    assert await repo.update('same',{'value':1}) is True
    assert await repo.update('new-string',{'value':2},upsert=True) is True
    assert await repo.update(0,{'value':3},upsert=True) is True
    assert await repo.update('missing',{'value':4}) is False
