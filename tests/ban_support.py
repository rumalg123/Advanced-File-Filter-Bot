from copy import deepcopy
from types import SimpleNamespace

from core.cache.config import CacheKeyGenerator
from repositories.user import User, UserRepository, UserStatus


class Cache:
    def __init__(self): self.values={}
    async def get(self,key): return deepcopy(self.values.get(key))
    async def set(self,key,value,**kwargs): self.values[key]=deepcopy(value);return True
    async def delete(self,*keys):
        for key in keys:self.values.pop(key,None)
        return True
    async def delete_pattern(self,*args): return 0


async def user_repository(storage,monkeypatch,*,status=UserStatus.ACTIVE):
    _,pool,db=storage
    import repositories.user as module
    monkeypatch.setattr(module,'_feature_config',SimpleNamespace(disable_premium=True,
        request_warning_limit=3,request_per_day=1,request_only_for_premium=False))
    monkeypatch.setattr(module,'_channel_config',SimpleNamespace(get_admin_list=lambda:[1]))
    cache=Cache();repo=UserRepository(pool,cache)
    user=User(id=42,name='QA user',status=status)
    await db.users.insert_one(repo._entity_to_dict(user))
    return repo,cache,db


def prime(repo,cache,user):
    cache.values[CacheKeyGenerator.user(user.id)]=repo._entity_to_dict(user)
