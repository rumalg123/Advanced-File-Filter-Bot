"""Recoverable channel indexing jobs. PH-005.

Opt-in only (PROCESSING_DURABLE_INDEXING=true). Writes to a NEW collection,
channel_index_jobs; no existing media_files or indexed_channels schema changes.

At-least-once processing: a crash before ack leaves a leased job that can be
reclaimed. media_files' existing unique file identity makes retries idempotent.
"""
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from pymongo import ASCENDING, ReturnDocument

from core.utils.logger import get_logger

logger = get_logger(__name__)


class ChannelIndexJobRepository:
    COLLECTION = "channel_index_jobs"
    MAX_ATTEMPTS = 7

    def __init__(self, db_pool, *, lease_seconds: int = 180):
        self.db_pool = db_pool
        self.lease_seconds = lease_seconds
        self._collection = None

    async def collection(self):
        if self._collection is None:
            self._collection = await self.db_pool.get_collection(self.COLLECTION)
        return self._collection

    async def ensure_indexes(self):
        """Indexes exist only on the new opt-in job collection."""
        collection = await self.collection()
        await collection.create_index(
            [("status", ASCENDING), ("next_attempt_at", ASCENDING),
             ("created_at", ASCENDING)],
            name="channel_job_pending",
        )
        await collection.create_index(
            [("status", ASCENDING), ("lease_until", ASCENDING)],
            name="channel_job_reclaim",
        )
        # Only acknowledged successes expire; dead letters remain inspectable.
        await collection.create_index(
            "finished_at", expireAfterSeconds=30 * 24 * 3600,
            name="channel_job_done_retention",
        )

    async def enqueue(self, chat_id: int, message_id: int, media: dict):
        """Idempotently persist before returning from the update handler."""
        now = datetime.now(UTC)
        job_id = f"{chat_id}:{message_id}"
        collection = await self.collection()
        result = await collection.update_one(
            {"_id": job_id},
            {"$setOnInsert": {
                "chat_id": chat_id,
                "message_id": message_id,
                "media": media,
                "status": "pending",
                "attempts": 0,
                "created_at": now,
                "next_attempt_at": now,
            }},
            upsert=True,
        )
        return result.upserted_id is not None

    async def claim(self):
        """Atomically lease a pending or abandoned job to one worker."""
        now = datetime.now(UTC)
        token = uuid4().hex
        collection = await self.collection()
        return await collection.find_one_and_update(
            {"$or": [
                {"status": "pending", "next_attempt_at": {"$lte": now}},
                {"status": "processing", "lease_until": {"$lte": now}},
            ]},
            {"$set": {
                "status": "processing",
                "lease_token": token,
                "lease_until": now + timedelta(seconds=self.lease_seconds),
                "started_at": now,
            }, "$inc": {"attempts": 1}},
            sort=[("created_at", ASCENDING)],
            return_document=ReturnDocument.AFTER,
        )

    async def acknowledge(self, job: dict) -> bool:
        """Ack only if we still own the lease (prevent stale-worker ack)."""
        collection = await self.collection()
        result = await collection.update_one(
            {"_id": job["_id"], "status": "processing",
             "lease_token": job["lease_token"]},
            {"$set": {"status": "done", "finished_at": datetime.now(UTC)},
             "$unset": {"lease_until": "", "lease_token": ""}},
        )
        return result.modified_count == 1

    async def fail(self, job: dict, error: Exception | str) -> str:
        """Retry with backoff, or retain a dead letter after MAX_ATTEMPTS."""
        attempts = int(job.get("attempts", 1))
        exhausted = attempts >= self.MAX_ATTEMPTS
        delay = min(300, 2 ** min(attempts, 8))
        now = datetime.now(UTC)
        update = {
            "status": "dead" if exhausted else "pending",
            "last_error": str(error)[:300],
            "failed_at": now,
        }
        if not exhausted:
            update["next_attempt_at"] = now + timedelta(seconds=delay)
        collection = await self.collection()
        result = await collection.update_one(
            {"_id": job["_id"], "status": "processing",
             "lease_token": job["lease_token"]},
            {"$set": update, "$unset": {"lease_until": "", "lease_token": ""}},
        )
        if result.modified_count != 1:
            logger.warning("Indexing job lease was lost before failure recording: %s", job["_id"])
            return "lease_lost"
        if exhausted:
            logger.error(
                "Indexing job exhausted retries; left as dead letter: %s", job["_id"]
            )
        return update["status"]

    async def counts(self) -> dict[str, int]:
        """Read-only queue inspection, suitable for health dashboards."""
        collection = await self.collection()
        return {
            status: await collection.count_documents({"status": status})
            for status in ("pending", "processing", "dead")
        }

    async def retry_dead(self, job_id: str) -> bool:
        """Explicit operator-driven replay; never automatically erase failures."""
        collection = await self.collection()
        result = await collection.update_one(
            {"_id": job_id, "status": "dead"},
            {"$set": {"status": "pending", "next_attempt_at": datetime.now(UTC),
                      "attempts": 0},
             "$unset": {"last_error": "", "failed_at": ""}},
        )
        return result.modified_count == 1
