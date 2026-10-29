from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from enum import Enum
import json
import re
import time
from typing import Dict, Any, Optional, List, Tuple

from pymongo.errors import DuplicateKeyError

from core.cache.config import CacheTTLConfig, CacheKeyGenerator
from core.cache.invalidation import CacheInvalidator
from core.database.base import BaseRepository, AggregationMixin
from core.database.errors import SearchBackendUnavailableError
from core.services.bulk_media_deletion import MediaBulkDeletion
from core.utils.validators import normalize_query
from core.utils.search_matcher import build_media_search_filter
from core.utils.search_observability import search_telemetry
from core.utils.media_metadata import effective_quality
from core.utils.logger import get_logger

logger = get_logger(__name__)

# PH-014: unique _id makes equal-timestamp offset pages deterministic.
# Do not change the multi-database merge path before PH-025..PH-028.
SINGLE_DB_SEARCH_SORT = [("indexed_at", -1), ("_id", -1)]

class SearchGenerationChanged(RuntimeError):
    """A concurrent media mutation invalidated this search attempt."""



# Import batch optimizations
try:
    from .optimizations.batch_operations import BatchOptimizations
    BATCH_OPTIMIZATIONS_AVAILABLE = True
except ImportError:
    BATCH_OPTIMIZATIONS_AVAILABLE = False
    logger.warning("Batch optimizations not available for media repository")


class FileType(Enum):
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    PHOTO = "photo"
    ANIMATION = "animation"
    APPLICATION = "application"


@dataclass
class MediaFile:
    """Media file entity"""
    file_unique_id: str
    file_id: str
    file_ref: Optional[str]
    file_name: str
    file_size: int
    file_type: FileType
    mime_type: Optional[str]
    caption: Optional[str]
    indexed_at: datetime = None
    updated_at: Optional[datetime] = None
    resolution: Optional[str] = None
    episode: Optional[str] = None
    season: Optional[str] = None
    # PH-015 additive fields. Legacy media_files documents need not have them.
    width: Optional[int] = None
    height: Optional[int] = None
    quality: Optional[str] = None

    @property
    def display_quality(self) -> Optional[str]:
        """Read old and new quality labels without writing inferred values."""
        return effective_quality(self.quality, self.resolution, self.file_name, self.caption)

    def __post_init__(self):
        if self.indexed_at is None:
            self.indexed_at = datetime.now(UTC)
        if self.updated_at is None:
            self.updated_at = datetime.now(UTC)


class MediaRepository(BaseRepository[MediaFile], AggregationMixin):
    """Repository for media file operations with multi-database support"""

    def __init__(
            self,
            db_pool,
            cache_manager,
            multi_db_manager=None,
            search_cache_ttl: Optional[int] = None
    ):
        super().__init__(db_pool, cache_manager, "media_files")
        self.ttl = CacheTTLConfig()
        if search_cache_ttl is not None:
            try:
                configured_ttl = int(search_cache_ttl)
                if configured_ttl <= 0:
                    raise ValueError("CACHE_TIME must be positive")
                self.ttl.SEARCH_RESULTS = configured_ttl
            except (TypeError, ValueError):
                logger.warning(
                    f"Invalid CACHE_TIME {search_cache_ttl!r}; using "
                    f"{self.ttl.SEARCH_RESULTS}s"
                )
        self.cache_invalidator = CacheInvalidator(cache_manager)
        self.multi_db_manager = multi_db_manager
        self.is_multi_db = multi_db_manager is not None
        
        # Initialize batch optimizations
        if BATCH_OPTIMIZATIONS_AVAILABLE:
            self.batch_ops = BatchOptimizations(db_pool, cache_manager)
        else:
            self.batch_ops = None

    def _entity_to_dict(self, media: MediaFile) -> Dict[str, Any]:
        """Convert MediaFile entity to dictionary"""
        data = asdict(media)
        data['_id'] = data.pop('file_id')
        data['file_type'] = media.file_type.value
        # Optional canonical fields are absent, not null, on media without
        # authoritative metadata. Avoid inflating existing document formats.
        for field in ('width', 'height', 'quality'):
            if data[field] is None:
                del data[field]
        data['indexed_at'] = data['indexed_at'].isoformat()
        if data.get('updated_at'):
            data['updated_at'] = data['updated_at'].isoformat()
        return data

    def _dict_to_entity(self, data: Dict[str, Any]) -> MediaFile:
        """Convert dictionary to MediaFile entity"""
        if isinstance(data, MediaFile):
            return data  # Already the correct type

        # Handle _id to file_id conversion safely
        if '_id' in data:
            data['file_id'] = data.pop('_id')
        elif 'file_id' not in data:
            raise KeyError("Missing required field: '_id' or 'file_id'")

        # Convert file_type safely
        from core.utils.file_type import get_file_type_from_value
        file_type_value = data.get('file_type')
        if isinstance(file_type_value, str):
            # Use utility for consistent conversion
            converted_type = get_file_type_from_value(file_type_value)
            data['file_type'] = converted_type if converted_type else FileType.DOCUMENT
        elif isinstance(file_type_value, FileType):
            pass  # Already correct type
        else:
            data['file_type'] = FileType.DOCUMENT  # Default fallback
        if data.get('indexed_at'):
            if isinstance(data['indexed_at'], str):
                data['indexed_at'] = datetime.fromisoformat(data['indexed_at'])
        if data.get('updated_at'):
            if isinstance(data['updated_at'], str):
                data['updated_at'] = datetime.fromisoformat(data['updated_at'])
        return MediaFile(**data)

    def _get_cache_key(self, identifier: str) -> str:
        """Use centralized key generator"""
        return CacheKeyGenerator.media(identifier)


    async def find_file(self, identifier: str) -> Optional[MediaFile]:
        """Find file by identifier, supporting multi-database mode"""
        # Try cache first
        cache_key = CacheKeyGenerator.media(identifier)
        cached = await self.cache.get(cache_key)
        if cached is not None:
            try:
                return self._dict_to_entity(cached)
            except (KeyError, TypeError, ValueError) as e:
                # Cache data is corrupt, delete and fall through to DB lookup
                logger.warning(f"Corrupt cache data for {identifier}, clearing: {e}")
                await self.cache_invalidator.invalidate_media_entry(identifier)

        lookup_filter = {
            "$or": [
                {"file_unique_id": identifier},
                {"file_ref": identifier},
                {"_id": identifier}
            ]
        }

        if self.is_multi_db:
            # Search across all databases
            data, db_index = await self.multi_db_manager.find_file_in_all_databases(
                self.collection_name,
                lookup_filter
            )
            if data:
                file = self._dict_to_entity(data)
                # Cache as dict for proper serialization
                await self.cache.set(cache_key, self._entity_to_dict(file), expire=self.ttl.MEDIA_FILE)
                return file
        else:
            # Single database mode
            collection = await self.collection()
            data = await self.db_pool.execute_with_retry(
                collection.find_one, lookup_filter
            )
            if data:
                file = self._dict_to_entity(data)
                # Cache as dict for proper serialization
                await self.cache.set(cache_key, self._entity_to_dict(file), expire=self.ttl.MEDIA_FILE)
                return file

        return None

    async def find_files_batch(
        self,
        file_unique_ids: List[str]
    ) -> Dict[str, Optional[MediaFile]]:
        """
        Find multiple files by their unique IDs in a single batch operation.
        Uses $in operator for efficient batch lookup instead of N individual queries.

        Args:
            file_unique_ids: List of file_unique_id values to look up

        Returns:
            Dictionary mapping file_unique_id to MediaFile (or None if not found)
        """
        if not file_unique_ids:
            return {}

        result: Dict[str, Optional[MediaFile]] = {uid: None for uid in file_unique_ids}

        # First, check cache for all files
        cache_hits = []
        cache_misses = []

        for uid in file_unique_ids:
            cache_key = CacheKeyGenerator.media(uid)
            cached = await self.cache.get(cache_key)
            if cached is not None:
                try:
                    result[uid] = self._dict_to_entity(cached)
                    cache_hits.append(uid)
                except (KeyError, TypeError, ValueError) as e:
                    logger.warning(f"Corrupt cache data for {uid}, clearing: {e}")
                    await self.cache_invalidator.invalidate_media_entry(uid)
                    cache_misses.append(uid)
            else:
                cache_misses.append(uid)

        if not cache_misses:
            # All found in cache
            return result

        # Batch fetch from database for cache misses
        try:
            if self.is_multi_db:
                # Search across all databases using $in
                for db_pool in await self.multi_db_manager.get_all_databases():
                    if not cache_misses:
                        break
                    collection = await db_pool.get_collection(self.collection_name)
                    docs = await db_pool.execute_with_retry(
                        collection.find({"file_unique_id": {"$in": cache_misses}}).to_list,
                        length=len(cache_misses)
                    )
                    for data in docs:
                        try:
                            file = self._dict_to_entity(data)
                            uid = file.file_unique_id
                            result[uid] = file
                            # Cache the found file
                            cache_key = CacheKeyGenerator.media(uid)
                            await self.cache.set(
                                cache_key,
                                self._entity_to_dict(file),
                                expire=self.ttl.MEDIA_FILE
                            )
                            # Remove from cache_misses
                            if uid in cache_misses:
                                cache_misses.remove(uid)
                        except Exception as e:
                            logger.warning(f"Error processing batch result: {e}")
            else:
                # Single database mode
                collection = await self.collection()
                docs = await self.db_pool.execute_with_retry(
                    collection.find({"file_unique_id": {"$in": cache_misses}}).to_list,
                    length=len(cache_misses)
                )
                for data in docs:
                    try:
                        file = self._dict_to_entity(data)
                        uid = file.file_unique_id
                        result[uid] = file
                        # Cache the found file
                        cache_key = CacheKeyGenerator.media(uid)
                        await self.cache.set(
                            cache_key,
                            self._entity_to_dict(file),
                            expire=self.ttl.MEDIA_FILE
                        )
                    except Exception as e:
                        logger.warning(f"Error processing batch result: {e}")

            logger.debug(
                f"Batch file lookup: {len(cache_hits)} cache hits, "
                f"{len(file_unique_ids) - len(cache_hits) - len(cache_misses)} DB hits, "
                f"{len(cache_misses)} not found"
            )

        except Exception as e:
            logger.error(f"Error in batch file lookup: {e}")

        return result

    async def delete(self, id: Any) -> bool:
        """Delete entity and invalidate all related caches"""
        try:
            # Find file first to get all identifiers for cache invalidation
            file = await self.find_file(id)
            if not file:
                return False

            if self.is_multi_db:
                deleted_count = await self.multi_db_manager.delete_one_across_databases(
                    self.collection_name,
                    {"file_unique_id": file.file_unique_id}
                )
            else:
                collection = await self.collection()

                result = await self.db_pool.execute_with_retry(
                    collection.delete_one, {"file_unique_id": file.file_unique_id}
                )
                deleted_count = result.deleted_count

            if deleted_count > 0:
                # Invalidate all file-related caches
                await self.cache_invalidator.invalidate_file_cache(file)
                await self.cache_invalidator.invalidate_all_search_results()
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting entity {id}: {e}")
            return False

    async def save_media(self, media: MediaFile) -> Tuple[bool, int, Optional[MediaFile]]:
        """
        Save media file with comprehensive duplicate handling across all databases
        Returns: (success, status_code, existing_file)
        status_code: 1=saved, 0=duplicate, 2=error
        existing_file: The existing file if it's a duplicate
        """
        try:
            # Check for duplicate by file_unique_id across all databases
            existing = await self.find_file(media.file_unique_id)
            if existing:
                logger.debug(f"Duplicate file found: {media.file_name}")
                return False, 0, existing

            if self.is_multi_db:
                # Use smart database selection for optimal write performance
                write_db_pool = await self.multi_db_manager.get_optimal_write_database()
                collection = await write_db_pool.get_collection(self.collection_name)
                
                # Save to write database
                document = self._entity_to_dict(media)
                result = await write_db_pool.execute_with_retry(
                    collection.insert_one, document
                )
                if result.inserted_id:
                    logger.info(f"Saved file to database: {media.file_name}")
                    await self.cache_invalidator.invalidate_all_search_results()
                    await self.cache_invalidator.invalidate_file_stats()
                    # Cache the new file as dict for proper serialization
                    cache_key = self._get_cache_key(media.file_unique_id)
                    await self.cache.set(cache_key, self._entity_to_dict(media), expire=self.ttl.MEDIA_FILE)
                    return True, 1, None
                else:
                    return False, 2, None
            else:
                # Single database mode - use existing create method
                success = await self.create(media)
                if success:
                    await self.cache_invalidator.invalidate_all_search_results()
                    await self.cache_invalidator.invalidate_file_stats()
                    cache_key = self._get_cache_key(media.file_unique_id)
                    await self.cache.set(
                        cache_key,
                        self._entity_to_dict(media),
                        expire=self.ttl.MEDIA_FILE
                    )
                    logger.info(f"Saved file: {media.file_name}")
                    return True, 1, None
                else:
                    return False, 2, None
                    
        except DuplicateKeyError as e:
            logger.warning(f"Duplicate key error for file: {media.file_name}")
            existing = await self.find_file(media.file_unique_id)
            return False, 0, existing
        except Exception as e:
            logger.error(f"Error saving media: {e}")
            return False, 2, None

    async def batch_check_duplicates(
        self,
        media_files: List[MediaFile]
    ) -> Dict[str, Optional[MediaFile]]:
        """
        Batch duplicate check to eliminate N+1 queries during bulk operations
        Uses optimized aggregation pipeline for bulk duplicate detection
        """
        if not media_files:
            return {}

        if self.is_multi_db:
            unique_ids = [media.file_unique_id for media in media_files]
            existing_docs = await self.multi_db_manager.find_many_in_all_databases(
                self.collection_name,
                {"file_unique_id": {"$in": unique_ids}},
                projection={
                    "file_unique_id": 1,
                    "_id": 1,
                    "file_name": 1,
                    "file_size": 1,
                    "file_type": 1,
                    "file_ref": 1,
                    "mime_type": 1,
                    "caption": 1,
                    "indexed_at": 1,
                    "updated_at": 1,
                    "resolution": 1,
                    "episode": 1,
                    "season": 1,
                }
            )
            existing_by_unique_id = {doc["file_unique_id"]: doc for doc in existing_docs}

            return {
                media.file_unique_id: (
                    self._dict_to_entity(existing_by_unique_id[media.file_unique_id])
                    if media.file_unique_id in existing_by_unique_id
                    else None
                )
                for media in media_files
            }

        # Use batch optimization if available
        if self.batch_ops:
            try:
                return await self.batch_ops.batch_duplicate_check(media_files)
            except Exception as e:
                logger.warning(f"Batch duplicate check failed, falling back: {e}")

        # Inline fallback using batch $in query instead of N+1 individual queries
        try:
            unique_ids = [media.file_unique_id for media in media_files]
            collection = await self.get_collection()

            # Single batch query using $in operator
            existing_docs = await self.db_pool.execute_with_retry(
                collection.find(
                    {"file_unique_id": {"$in": unique_ids}},
                    {"file_unique_id": 1, "_id": 1, "file_name": 1, "file_size": 1,
                     "file_type": 1, "file_ref": 1, "mime_type": 1, "caption": 1,
                     "indexed_at": 1, "updated_at": 1}
                ).to_list,
                length=len(unique_ids)
            )

            # Build result map from batch query results
            result = {}
            existing_by_unique_id = {doc["file_unique_id"]: doc for doc in existing_docs}

            for media in media_files:
                if media.file_unique_id in existing_by_unique_id:
                    result[media.file_unique_id] = self._dict_to_entity(
                        existing_by_unique_id[media.file_unique_id]
                    )
                else:
                    result[media.file_unique_id] = None

            return result

        except Exception as e:
            logger.error(f"Inline batch duplicate check also failed: {e}")
            # Final fallback to individual queries (worst case)
            result = {}
            for media in media_files:
                existing = await self.find_file(media.file_unique_id)
                result[media.file_unique_id] = existing
            return result

    async def search_files(
            self,
            query: str,
            file_type: Optional[FileType] = None,
            offset: int = 0,
            limit: int = 10,
            use_caption: bool = True,
            advanced_filters: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[MediaFile], int, int]:
        """Bounded retry if a concurrent write changes search generation.

        Each search attempt takes a fresh generation, including after a
        cache hit. Never return a known-stale cached/DB result. Continuous
        writes cause a retryable error instead of unbounded spinning.
        """
        for attempt in range(3):
            try:
                return await self._search_files_once(
                    query, file_type, offset, limit, use_caption,
                    advanced_filters
                )
            except SearchGenerationChanged:
                logger.debug(
                    "Search generation changed during attempt %s/3", attempt + 1
                )
        raise SearchBackendUnavailableError(
            "Search index changed repeatedly while reading; please retry"
        )

    async def _read_search_generation(self) -> int:
        try:
            return await self.cache_invalidator.get_search_cache_version()
        except (RuntimeError, ValueError, TypeError) as exc:
            raise SearchBackendUnavailableError(
                "Search cache generation unavailable"
            ) from exc

    async def _search_files_once(
            self,
            query: str,
            file_type: Optional[FileType] = None,
            offset: int = 0,
            limit: int = 10,
            use_caption: bool = True,
            advanced_filters: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[MediaFile], int, int]:
        """
        Search for files across all databases
        Returns: (files, next_offset, total_count)
        """
        # PH-006: instrument stage latency, never raw user queries.
        search_started = time.perf_counter()
        # PH-003: if protected Redis state is unavailable we cannot trust
        # cached pages, because the generation may have been reset.
        try:
            cache_version = await self.cache_invalidator.get_search_cache_version()
        except RuntimeError as exc:
            search_telemetry.observe(
                "generation_error", (time.perf_counter() - search_started) * 1000
            )
            raise SearchBackendUnavailableError(
                "Protected search cache generation unavailable"
            ) from exc

        # Generate versioned cache key
        normalized_query = normalize_query(query)
        # Cache the same normalized text that reaches the MongoDB matcher.
        # Explicit filters remain part of the key to prevent cross-filter hits.
        cache_query = normalized_query
        if advanced_filters:
            cache_query = (
                f"{normalized_query}|advanced:"
                f"{json.dumps(advanced_filters, sort_keys=True, separators=(',', ':'))}"
            )
        # PH-003: a split-state cutover must not accidentally reuse an older
        # ":v1" search page produced with the legacy counter on cache Redis.
        # A new cache namespace avoids mixing pre-PH-014 pages with pages
        # ordered by the unique _id tie-breaker after a rolling deployment.
        if not self.is_multi_db:
            cache_query += "|sort:indexed-at-id-desc-v1"
        if getattr(self.cache, "protected_state_enabled", False):
            cache_query += "|state:split-v1"
        cache_key = CacheKeyGenerator.search_results_versioned(
            cache_query,
            file_type.value if file_type else None,
            offset,
            limit,
            use_caption,
            cache_version
        )

        cached = await self.cache.get(cache_key)
        if cached is not None:
            try:
                result = (
                    [self._dict_to_entity(f) for f in cached['files']],
                    cached['next_offset'],
                    cached['total']
                )
                # A mutation may occur while fetching the cached page.
                # Recheck on both single and split Redis deployments.
                current_version = await self._read_search_generation()
                if current_version != cache_version:
                    raise SearchGenerationChanged()
                elapsed_ms = (time.perf_counter() - search_started) * 1000
                search_telemetry.observe("cache_hit", elapsed_ms)
                search_telemetry.observe("search", elapsed_ms)
                return result
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"Invalid search cache entry {cache_key}: {e}")
                await self.cache.delete(cache_key)

        # Cache misses are counted separately from completed MongoDB reads.
        search_telemetry.observe("cache_miss", (time.perf_counter() - search_started) * 1000)

        # Build search filter
        search_filter = self._build_search_filter(
            normalized_query, file_type, use_caption, advanced_filters
        )

        # PH-002: a MongoDB failure is NOT a successful zero-result search.
        # Only completed queries can populate Redis or drive zero-result
        # analytics. Existing optional multi-DB partial-result semantics are
        # separately tracked as PH-027 and must be fixed before enabling it.
        try:
            if self.is_multi_db:
                count_started = time.perf_counter()
                total = await self.multi_db_manager.count_across_all_databases(
                    self.collection_name, search_filter
                )
                search_telemetry.observe("count", (time.perf_counter() - count_started) * 1000)
                page_started = time.perf_counter()
                files_data = await self.multi_db_manager.search_across_all_databases(
                    self.collection_name,
                    search_filter,
                    limit=limit,
                    skip=offset,
                    sort=[('indexed_at', -1)]
                )
                files = [self._dict_to_entity(f) for f in files_data]
                search_telemetry.observe("page", (time.perf_counter() - page_started) * 1000)
            else:
                count_started = time.perf_counter()
                total = await self.count(search_filter, raise_on_error=True)
                search_telemetry.observe("count", (time.perf_counter() - count_started) * 1000)
                page_started = time.perf_counter()
                files = await self.find_many(
                    search_filter,
                    limit=limit,
                    skip=offset,
                    sort=SINGLE_DB_SEARCH_SORT,
                    raise_on_error=True
                )
                search_telemetry.observe("page", (time.perf_counter() - page_started) * 1000)
        except Exception as exc:
            search_telemetry.observe(
                "backend_error", (time.perf_counter() - search_started) * 1000
            )
            logger.error("Media search failed before cache storage: %s", exc, exc_info=True)
            raise SearchBackendUnavailableError(
                "Unable to complete the MongoDB media search"
            ) from exc

        # DB count/page reads span multiple awaits. When indexing,
        # deletion or import changes the generation mid-read, discard this
        # attempt instead of showing/cache-writing a known-stale page.
        if await self._read_search_generation() != cache_version:
            raise SearchGenerationChanged()

        # Calculate next offset
        next_offset = offset + limit if offset + limit < total else 0

        # Cache results
        cache_data = {
            'files': [self._entity_to_dict(f) for f in files],
            'next_offset': next_offset,
            'total': total
        }
        # Negative cache entries are more sensitive to out-of-band MongoDB
        # imports, so give genuine zero-match queries a shorter expiration.
        # Repository writes still invalidate all versions immediately.
        ttl = (
            min(self.ttl.SEARCH_RESULTS, self.ttl.SEARCH_EMPTY_RESULTS)
            if total == 0 else self.ttl.SEARCH_RESULTS
        )
        await self.cache.set(cache_key, cache_data, expire=ttl)
        # Even if an invalidation races the cache SET, the stale entry stays
        # under its old generation. Retry rather than serve the old result.
        if await self._read_search_generation() != cache_version:
            raise SearchGenerationChanged()
        search_telemetry.observe("search", (time.perf_counter() - search_started) * 1000)
        return files, next_offset, total

    async def has_matching_file(
            self,
            query: str,
            file_type: Optional[FileType] = None,
            use_caption: bool = True,
            advanced_filters: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Check current MongoDB search truth without counting every match."""
        search_filter = self._build_search_filter(
            normalize_query(query), file_type, use_caption, advanced_filters
        )

        if self.is_multi_db:
            matches = await self.multi_db_manager.search_across_all_databases(
                self.collection_name,
                search_filter,
                limit=1,
                skip=0,
                sort=[('_id', 1)]
            )
            return bool(matches)

        collection = await self.collection()
        match = await self.db_pool.execute_with_retry(
            collection.find_one, search_filter, {'_id': 1}
        )
        return match is not None

    def _build_search_filter(
            self,
            query: str,
            file_type: Optional[FileType],
            use_caption: bool,
            advanced_filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Build a backward-compatible MongoDB search predicate."""
        return build_media_search_filter(query, file_type, use_caption, advanced_filters)

    async def update(self, id: Any, update_data: Dict[str, Any], upsert: bool = False) -> bool:
        """Update entity and invalidate cache properly"""
        old_file = await self.find_file(id)
        if self.is_multi_db:
            success = await self.multi_db_manager.update_one_across_databases(
                self.collection_name,
                {"_id": id},
                {"$set": update_data},
                upsert=upsert
            )
            if success:
                if old_file:
                    await self.cache_invalidator.invalidate_file_cache(old_file)
                else:
                    await self.cache_invalidator.invalidate_media_entry(id)
                await self.cache_invalidator.invalidate_file_stats()
                await self.cache_invalidator.invalidate_all_search_results()
            return success

        success = await super().update(id, update_data, upsert)

        if success:
            if old_file:
                await self.cache_invalidator.invalidate_file_cache(old_file)
            new_file = await self.find_file(id)
            if new_file:
                await self.cache_invalidator.invalidate_file_cache(new_file)
            await self.cache_invalidator.invalidate_file_stats()
            await self.cache_invalidator.invalidate_all_search_results()

        return success

    async def preview_delete_files_by_keyword(self, keyword: str):
        """Strict read-only preview for an administrator-confirmed deletion."""
        return await MediaBulkDeletion(self).preview(keyword)

    async def delete_files_by_keyword(
        self, keyword: str, *, expected_count=None, stop_requested=None
    ) -> int:
        """Delete in bounded batches only after the preview is confirmed."""
        return await MediaBulkDeletion(self).execute(
            keyword, expected_count=expected_count, stop_requested=stop_requested
        )

    async def get_file_stats(self) -> Dict[str, Any]:
        """Get file statistics"""
        cache_key = CacheKeyGenerator.file_stats()
        cached = await self.cache.get(cache_key)
        if isinstance(cached, dict):
            return cached
        if cached is not None:
            await self.cache_invalidator.invalidate_file_stats()
        pipeline = [
            {"$facet": {
                "total": [{"$count": "count"}],
                "by_type": [
                    {"$group": {
                        "_id": "$file_type",
                        "count": {"$sum": 1},
                        "size": {"$sum": "$file_size"}
                    }}
                ],
                "total_size": [
                    {"$group": {
                        "_id": None,
                        "size": {"$sum": "$file_size"}
                    }}
                ]
            }}
        ]

        if self.is_multi_db:
            results = await self.multi_db_manager.aggregate_across_all_databases(
                self.collection_name,
                pipeline,
                limit=None
            )
        else:
            results = await self.aggregate(pipeline, limit=None)  # Stats need unlimited results

        if results:
            stats = {
                'total_files': 0,
                'total_size': 0,
                'by_type': {}
            }

            for facets in results:
                stats['total_files'] += facets['total'][0]['count'] if facets['total'] else 0
                stats['total_size'] += facets['total_size'][0]['size'] if facets['total_size'] else 0

                for type_stat in facets.get('by_type', []):
                    file_type = type_stat['_id']
                    current = stats['by_type'].setdefault(file_type, {'count': 0, 'size': 0})
                    current['count'] += type_stat['count']
                    current['size'] += type_stat['size']

            await self.cache.set(cache_key, stats, expire=self.ttl.FILE_STATS)
            return stats

        return {
            'total_files': 0,
            'total_size': 0,
            'by_type': {}
        }


    async def create_indexes(self) -> None:
        """Create necessary indexes for optimal performance"""
        # Names must match indexes.py to avoid IndexOptionsConflict errors
        indexes = [
            ([('file_name', 'text'), ('caption', 'text')], {'name': 'text_search_idx', 'default_language': 'english'}),
            ([('file_type', 1), ('indexed_at', -1)], {'name': 'file_type_time_idx'}),
            ([('file_size', 1)], {'name': 'size_index'}),
            ([('indexed_at', -1)], {'name': 'date_index'}),
            ([('file_ref', 1)], {'name': 'file_ref_index', 'unique': True, 'sparse': True}),
            ([('file_type', 1), ('file_name', 1)], {'name': 'type_name_index'}),
            ([('file_unique_id', 1)], {'name': 'unique_file_id_idx', 'unique': True}),
            # New indexes for season/episode/resolution fields
            ([('season', 1), ('episode', 1)], {'name': 'season_episode_idx', 'sparse': True}),
            ([('season', 1), ('episode', 1), ('resolution', 1)], {'name': 'season_episode_resolution_idx', 'sparse': True}),
            ([('resolution', 1)], {'name': 'resolution_idx', 'sparse': True}),
            ([('resolution', 1), ('file_type', 1)], {'name': 'resolution_type_idx', 'sparse': True}),
            ([('episode', 1)], {'name': 'episode_idx', 'sparse': True}),
        ]

        for keys, kwargs in indexes:
            try:
                await self.create_index(keys, **kwargs)
            except Exception as e:
                error_str = str(e)
                # Index conflicts are expected if indexes.py already created them
                if "IndexOptionsConflict" in error_str or "Index already exists" in error_str:
                    logger.debug(f"Index {kwargs.get('name', '')} already exists")
                else:
                    logger.warning(f"Error creating index {kwargs.get('name', '')}: {e}")
