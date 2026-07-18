from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from repositories.batch_link import BatchLink, BatchLinkRepository


class MemoryCache:
    def __init__(self, value=None):
        self.value = value
        self.deleted = []

    async def get(self, _key):
        return dict(self.value) if isinstance(self.value, dict) else self.value

    async def set(self, _key, _value, expire=None):
        return True

    async def delete(self, key):
        self.deleted.append(key)
        return True


class DeletePool:
    async def get_collection(self, _name):
        return SimpleNamespace(delete_one=lambda *_args, **_kwargs: None)

    async def execute_with_retry(self, _func, *_args, **_kwargs):
        return SimpleNamespace(deleted_count=1)


def make_link(expires_at):
    return BatchLink(
        id="batch-id",
        source_chat_id=-1001,
        from_msg_id=1,
        to_msg_id=2,
        expires_at=expires_at
    )


def test_expiry_is_serialized_as_bson_datetime():
    repo = BatchLinkRepository(DeletePool(), MemoryCache())
    expiry = datetime.now(UTC) + timedelta(hours=1)

    document = repo._entity_to_dict(make_link(expiry))

    assert document["expires_at"] == expiry
    assert isinstance(document["expires_at"], datetime)


@pytest.mark.asyncio
async def test_expired_cached_batch_link_is_rejected_and_deleted():
    expiry = datetime.now(UTC) - timedelta(minutes=1)
    link = make_link(expiry)
    cached = {
        "_id": link.id,
        "source_chat_id": link.source_chat_id,
        "from_msg_id": link.from_msg_id,
        "to_msg_id": link.to_msg_id,
        "protected": False,
        "premium_only": False,
        "created_by": 0,
        "created_at": link.created_at.isoformat(),
        "expires_at": expiry.isoformat()
    }
    cache = MemoryCache(cached)
    repo = BatchLinkRepository(DeletePool(), cache)

    assert await repo.get_batch_link("batch-id") is None
    assert cache.deleted
