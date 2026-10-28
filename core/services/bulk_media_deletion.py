"""PH-007: bounded, confirmed, resumable media deletion for a single DB."""
import asyncio
import logging
from types import SimpleNamespace

from core.services.bulk_delete_policy import (
    MAX_BULK_DELETE_FILES, BULK_DELETE_BATCH_SIZE, PREVIEW_SAMPLE_SIZE,
    BulkDeletePreview, BulkDeleteRejected, BulkDeleteInterrupted,
)
from core.utils.validators import normalize_query

logger = logging.getLogger(__name__)


class MediaBulkDeletion:
    def __init__(self, media_repo):
        self.repo = media_repo

    def predicate(self, keyword):
        if not isinstance(keyword, str) or len(keyword.strip()) < 3:
            raise BulkDeleteRejected("Specify at least 3 keyword characters.")
        predicate = self.repo._build_search_filter(
            normalize_query(keyword.strip()), None, True
        )
        if not predicate:
            raise BulkDeleteRejected("Refusing an unbounded deletion predicate.")
        if self.repo.is_multi_db:
            raise BulkDeleteRejected(
                "Keyword deletion is disabled for multi-database deployments."
            )
        return predicate

    async def preview(self, keyword):
        predicate = self.predicate(keyword)
        collection = await self.repo.collection()
        count = await self.repo.db_pool.execute_with_retry(
            collection.count_documents, predicate
        )
        rows = await self.repo.db_pool.execute_with_retry(
            collection.find(predicate, {"_id": 0, "file_name": 1})
            .limit(PREVIEW_SAMPLE_SIZE).to_list,
            length=PREVIEW_SAMPLE_SIZE,
        )
        return BulkDeletePreview(
            keyword=keyword.strip(),
            count=int(count),
            sample=tuple(str(r.get("file_name") or "Unnamed") for r in rows),
        )

    async def execute(self, keyword, *, expected_count, stop_requested=None):
        predicate = self.predicate(keyword)
        if (not isinstance(expected_count, int) or isinstance(expected_count, bool)
                or expected_count <= 0 or expected_count > MAX_BULK_DELETE_FILES):
            raise BulkDeleteRejected(
                f"Confirm between 1 and {MAX_BULK_DELETE_FILES} matches."
            )

        collection = await self.repo.collection()
        deleted = 0
        try:
            actual = await self.repo.db_pool.execute_with_retry(
                collection.count_documents, predicate
            )
            if actual != expected_count:
                raise BulkDeleteRejected(
                    "Match count changed since preview. Start a new preview."
                )

            while deleted < expected_count:
                if stop_requested and stop_requested():
                    raise BulkDeleteInterrupted(
                        "Deletion interrupted; re-preview remaining files to resume.",
                        deleted,
                    )
                limit = min(BULK_DELETE_BATCH_SIZE, expected_count - deleted)
                rows = await self.repo.db_pool.execute_with_retry(
                    collection.find(
                        predicate,
                        {"_id": 1, "file_unique_id": 1, "file_ref": 1},
                    ).limit(limit).to_list,
                    length=limit,
                )
                if not rows:
                    raise BulkDeleteInterrupted(
                        "Matches changed during deletion; re-preview.", deleted
                    )

                result = await self.repo.db_pool.execute_with_retry(
                    collection.delete_many, {"_id": {"$in": [r["_id"] for r in rows]}}
                )
                deleted += int(result.deleted_count)
                # Failures to delete a key may simply mean it was never cached.
                # Record them but always invalidate search generation.
                for row in rows:
                    try:
                        await self.repo.cache_invalidator.invalidate_file_cache(
                            SimpleNamespace(
                                file_unique_id=row.get("file_unique_id"),
                                file_id=row["_id"],
                                file_ref=row.get("file_ref"),
                            )
                        )
                    except Exception:
                        logger.exception("File cache invalidation raised after deletion")
                if not await self.repo.cache_invalidator.invalidate_all_search_results():
                    raise BulkDeleteInterrupted(
                        "Deletion succeeded but search-cache invalidation failed; "
                        "check Redis before continuing.",
                        deleted,
                    )
                if result.deleted_count != len(rows):
                    raise BulkDeleteInterrupted(
                        "Concurrent deletion detected; re-preview remaining files.",
                        deleted,
                    )
                await asyncio.sleep(0)
            logger.warning(
                "PH-007 keyword deletion completed, deleted=%d", deleted
            )
            return deleted
        except (BulkDeleteInterrupted, BulkDeleteRejected):
            raise
        except asyncio.CancelledError:
            logger.warning("PH-007 keyword deletion cancelled, acknowledged=%d", deleted)
            raise
        except Exception as exc:
            logger.exception("PH-007 keyword deletion failed, acknowledged=%d", deleted)
            raise BulkDeleteInterrupted(
                "Database error during deletion; inspect logs and re-preview.",
                deleted,
            ) from exc
