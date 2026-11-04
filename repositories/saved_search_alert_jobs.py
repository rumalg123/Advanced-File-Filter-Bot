"""PH-018 opt-in persisted notification fan-out with lease-fenced checkpoints.

New saved_search_alert_jobs collection only when explicitly enabled.
Delivery claims reuse saved_search_notifications without altering old records.
A successful Telegram API response followed by a crash before ack can retry:
this provides at-least-once (not exactly-once) delivery.
"""
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pymongo import ASCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from core.utils.logger import get_logger

logger = get_logger(__name__)


class SavedSearchAlertJobRepository:
    COLLECTION = "saved_search_alert_jobs"
    MAX_ATTEMPTS = 8

    def __init__(self, db_pool, *, lease_seconds=300, delivery_lease_seconds=120):
        self.db_pool = db_pool
        self.lease_seconds = lease_seconds
        self.delivery_lease_seconds = delivery_lease_seconds

    async def _jobs(self):
        return await self.db_pool.get_collection(self.COLLECTION)

    async def _deliveries(self):
        return await self.db_pool.get_collection("saved_search_notifications")

    async def ensure_indexes(self):
        """Creates indexes ONLY on the new opt-in queue collection."""
        jobs = await self._jobs()
        await jobs.create_index(
            [("status", ASCENDING), ("next_attempt_at", ASCENDING),
             ("created_at", ASCENDING)], name="saved_alert_pending"
        )
        await jobs.create_index(
            [("status", ASCENDING), ("lease_until", ASCENDING)],
            name="saved_alert_reclaim"
        )
        # A done-only marker is the only document carrying finished_at.
        await jobs.create_index(
            "finished_at", expireAfterSeconds=30 * 86400,
            name="saved_alert_completed_retention"
        )

    @staticmethod
    def _job_id(file_unique_id):
        return hashlib.sha256(file_unique_id.encode("utf-8")).hexdigest()

    async def enqueue(self, media):
        if not isinstance(media.file_unique_id, str) or not media.file_unique_id:
            raise ValueError("Cannot queue an alert without media file_unique_id")
        now = datetime.now(UTC)
        snapshot = {
            "file_unique_id": media.file_unique_id,
            "file_id": media.file_id,
            "file_ref": media.file_ref,
            "file_name": media.file_name,
            "file_size": media.file_size,
            "file_type": media.file_type.value,
            "mime_type": media.mime_type,
            "caption": media.caption,
        }
        jobs = await self._jobs()
        result = await jobs.update_one(
            {"_id": self._job_id(media.file_unique_id)},
            {"$setOnInsert": {
                "media": snapshot,
                "status": "pending",
                "after_id": None,
                "attempts": 0,
                "created_at": now,
                "next_attempt_at": now,
            }},
            upsert=True,
        )
        return result.upserted_id is not None

    async def claim(self):
        jobs = await self._jobs()
        now = datetime.now(UTC)
        return await jobs.find_one_and_update(
            {"$or": [
                {"status": "pending", "next_attempt_at": {"$lte": now}},
                {"status": "processing", "lease_until": {"$lte": now}},
            ]},
            {"$set": {
                "status": "processing", "lease_until": now + timedelta(seconds=self.lease_seconds),
                "lease_token": uuid4().hex, "started_at": now,
            }, "$inc": {"attempts": 1}},
            sort=[("created_at", ASCENDING)],
            return_document=ReturnDocument.AFTER,
        )

    async def renew(self, job):
        jobs = await self._jobs()
        now = datetime.now(UTC)
        result = await jobs.update_one(
            {"_id": job["_id"], "status": "processing",
             "lease_token": job["lease_token"], "lease_until": {"$gt": now}},
            {"$set": {"lease_until": now + timedelta(seconds=self.lease_seconds)}},
        )
        return result.modified_count == 1

    async def checkpoint(self, job, after_id):
        jobs = await self._jobs()
        now = datetime.now(UTC)
        result = await jobs.update_one(
            {"_id": job["_id"], "status": "processing",
             "lease_token": job["lease_token"], "lease_until": {"$gt": now}},
            {"$set": {"after_id": after_id, "updated_at": now}},
        )
        return result.matched_count == 1

    async def acknowledge(self, job):
        jobs = await self._jobs()
        now = datetime.now(UTC)
        result = await jobs.update_one(
            {"_id": job["_id"], "status": "processing",
             "lease_token": job["lease_token"], "lease_until": {"$gt": now}},
            {"$set": {"status": "done", "finished_at": now},
             "$unset": {"lease_token": "", "lease_until": ""}},
        )
        return result.modified_count == 1

    async def fail(self, job, error):
        jobs = await self._jobs()
        attempts = int(job.get("attempts", 1))
        is_dead = attempts >= self.MAX_ATTEMPTS
        now = datetime.now(UTC)
        status = "dead" if is_dead else "pending"
        update = {
            "status": status, "last_error_type": type(error).__name__,
            "failed_at": now,
        }
        if not is_dead:
            update["next_attempt_at"] = now + timedelta(
                seconds=min(300, 2 ** min(attempts, 8))
            )
        result = await jobs.update_one(
            {"_id": job["_id"], "status": "processing",
             "lease_token": job["lease_token"]},
            {"$set": update, "$unset": {"lease_token": "", "lease_until": ""}},
        )
        return status if result.modified_count == 1 else "lease_lost"

    async def retry_dead(self, job_id):
        jobs = await self._jobs()
        result = await jobs.update_one(
            {"_id": job_id, "status": "dead"},
            {"$set": {"status": "pending", "attempts": 0,
                      "next_attempt_at": datetime.now(UTC)},
             "$unset": {"last_error_type": "", "failed_at": ""}},
        )
        return result.modified_count == 1

    async def metrics(self):
        jobs = await self._jobs()
        result = {
            key: await jobs.count_documents({"status": key})
            for key in ("pending", "processing", "dead")
        }
        first = await jobs.find_one(
            {"status": "pending"}, sort=[("created_at", ASCENDING)],
            projection={"created_at": 1},
        )
        result["oldest_pending_seconds"] = (
            max(0, int((datetime.now(UTC) - first["created_at"].replace(
                tzinfo=first["created_at"].tzinfo or UTC
            )).total_seconds()))
            if first else None
        )
        return result

    @staticmethod
    def _delivery_id(search_id, file_unique_id):
        return hashlib.sha256(
            f"{search_id}:{file_unique_id}".encode("utf-8")
        ).hexdigest()[:32]

    async def begin_delivery(self, search_id, file_unique_id):
        """Return (status, token): claimed, delivered, or in_flight.

        Old-format claims are conservatively considered delivered to avoid
        duplicate Telegram notifications after switching to durable mode.
        """
        collection = await self._deliveries()
        key = self._delivery_id(search_id, file_unique_id)
        now = datetime.now(UTC)
        token = uuid4().hex
        try:
            await collection.insert_one({
                "_id": key, "search_id": search_id,
                "file_unique_id": file_unique_id, "created_at": now,
                "status": "sending", "lease_token": token,
                "lease_until": now + timedelta(seconds=self.delivery_lease_seconds),
            })
            return "claimed", token
        except DuplicateKeyError:
            pass
        existing = await collection.find_one({"_id": key})
        if not existing:
            # Concurrent delete. Retry the page, rather than skip the recipient.
            return "in_flight", None
        if existing.get("status", "sent") == "sent":
            return "delivered", None
        if existing.get("status") != "sending":
            return "in_flight", None
        result = await collection.update_one(
            {"_id": key, "status": "sending", "lease_until": {"$lte": now}},
            {"$set": {"lease_until": now + timedelta(
                seconds=self.delivery_lease_seconds
            ), "lease_token": token}},
        )
        return ("claimed", token) if result.modified_count else ("in_flight", None)

    async def finish_delivery(self, search_id, file_unique_id, token):
        collection = await self._deliveries()
        result = await collection.update_one(
            {"_id": self._delivery_id(search_id, file_unique_id),
             "status": "sending", "lease_token": token},
            {"$set": {"status": "sent", "sent_at": datetime.now(UTC)},
             "$unset": {"lease_token": "", "lease_until": ""}},
        )
        return result.modified_count == 1

    async def release_delivery(self, search_id, file_unique_id, token):
        collection = await self._deliveries()
        result = await collection.delete_one({
            "_id": self._delivery_id(search_id, file_unique_id),
            "status": "sending", "lease_token": token,
        })
        return result.deleted_count == 1
