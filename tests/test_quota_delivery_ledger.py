"""PH-022 opt-in quota settlement: durable idempotency and uncertain send outcomes."""
import asyncio
import os
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from config.settings import settings
from core.utils.quota_calendar import QuotaReservation
from core.utils.quota_delivery import settle_delivery_quota
from repositories.user import User, UserRepository
from scripts.profile_media_search import is_local


class Cache:
    async def get(self, *_a, **_kw):
        return None
    async def delete(self, *_a, **_kw):
        return True


@pytest.mark.asyncio
async def test_shared_settlement_preserves_legacy_refund_and_avoids_noop_writes():
    repo = SimpleNamespace(release_quota=AsyncMock(return_value=True))
    assert await settle_delivery_quota(repo, 42, 5, 2)
    repo.release_quota.assert_awaited_once_with(42, 3)
    repo.release_quota.reset_mock()
    assert await settle_delivery_quota(repo, 42, 1, 1)
    repo.release_quota.assert_not_awaited()
    assert await settle_delivery_quota(repo, 42, 1, 0, uncertain=True)
    repo.release_quota.assert_awaited_once_with(42, 1)


@pytest.mark.asyncio
async def test_tokenized_settlement_records_unknown_instead_of_refunding():
    repo = SimpleNamespace(
        release_quota=AsyncMock(),
        settle_quota_delivery=AsyncMock(return_value=True),
    )
    reservation = QuotaReservation(4, "2026-10-29", "token-1")
    assert await settle_delivery_quota(repo, 42, reservation, 2, uncertain=True)
    repo.settle_quota_delivery.assert_awaited_once_with(
        42, reservation, 2, uncertain=True
    )
    repo.release_quota.assert_not_awaited()
    assert (reservation - 2).reservation_id == "token-1"
    assert (reservation - 2).original_amount == 4


@pytest.mark.parametrize("amount,confirmed", [(1, 2), (1, -1), (3, 4)])
@pytest.mark.asyncio
async def test_invalid_confirmation_count_never_updates_quota(amount, confirmed):
    repo = SimpleNamespace(settle_quota_delivery=AsyncMock())
    with pytest.raises(ValueError):
        await settle_delivery_quota(repo, 42, QuotaReservation(amount, date(2026, 10, 29), "id"), confirmed)
    repo.settle_quota_delivery.assert_not_awaited()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_mongo_idempotent_quota_settlement_and_midnight_recovery(monkeypatch):
    uri = os.getenv("TEST_MONGO_URI")
    if not uri:
        pytest.skip("Requires disposable CI MongoDB")
    assert is_local(uri), "NEVER run writes against remote production MongoDB"
    monkeypatch.setattr(settings.features, "feature_quota_delivery_ledger", True)
    day = {"value": date(2026, 10, 29)}
    monkeypatch.setattr("repositories.user.quota_day_utc", lambda *a: day["value"])
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
    name = "ph022_ci_" + uuid4().hex

    class Pool:
        async def get_collection(self, collection_name):
            assert collection_name == "users"
            return client[name].users
        async def execute_with_retry(self, func, *args, **kwargs):
            return await func(*args, **kwargs)

    try:
        users = client[name].users
        await users.insert_one({
            "_id": 42, "name": "Fixture", "status": "active",
            "daily_retrieval_count": 0,
            "last_retrieval_date": "2026-10-29",
        })
        repo = UserRepository(Pool(), Cache(), daily_limit=10)
        repo.get_user = AsyncMock(return_value=User(id=42, name="Fixture"))
        repo.cache_invalidator = SimpleNamespace(
            invalidate_user_data=AsyncMock(),
            invalidate_user_stats=AsyncMock()
        )
        async def fresh(uid, *, use_cache=False):
            obj = await users.find_one({"_id": uid})
            return repo._dict_to_entity(obj)
        repo.find_by_id = fresh

        ok, first, _ = await repo.reserve_quota_atomic(42, 4, 10)
        assert ok and isinstance(first, QuotaReservation)
        assert first.reservation_id and first.original_amount == 4
        assert (await users.find_one({"_id": 42}))["daily_retrieval_count"] == 4

        # 20 competing settlements of the SAME reservation may refund only once.
        results = await asyncio.gather(*[
            settle_delivery_quota(repo, 42, first, 2)
            for _ in range(20)
        ])
        assert sum(results) == 1
        data = await users.find_one({"_id": 42})
        assert data["daily_retrieval_count"] == 2
        assert data["quota_delivery_ledger"][0]["status"] == "settled"
        assert data["quota_delivery_ledger"][0]["refund_count"] == 2
        assert not await repo.release_quota(42, first - 2)

        # Unknown Telegram outcome does not auto-credit the user.
        ok, second, _ = await repo.reserve_quota_atomic(42, 3, 10)
        assert ok
        assert await settle_delivery_quota(repo, 42, second, 1, uncertain=True)
        data = await users.find_one({"_id": 42})
        assert data["daily_retrieval_count"] == 5
        assert any(x["id"] == second.reservation_id and x["status"] == "uncertain"
                   for x in data["quota_delivery_ledger"])
        assert not await repo.release_quota(42, second - 1)
        assert not await repo.resolve_uncertain_quota(42, second.reservation_id, 3)
        assert await repo.resolve_uncertain_quota(42, second.reservation_id, 1)
        assert not await repo.resolve_uncertain_quota(42, second.reservation_id, 1)
        assert (await users.find_one({"_id": 42}))["daily_retrieval_count"] == 4

        # A new reservation prunes resolved audit entries but retains unresolved.
        ok, third, _ = await repo.reserve_quota_atomic(42, 2, 10)
        assert ok
        data = await users.find_one({"_id": 42})
        assert [x["id"] for x in data["quota_delivery_ledger"]] == [third.reservation_id]
        assert data["daily_retrieval_count"] == 6

        # After rollover, an old-day refund cannot decrement a new day.
        day["value"] = date(2026, 10, 30)
        ok, fourth, _ = await repo.reserve_quota_atomic(42, 1, 10)
        assert ok and fourth.quota_day == "2026-10-30"
        assert not await repo.release_quota(42, third)
        rollover_doc = await users.find_one({"_id": 42})
        assert rollover_doc["daily_retrieval_count"] == 1
        # PH-022: unresolved earlier-day reservations MUST survive filtering
        # when new quota is reserved and cannot silently disappear.
        unresolved_ids = {x["id"] for x in rollover_doc["quota_delivery_ledger"]}
        assert third.reservation_id in unresolved_ids
        assert fourth.reservation_id in unresolved_ids
        assert await repo.release_quota(42, fourth)
        assert (await users.find_one({"_id": 42}))["daily_retrieval_count"] == 0

        # The user DTO ignores the internal ledger without rewriting it.
        dto = repo._dict_to_entity(await users.find_one({"_id": 42}))
        assert dto.id == 42 and not hasattr(dto, "quota_delivery_ledger")
        assert sorted(await users.index_information()) == ["_id_"]
    finally:
        await client.drop_database(name)
        client.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_many_unresolved_reservations_fail_closed_without_trimming(monkeypatch):
    uri = os.getenv("TEST_MONGO_URI")
    if not uri:
        pytest.skip("Disposable MongoDB required")
    assert is_local(uri), "Remote integration writes forbidden"
    monkeypatch.setattr(settings.features, "feature_quota_delivery_ledger", True)
    name = "ph022_cap_" + uuid4().hex
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)

    class Pool:
        async def get_collection(self, name_):
            return client[name][name_]
        async def execute_with_retry(self, fn, *a, **kw):
            return await fn(*a, **kw)

    try:
        await client[name].users.insert_one({
            "_id": 42, "name": "Test", "status": "active",
            "last_retrieval_date": "2026-10-28",
            "daily_retrieval_count": 0,
            "quota_delivery_ledger": [{
                "id": f"old-{i}", "day": "2026-10-28",
                "amount": 1, "status": "uncertain",
            } for i in range(256)]
        })
        repo = UserRepository(Pool(), Cache(), daily_limit=10)
        repo.cache_invalidator = SimpleNamespace(
            invalidate_user_data=AsyncMock(), invalidate_user_stats=AsyncMock()
        )
        repo.get_user = AsyncMock(return_value=User(id=42, name="Test"))
        monkeypatch.setattr("repositories.user.quota_day_utc", lambda *a: date(2026, 10, 29))
        allowed, reserved, message = await repo.reserve_quota_atomic(42, 1, 10)
        assert not allowed and reserved == 0
        assert "operator review" in message
        obj = await client[name].users.find_one({"_id": 42})
        assert obj["daily_retrieval_count"] == 0
        assert len(obj["quota_delivery_ledger"]) == 256
    finally:
        await client.drop_database(name)
        client.close()
