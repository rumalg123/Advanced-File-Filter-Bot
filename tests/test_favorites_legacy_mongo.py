import pytest
from favorites_recent_support import storage
from repositories.features import collection_callback_token

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_legacy_collection_read_persists_its_callback_token(storage):
    repository,_,db = storage
    document={'_id':'42:legacy','user_id':42,'name':'Legacy collection',
        'normalized_name':'legacy collection','file_ids':['qa-file']}
    await db.user_collections.insert_one(document)
    loaded = await repository.get_collection(42,'Legacy collection')
    token = collection_callback_token(loaded)
    assert (await db.user_collections.find_one({'_id':'42:legacy'})).get('callback_token')==token
    assert (await repository.get_collection_by_token(42,token))['_id']=='42:legacy'
    assert await repository.get_collection_by_token(99,token) is None
