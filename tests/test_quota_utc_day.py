"""PH-021: UTC daily quotas, atomic rollover, and original-day refunds.

Only disposable localhost MongoDB is used by the integration scenario.
"""
import asyncio
import os
from datetime import UTC, date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from core.utils.premium import format_user_plan_status
from core.utils.quota_calendar import QuotaReservation, quota_day_utc
from repositories.user import User, UserRepository
from scripts.profile_media_search import is_local


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        (datetime(2026, 10, 28, 23, 59, 59, tzinfo=UTC), date(2026, 10, 28)),
        (datetime(2026, 10, 29, 0, 0, 0, tzinfo=UTC), date(2026, 10, 29)),
        # At Colombo midnight, the UTC quota day is still yesterday.
        (datetime(2026, 10, 29, 0, 15,
                  tzinfo=timezone(timedelta(hours=5, minutes=30))),
         date(2026, 10, 28)),
        (datetime(2026, 10, 28, 20, 15,
                  tzinfo=timezone(timedelta(hours=-4))),
         date(2026, 10, 29)),
    ],
)
def test_explicit_utc_day_ignores_server_and_offset_calendar(instant, expected):
    assert quota_day_utc(instant) == expected


def test_naive_quota_instants_are_rejected_and_reservations_preserve_day():
    with pytest.raises(ValueError, match="timezone-aware"):
        quota_day_utc(datetime(2026, 10, 29))
    amount = QuotaReservation(5, "2026-10-28")
    assert isinstance(amount, int) and amount == 5
    assert amount.quota_day == "2026-10-28"
    partial = amount - 3
    assert isinstance(partial, QuotaReservation)
    assert partial == 2 and partial.quota_day == amount.quota_day
    assert amount - 5 == 0 and (amount - 5).quota_day == amount.quota_day
    assert amount - 6 == -1
    with pytest.raises(ValueError):
        QuotaReservation(-1, "2026-10-29")


class Pool:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def execute_with_retry(self, function, *args, **kwargs):
        self.calls.append((function, args, kwargs))
        return self.result


def stub_repo(pool):
    repo = UserRepository(pool, SimpleNamespace(), daily_limit=10)
    repo.get_collection = AsyncMock(
        return_value=SimpleNamespace(
            find_one_and_update=lambda: None, update_one=lambda: None
        )
    )
    repo.cache_invalidator = SimpleNamespace(
        invalidate_user_data=AsyncMock(),
        invalidate_user_stats=AsyncMock(),
    )
    repo.get_user = AsyncMock(return_value=User(id=42, name="user"))
    return repo


@pytest.mark.asyncio
async def test_retrieval_increment_rollover_is_single_atomic_pipeline(monkeypatch):
    monkeypatch.setattr("repositories.user.quota_day_utc", lambda *a: date(2026, 10, 29))
    pool = Pool({"daily_retrieval_count": 5})
    repo = stub_repo(pool)
    assert await repo.increment_retrieval_count_batch(42, 3) == 5
    assert len(pool.calls) == 1
    _fn, args, kw = pool.calls[0]
    assert kw["return_document"] is True
    assert args[0] == {"_id": 42}
    stage = args[1][0]["$set"]
    assert stage["last_retrieval_date"] == "2026-10-29"
    assert stage["daily_retrieval_count"]["$cond"][2] == 3
    assert stage["daily_retrieval_count"]["$cond"][1]["$add"][-1] == 3
    assert await repo.increment_retrieval_count(42) == 5
    assert len(pool.calls) == 2


@pytest.mark.asyncio
async def test_reservation_day_tag_flows_into_refund_guard(monkeypatch):
    monkeypatch.setattr("repositories.user.quota_day_utc", lambda *a: date(2026, 10, 28))
    pool = Pool({"daily_retrieval_count": 4})
    repo = stub_repo(pool)
    success, reserved, _ = await repo.reserve_quota_atomic(42, 4, 10)
    assert success and reserved == 4 and reserved.quota_day == "2026-10-28"
    _fn, args, kw = pool.calls[0]
    assert args[0]["$or"][0]["last_retrieval_date"] == {"$ne": "2026-10-28"}
    assert args[1][0]["$set"]["last_retrieval_date"] == "2026-10-28"
    pool.result = SimpleNamespace(modified_count=1)
    # Midnight happens between reservation and refund.
    monkeypatch.setattr("repositories.user.quota_day_utc", lambda *a: date(2026, 10, 29))
    assert await repo.release_quota(42, reserved - 1)
    _fn, args, kw = pool.calls[-1]
    assert args[0]["last_retrieval_date"] == "2026-10-28"
    assert args[0]["daily_retrieval_count"] == {"$gte": 3}
    assert args[1]["$inc"]["daily_retrieval_count"] == -3
    # Untagged older callers remain day-scoped to *current* UTC date.
    assert await repo.release_quota(42, 1)
    assert pool.calls[-1][1][0]["last_retrieval_date"] == "2026-10-29"


def test_plan_status_uses_utc_without_modifying_legacy_day_values(monkeypatch):
    monkeypatch.setattr("core.utils.premium.quota_day_utc", lambda: date(2026, 10, 29))
    user = User(
        id=42, name="Free", daily_retrieval_count=10,
        last_retrieval_date=date(2026, 10, 28)
    )
    text = format_user_plan_status(user, daily_limit=10)
    assert "Today's Usage: 0/10" in text
    assert user.last_retrieval_date == date(2026, 10, 28)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_disposable_mongo_concurrent_midnight_reservations_and_refund(monkeypatch):
    uri = os.getenv("TEST_MONGO_URI")
    if not uri:
        pytest.skip("Requires the disposable CI MongoDB service")
    assert is_local(uri), "Never write integration fixtures to a remote MongoDB"
    name = "ph021_ci_" + uuid4().hex
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)

    class MongoPool:
        async def get_collection(self, collection_name):
            assert collection_name == "users"
            return client[name].users

        async def execute_with_retry(self, operation, *args, **kwargs):
            return await operation(*args, **kwargs)

    try:
        collection = client[name].users
        await collection.insert_one({
            "_id": 42, "name": "Fixture", "status": "active",
            "daily_retrieval_count": 9, "last_retrieval_date": "2026-10-28"
        })
        repo = UserRepository(MongoPool(), SimpleNamespace(), daily_limit=10)
        repo.cache_invalidator = SimpleNamespace(
            invalidate_user_data=AsyncMock(),
            invalidate_user_stats=AsyncMock(),
        )
        repo.get_user = AsyncMock(return_value=User(id=42, name="Fixture"))

        async def uncached_user(uid, *, use_cache=False):
            data = await collection.find_one({"_id": uid})
            return repo._dict_to_entity(data)

        repo.find_by_id = uncached_user
        monkeypatch.setattr("repositories.user.quota_day_utc", lambda *a: date(2026, 10, 29))

        # 25 concurrent requests after rollover must consume no more than 10.
        results = await asyncio.gather(*[
            repo.reserve_quota_atomic(42, 1, 10) for _ in range(25)
        ])
        accepted = [count for ok, count, _msg in results if ok]
        assert len(accepted) == 10
        assert all(isinstance(x, QuotaReservation) for x in accepted)
        assert all(x.quota_day == "2026-10-29" for x in accepted)
        current = await collection.find_one({"_id": 42})
        assert current["last_retrieval_date"] == "2026-10-29"
        assert current["daily_retrieval_count"] == 10

        # An old-day refund cannot subtract newly reserved day-2 quota.
        old = QuotaReservation(4, "2026-10-28")
        assert not await repo.release_quota(42, old)
        assert (await collection.find_one({"_id": 42}))["daily_retrieval_count"] == 10

        # A current-day partial refund returns only unused slots.
        assert await repo.release_quota(42, accepted[0])
        assert (await collection.find_one({"_id": 42}))["daily_retrieval_count"] == 9
        assert await repo.reserve_quota_atomic(42, 1, 10)
        assert (await collection.find_one({"_id": 42}))["daily_retrieval_count"] == 10
        # Guard against overdraft: reject more than the actual current count.
        assert not await repo.release_quota(42, QuotaReservation(11, "2026-10-29"))
        assert (await collection.find_one({"_id": 42}))["daily_retrieval_count"] == 10

        # Existing ISO string fields are preserved; no new collection/index.
        assert sorted(await collection.index_information()) == ["_id_"]
    finally:
        await client.drop_database(name)
        client.close()
