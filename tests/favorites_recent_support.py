"""Local-only favorites compatibility and concurrent recent-history acceptance."""
import os
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from repositories.features import FeatureRepository


@pytest_asyncio.fixture
async def storage():
    uri = os.getenv('TEST_MONGO_URI','')
    if not uri: pytest.skip('Requires disposable local MongoDB')
    assert urlsplit(uri).hostname in ('localhost','127.0.0.1')
    client = AsyncIOMotorClient(uri,serverSelectionTimeoutMS=5000)
    name = 'qa_fav_recent_'+uuid4().hex
    db = client[name]
    class Pool:
        before_delete = None
        async def get_collection(self,name): return db[name]
        async def execute_with_retry(self,operation,*args,**kwargs):
            if getattr(operation,'__name__','')=='delete_many' and self.before_delete:
                hook,self.before_delete = self.before_delete,None
                await hook()
            return await operation(*args,**kwargs)
    pool = Pool()
    try: yield FeatureRepository(pool),pool,db
    finally:
        await client.drop_database(name)
        client.close()
