"""Additive persistence for opt-in user and content features."""

import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from pymongo.errors import DuplicateKeyError

from core.utils.logger import get_logger

logger = get_logger(__name__)


def normalize_feature_text(value: str) -> str:
    """Normalize user-owned names and queries without changing display text."""
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def collection_slug(value: str) -> str:
    normalized = normalize_feature_text(value)
    slug = re.sub(r"[^a-z0-9_-]+", "-", normalized).strip("-")[:32]
    return slug or "favorites"


class FeatureRepository:
    """Repository spanning isolated collections used only by flagged features."""

    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def _collection(self, name: str):
        return await self.db_pool.get_collection(name)

    async def create_indexes(self) -> dict[str, bool]:
        """Create additive indexes idempotently; startup may continue on failure."""
        definitions = {
            "user_collections": [
                ([('user_id', 1), ('normalized_name', 1)], {
                    'name': 'user_collection_name_idx', 'unique': True, 'background': True
                }),
            ],
            "recent_files": [
                ([('user_id', 1), ('last_accessed_at', -1)], {
                    'name': 'recent_user_time_idx', 'background': True
                }),
            ],
            "saved_searches": [
                ([('user_id', 1), ('normalized_query', 1)], {
                    'name': 'saved_search_user_query_idx', 'unique': True, 'background': True
                }),
                ([('active', 1), ('updated_at', -1)], {
                    'name': 'saved_search_active_idx', 'background': True
                }),
            ],
            "saved_search_notifications": [
                ([('search_id', 1), ('file_unique_id', 1)], {
                    'name': 'saved_search_file_idx', 'unique': True, 'background': True
                }),
                ([('created_at', 1)], {
                    'name': 'saved_search_notification_ttl_idx',
                    'expireAfterSeconds': 15552000,
                    'background': True,
                }),
            ],
            "recommendation_feedback": [
                ([('user_id', 1), ('signal', 1), ('updated_at', -1)], {
                    'name': 'feedback_user_signal_idx', 'background': True
                }),
            ],
            "file_reports": [
                ([('status', 1), ('created_at', -1)], {
                    'name': 'report_status_time_idx', 'background': True
                }),
                ([('file_unique_id', 1), ('status', 1)], {
                    'name': 'report_file_status_idx', 'background': True
                }),
            ],
            "content_requests": [
                ([('user_id', 1), ('created_at', -1)], {
                    'name': 'request_user_time_idx', 'background': True
                }),
                ([('normalized_query', 1), ('status', 1), ('created_at', -1)], {
                    'name': 'request_query_status_idx', 'background': True
                }),
                ([('user_id', 1), ('normalized_query', 1)], {
                    'name': 'request_one_pending_idx',
                    'unique': True,
                    'partialFilterExpression': {'status': 'pending'},
                    'background': True,
                }),
            ],
            "search_analytics": [
                ([('count', -1), ('last_searched_at', -1)], {
                    'name': 'zero_result_count_idx', 'background': True
                }),
            ],
        }

        results = {}
        for collection_name, indexes in definitions.items():
            collection = await self._collection(collection_name)
            for keys, options in indexes:
                index_name = options['name']
                try:
                    await self.db_pool.execute_with_retry(
                        collection.create_index, keys, **options
                    )
                    results[index_name] = True
                except Exception as e:
                    if "already exists" in str(e).lower() or "IndexOptionsConflict" in str(e):
                        results[index_name] = True
                    else:
                        logger.warning(f"Could not create feature index {index_name}: {e}")
                        results[index_name] = False
        return results

    # Favorites and named collections
    async def ensure_collection(self, user_id: int, name: str = "Favorites") -> dict[str, Any]:
        display_name = (name or "Favorites").strip()[:40]
        normalized_name = normalize_feature_text(display_name)
        slug = collection_slug(display_name)
        name_hash = hashlib.sha256(normalized_name.encode()).hexdigest()[:8]
        document_id = f"{user_id}:{slug[:16]}-{name_hash}"
        now = datetime.now(UTC)
        collection = await self._collection("user_collections")
        await self.db_pool.execute_with_retry(
            collection.update_one,
            {'_id': document_id, 'user_id': user_id},
            {
                '$setOnInsert': {
                    'user_id': user_id,
                    'name': display_name,
                    'normalized_name': normalized_name,
                    'file_ids': [],
                    'created_at': now,
                },
                '$set': {'updated_at': now},
            },
            upsert=True
        )
        return await self.db_pool.execute_with_retry(collection.find_one, {'_id': document_id})

    async def add_to_collection(
        self, user_id: int, file_unique_id: str, name: str = "Favorites"
    ) -> bool:
        document = await self.ensure_collection(user_id, name)
        collection = await self._collection("user_collections")
        result = await self.db_pool.execute_with_retry(
            collection.update_one,
            {
                '_id': document['_id'],
                'user_id': user_id,
                '$or': [
                    {'file_ids': file_unique_id},
                    {
                        '$expr': {
                            '$lt': [
                                {'$size': {'$ifNull': ['$file_ids', []]}},
                                100,
                            ]
                        }
                    },
                ],
            },
            {
                '$addToSet': {'file_ids': file_unique_id},
                '$set': {'updated_at': datetime.now(UTC)},
            }
        )
        return bool(result.matched_count)

    async def remove_from_collection(
        self, user_id: int, file_unique_id: str, name: str = "Favorites"
    ) -> bool:
        collection = await self._collection("user_collections")
        result = await self.db_pool.execute_with_retry(
            collection.update_one,
            {
                'user_id': user_id,
                'normalized_name': normalize_feature_text(name),
                'file_ids': file_unique_id,
            },
            {
                '$pull': {'file_ids': file_unique_id},
                '$set': {'updated_at': datetime.now(UTC)},
            }
        )
        return bool(result.modified_count)

    async def list_collections(self, user_id: int, limit: int = 20) -> list[dict[str, Any]]:
        collection = await self._collection("user_collections")
        cursor = collection.find({'user_id': user_id}).sort('updated_at', -1).limit(limit)
        return await self.db_pool.execute_with_retry(cursor.to_list, length=limit)

    async def get_collection(self, user_id: int, name: str = "Favorites") -> dict[str, Any] | None:
        collection = await self._collection("user_collections")
        return await self.db_pool.execute_with_retry(
            collection.find_one,
            {'user_id': user_id, 'normalized_name': normalize_feature_text(name)}
        )

    async def delete_collection(self, user_id: int, name: str) -> bool:
        collection = await self._collection("user_collections")
        result = await self.db_pool.execute_with_retry(
            collection.delete_one,
            {'user_id': user_id, 'normalized_name': normalize_feature_text(name)}
        )
        return bool(result.deleted_count)

    # Recent successful deliveries
    async def record_recent_file(self, user_id: int, file_unique_id: str) -> None:
        collection = await self._collection("recent_files")
        document_id = f"{user_id}:{file_unique_id}"
        now = datetime.now(UTC)
        await self.db_pool.execute_with_retry(
            collection.update_one,
            {'_id': document_id},
            {
                '$set': {
                    'user_id': user_id,
                    'file_unique_id': file_unique_id,
                    'last_accessed_at': now,
                },
                '$setOnInsert': {'created_at': now},
            },
            upsert=True
        )

        # Keep only the newest 50 records per user without touching other users.
        cursor = collection.find(
            {'user_id': user_id}, {'_id': 1}
        ).sort('last_accessed_at', -1).skip(50).limit(100)
        stale = await self.db_pool.execute_with_retry(cursor.to_list, length=100)
        if stale:
            await self.db_pool.execute_with_retry(
                collection.delete_many,
                {'_id': {'$in': [item['_id'] for item in stale]}}
            )

    async def get_recent_files(self, user_id: int, limit: int = 20) -> list[str]:
        collection = await self._collection("recent_files")
        cursor = collection.find(
            {'user_id': user_id}, {'file_unique_id': 1}
        ).sort('last_accessed_at', -1).limit(limit)
        documents = await self.db_pool.execute_with_retry(cursor.to_list, length=limit)
        return [document['file_unique_id'] for document in documents]

    async def clear_recent_files(self, user_id: int) -> int:
        collection = await self._collection("recent_files")
        result = await self.db_pool.execute_with_retry(
            collection.delete_many, {'user_id': user_id}
        )
        return int(result.deleted_count)

    # Saved searches and alert claims
    async def create_saved_search(self, user_id: int, query: str) -> tuple[dict[str, Any], bool]:
        normalized_query = normalize_feature_text(query)
        collection = await self._collection("saved_searches")
        existing = await self.db_pool.execute_with_retry(
            collection.find_one,
            {'user_id': user_id, 'normalized_query': normalized_query}
        )
        if existing:
            return existing, False

        saved_count = await self.db_pool.execute_with_retry(
            collection.count_documents, {'user_id': user_id}
        )
        if saved_count >= 25:
            raise ValueError("A user can save at most 25 searches")

        now = datetime.now(UTC)
        document = {
            '_id': uuid.uuid4().hex[:12],
            'user_id': user_id,
            'query': query.strip()[:100],
            'normalized_query': normalized_query,
            'active': True,
            'created_at': now,
            'updated_at': now,
        }
        try:
            await self.db_pool.execute_with_retry(collection.insert_one, document)
            return document, True
        except DuplicateKeyError:
            existing = await self.db_pool.execute_with_retry(
                collection.find_one,
                {'user_id': user_id, 'normalized_query': normalized_query}
            )
            return existing, False

    async def list_saved_searches(self, user_id: int, limit: int = 20) -> list[dict[str, Any]]:
        collection = await self._collection("saved_searches")
        cursor = collection.find({'user_id': user_id}).sort('updated_at', -1).limit(limit)
        return await self.db_pool.execute_with_retry(cursor.to_list, length=limit)

    async def set_saved_search_active(self, user_id: int, search_id: str, active: bool) -> bool:
        collection = await self._collection("saved_searches")
        result = await self.db_pool.execute_with_retry(
            collection.update_one,
            {'_id': search_id, 'user_id': user_id},
            {'$set': {'active': active, 'updated_at': datetime.now(UTC)}}
        )
        return bool(result.matched_count)

    async def delete_saved_search(self, user_id: int, search_id: str) -> bool:
        collection = await self._collection("saved_searches")
        result = await self.db_pool.execute_with_retry(
            collection.delete_one, {'_id': search_id, 'user_id': user_id}
        )
        if result.deleted_count:
            notifications = await self._collection("saved_search_notifications")
            await self.db_pool.execute_with_retry(
                notifications.delete_many, {'search_id': search_id}
            )
        return bool(result.deleted_count)

    async def get_active_saved_searches(self, limit: int = 500) -> list[dict[str, Any]]:
        collection = await self._collection("saved_searches")
        cursor = collection.find({'active': True}).sort('updated_at', -1).limit(limit)
        return await self.db_pool.execute_with_retry(cursor.to_list, length=limit)

    async def claim_saved_search_notification(self, search_id: str, file_unique_id: str) -> bool:
        collection = await self._collection("saved_search_notifications")
        document = {
            '_id': hashlib.sha256(f"{search_id}:{file_unique_id}".encode()).hexdigest()[:32],
            'search_id': search_id,
            'file_unique_id': file_unique_id,
            'created_at': datetime.now(UTC),
        }
        try:
            await self.db_pool.execute_with_retry(collection.insert_one, document)
            return True
        except DuplicateKeyError:
            return False

    async def release_saved_search_notification(self, search_id: str, file_unique_id: str) -> None:
        collection = await self._collection("saved_search_notifications")
        document_id = hashlib.sha256(f"{search_id}:{file_unique_id}".encode()).hexdigest()[:32]
        await self.db_pool.execute_with_retry(collection.delete_one, {'_id': document_id})

    # Recommendation feedback
    async def set_recommendation_feedback(
        self, user_id: int, file_unique_id: str, signal: str
    ) -> bool:
        collection = await self._collection("recommendation_feedback")
        result = await self.db_pool.execute_with_retry(
            collection.update_one,
            {'_id': f"{user_id}:{file_unique_id}"},
            {
                '$set': {
                    'user_id': user_id,
                    'file_unique_id': file_unique_id,
                    'signal': signal,
                    'updated_at': datetime.now(UTC),
                }
            },
            upsert=True
        )
        return bool(result.matched_count or result.upserted_id)

    async def get_recommendation_feedback(self, user_id: int, limit: int = 100) -> dict[str, list[str]]:
        collection = await self._collection("recommendation_feedback")
        cursor = collection.find({'user_id': user_id}).sort('updated_at', -1).limit(limit)
        documents = await self.db_pool.execute_with_retry(cursor.to_list, length=limit)
        result = {'more': [], 'less': []}
        for document in documents:
            signal = document.get('signal')
            if signal in result:
                result[signal].append(document['file_unique_id'])
        return result

    # File reports
    @staticmethod
    def _reporter_ids(report: dict[str, Any]) -> list[int]:
        """Read reporter IDs from new and legacy report documents."""
        reporter_ids = list(report.get('reporter_ids') or [])
        legacy_user_id = report.get('user_id')
        if legacy_user_id is not None:
            reporter_ids.append(legacy_user_id)

        normalized = []
        for reporter_id in reporter_ids:
            try:
                reporter_id = int(reporter_id)
            except (TypeError, ValueError):
                continue
            if reporter_id not in normalized:
                normalized.append(reporter_id)
        return normalized

    async def _subscribe_to_file_report(
        self,
        collection,
        report: dict[str, Any],
        user_id: int,
        file_name: str | None
    ) -> tuple[dict[str, Any], str] | None:
        reporter_ids = self._reporter_ids(report)
        state = 'duplicate' if user_id in reporter_ids else 'subscribed'
        reporter_ids.append(user_id)
        update = {
            '$addToSet': {'reporter_ids': {'$each': reporter_ids}},
            '$set': {'updated_at': datetime.now(UTC)},
        }
        if file_name:
            update['$set']['file_name'] = file_name
        result = await self.db_pool.execute_with_retry(
            collection.update_one,
            {'_id': report['_id'], 'status': 'open'},
            update
        )
        if not result.matched_count:
            return None
        refreshed = await self.db_pool.execute_with_retry(
            collection.find_one, {'_id': report['_id']}
        )
        return refreshed or report, state

    async def create_file_report(
        self,
        user_id: int,
        file_unique_id: str,
        reason: str,
        file_name: str | None = None
    ) -> tuple[dict[str, Any], str]:
        """Create one open issue per file/reason and subscribe later reporters."""
        collection = await self._collection("file_reports")
        report_id = hashlib.sha256(
            f"{file_unique_id}:{reason}".encode()
        ).hexdigest()[:16]
        for _attempt in range(3):
            existing = await self.db_pool.execute_with_retry(
                collection.find_one,
                {
                    'file_unique_id': file_unique_id,
                    'reason': reason,
                    'status': 'open',
                }
            )
            if existing:
                subscription = await self._subscribe_to_file_report(
                    collection, existing, user_id, file_name
                )
                if subscription:
                    return subscription
                continue

            now = datetime.now(UTC)
            document = {
                '_id': report_id,
                'user_id': user_id,
                'reporter_ids': [user_id],
                'file_unique_id': file_unique_id,
                'file_name': file_name,
                'reason': reason,
                'status': 'open',
                'created_at': now,
                'updated_at': now,
            }
            canonical = await self.db_pool.execute_with_retry(
                collection.find_one, {'_id': report_id}
            )
            if canonical:
                # A previously resolved canonical issue can be reported again.
                reopened_fields = {
                    key: value for key, value in document.items() if key != '_id'
                }
                result = await self.db_pool.execute_with_retry(
                    collection.update_one,
                    {'_id': report_id, 'status': {'$ne': 'open'}},
                    {
                        '$set': reopened_fields,
                        '$unset': {
                            'resolved_by': '',
                            'resolved_at': '',
                            'merged_into': '',
                            'notification_results': '',
                        },
                    }
                )
                if result.modified_count:
                    return document, 'created'
                continue

            try:
                await self.db_pool.execute_with_retry(collection.insert_one, document)
                return document, 'created'
            except DuplicateKeyError:
                # Another reporter created the deterministic issue concurrently.
                continue

        existing = await self.db_pool.execute_with_retry(
            collection.find_one,
            {
                'file_unique_id': file_unique_id,
                'reason': reason,
                'status': 'open',
            }
        )
        if existing:
            subscription = await self._subscribe_to_file_report(
                collection, existing, user_id, file_name
            )
            if subscription:
                return subscription
        raise RuntimeError("Could not create or subscribe to the file report")

    async def list_file_reports(self, status: str = "open", limit: int = 20) -> list[dict[str, Any]]:
        collection = await self._collection("file_reports")
        query = {'status': status} if status != 'all' else {}
        cursor = collection.find(query).sort('created_at', -1).limit(limit)
        reports = await self.db_pool.execute_with_retry(cursor.to_list, length=limit)

        # Coalesce legacy user-scoped open reports in the admin view. Resolution
        # atomically closes every member of the same file/reason issue below.
        coalesced = []
        open_groups = {}
        for report in reports:
            if report.get('status') != 'open':
                coalesced.append(report)
                continue
            key = (report.get('file_unique_id'), report.get('reason'))
            primary = open_groups.get(key)
            if primary is None:
                primary = dict(report)
                primary['reporter_ids'] = self._reporter_ids(report)
                primary['duplicate_report_ids'] = []
                open_groups[key] = primary
                coalesced.append(primary)
                continue
            primary['reporter_ids'] = list(dict.fromkeys(
                self._reporter_ids(primary) + self._reporter_ids(report)
            ))
            primary['duplicate_report_ids'].append(report['_id'])
        return coalesced

    async def resolve_file_report(
        self, report_id: str, admin_id: int
    ) -> dict[str, Any] | None:
        collection = await self._collection("file_reports")
        report = await self.db_pool.execute_with_retry(
            collection.find_one, {'_id': report_id, 'status': 'open'}
        )
        if not report:
            return None

        now = datetime.now(UTC)
        group_cursor = collection.find({
            'file_unique_id': report.get('file_unique_id'),
            'reason': report.get('reason'),
            'status': 'open',
        })
        group_reports = await self.db_pool.execute_with_retry(
            group_cursor.to_list, length=100
        )
        group_reports.sort(key=lambda item: item['_id'] != report_id)

        resolved_report = None
        reporter_ids = []
        for grouped_report in group_reports:
            is_primary = grouped_report['_id'] == report_id
            updated = await self.db_pool.execute_with_retry(
                collection.find_one_and_update,
                {'_id': grouped_report['_id'], 'status': 'open'},
                {
                    '$set': {
                        'status': 'resolved' if is_primary else 'merged',
                        'resolved_by': admin_id,
                        'resolved_at': now,
                        'updated_at': now,
                        **({} if is_primary else {'merged_into': report_id}),
                    }
                },
                return_document=True
            )
            if is_primary and not updated:
                return None
            if not updated:
                continue
            if is_primary:
                resolved_report = updated
            reporter_ids.extend(self._reporter_ids(updated))

        if not resolved_report:
            return None
        reporter_ids = list(dict.fromkeys(reporter_ids))
        return await self.db_pool.execute_with_retry(
            collection.find_one_and_update,
            {'_id': report_id, 'status': 'resolved'},
            {
                '$set': {
                    'reporter_ids': reporter_ids,
                    'updated_at': now,
                },
                '$push': {
                    'resolution_history': {
                        'resolved_by': admin_id,
                        'resolved_at': now,
                        'reporter_ids': reporter_ids,
                    }
                },
            },
            return_document=True
        )

    async def record_report_notification_results(
        self,
        report_id: str,
        notified_user_ids: list[int],
        unreachable_user_ids: list[int],
        failed_user_ids: list[int]
    ) -> None:
        collection = await self._collection("file_reports")
        await self.db_pool.execute_with_retry(
            collection.update_one,
            {'_id': report_id, 'status': 'resolved'},
            {
                '$set': {
                    'notification_results': {
                        'notified_user_ids': notified_user_ids,
                        'unreachable_user_ids': unreachable_user_ids,
                        'failed_user_ids': failed_user_ids,
                        'attempted_at': datetime.now(UTC),
                    },
                    'updated_at': datetime.now(UTC),
                }
            }
        )

    # Persistent request tracking
    async def find_pending_content_request(
        self, user_id: int, query: str
    ) -> dict[str, Any] | None:
        collection = await self._collection("content_requests")
        return await self.db_pool.execute_with_retry(
            collection.find_one,
            {
                'user_id': user_id,
                'normalized_query': normalize_feature_text(query),
                'status': 'pending',
            }
        )

    async def create_content_request(
        self, user_id: int, message_id: int, query: str
    ) -> tuple[dict[str, Any], bool]:
        normalized_query = normalize_feature_text(query)
        collection = await self._collection("content_requests")
        existing = await self.find_pending_content_request(user_id, query)
        if existing:
            return existing, False

        now = datetime.now(UTC)
        document = {
            '_id': f"{user_id}:{message_id}",
            'user_id': user_id,
            'message_id': message_id,
            'query': query.strip()[:100],
            'normalized_query': normalized_query,
            'status': 'pending',
            'created_at': now,
            'updated_at': now,
        }
        try:
            await self.db_pool.execute_with_retry(collection.insert_one, document)
            return document, True
        except DuplicateKeyError:
            existing = await self.db_pool.execute_with_retry(
                collection.find_one,
                {
                    'user_id': user_id,
                    'normalized_query': normalized_query,
                    'status': 'pending',
                }
            )
            return existing, False

    async def update_content_request(
        self, user_id: int, message_id: int, status: str, admin_id: int
    ) -> bool:
        collection = await self._collection("content_requests")
        result = await self.db_pool.execute_with_retry(
            collection.update_one,
            {'_id': f"{user_id}:{message_id}", 'status': 'pending'},
            {
                '$set': {
                    'status': status,
                    'handled_by': admin_id,
                    'updated_at': datetime.now(UTC),
                }
            }
        )
        return bool(result.modified_count)

    async def get_content_request(
        self, user_id: int, message_id: int
    ) -> dict[str, Any] | None:
        collection = await self._collection("content_requests")
        return await self.db_pool.execute_with_retry(
            collection.find_one, {'_id': f"{user_id}:{message_id}"}
        )

    async def claim_content_request_transition(
        self,
        user_id: int,
        message_id: int,
        target_status: str,
        admin_id: int
    ) -> bool:
        """Atomically claim one pending request before sending its notification."""
        collection = await self._collection("content_requests")
        result = await self.db_pool.execute_with_retry(
            collection.update_one,
            {'_id': f"{user_id}:{message_id}", 'status': 'pending'},
            {
                '$set': {
                    'status': f"processing:{target_status}",
                    'target_status': target_status,
                    'handled_by': admin_id,
                    'updated_at': datetime.now(UTC),
                }
            }
        )
        return bool(result.modified_count)

    async def finish_content_request_transition(
        self, user_id: int, message_id: int, target_status: str
    ) -> bool:
        collection = await self._collection("content_requests")
        result = await self.db_pool.execute_with_retry(
            collection.update_one,
            {
                '_id': f"{user_id}:{message_id}",
                'status': f"processing:{target_status}",
            },
            {
                '$set': {
                    'status': target_status,
                    'notification_sent_at': datetime.now(UTC),
                    'updated_at': datetime.now(UTC),
                },
                '$unset': {'target_status': ''},
            }
        )
        return bool(result.modified_count)

    async def rollback_content_request_transition(
        self, user_id: int, message_id: int, target_status: str
    ) -> bool:
        collection = await self._collection("content_requests")
        result = await self.db_pool.execute_with_retry(
            collection.update_one,
            {
                '_id': f"{user_id}:{message_id}",
                'status': f"processing:{target_status}",
            },
            {
                '$set': {'status': 'pending', 'updated_at': datetime.now(UTC)},
                '$unset': {'target_status': '', 'handled_by': ''},
            }
        )
        return bool(result.modified_count)

    async def list_content_requests(self, user_id: int, limit: int = 20) -> list[dict[str, Any]]:
        collection = await self._collection("content_requests")
        cursor = collection.find({'user_id': user_id}).sort('created_at', -1).limit(limit)
        return await self.db_pool.execute_with_retry(cursor.to_list, length=limit)

    # Search/content analytics
    async def track_zero_result(self, user_id: int, query: str) -> None:
        normalized_query = normalize_feature_text(query)
        if not normalized_query:
            return
        collection = await self._collection("search_analytics")
        now = datetime.now(UTC)
        await self.db_pool.execute_with_retry(
            collection.update_one,
            {'_id': normalized_query},
            {
                '$inc': {'count': 1},
                '$set': {'last_searched_at': now},
                '$setOnInsert': {'query': query.strip()[:100], 'created_at': now},
            },
            upsert=True
        )

    async def top_zero_results(self, limit: int = 10) -> list[dict[str, Any]]:
        collection = await self._collection("search_analytics")
        cursor = collection.find({}).sort([('count', -1), ('last_searched_at', -1)]).limit(limit)
        return await self.db_pool.execute_with_retry(cursor.to_list, length=limit)

    async def count_documents(self, collection_name: str, query: dict | None = None) -> int:
        collection = await self._collection(collection_name)
        return int(await self.db_pool.execute_with_retry(
            collection.count_documents, query or {}
        ))
