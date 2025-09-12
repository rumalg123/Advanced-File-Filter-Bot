from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple

from pymongo import DeleteOne
from pymongo.errors import DuplicateKeyError

from core.cache.config import CacheTTLConfig, CacheKeyGenerator
from core.cache.invalidation import CacheInvalidator
from core.database.base import BaseRepository, AggregationMixin
from core.utils.helpers import normalize_query
from core.utils.logger import get_logger

logger = get_logger(__name__)

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

    def __post_init__(self):
        if self.indexed_at is None:
            self.indexed_at = datetime.now(UTC)
        if self.updated_at is None:
            self.updated_at = datetime.now(UTC)


class MediaRepository(BaseRepository[MediaFile], AggregationMixin):
    """Repository for media file operations with multi-database support"""

    def __init__(self, db_pool, cache_manager, multi_db_manager=None):
        super().__init__(db_pool, cache_manager, "media_files")
        self.ttl = CacheTTLConfig()
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
        data['indexed_at'] = data['indexed_at'].isoformat()
        if data.get('updated_at'):
            data['updated_at'] = data['updated_at'].isoformat()
        return data

    def _dict_to_entity(self, data: Dict[str, Any]) -> MediaFile:
        """Convert dictionary to MediaFile entity"""
        if isinstance(data, MediaFile):
            return data  # Already the correct type
        data['file_id'] = data.pop('_id')
        data['file_type'] = FileType(data['file_type'])
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
        if cached:
            return self._dict_to_entity(cached)

        if self.is_multi_db:
            # Search across all databases
            data, db_index = await self.multi_db_manager.find_file_in_all_databases(
                self.collection_name, 
                {"file_unique_id": identifier}
            )
            if data:
                file = self._dict_to_entity(data)
                await self.cache.set(cache_key, file, expire=self.ttl.MEDIA_FILE)
                return file
        else:
            # Single database mode
            collection = await self.collection
            data = await self.db_pool.execute_with_retry(
                collection.find_one, {"file_unique_id": identifier}
            )
            if data:
                file = self._dict_to_entity(data)
                await self.cache.set(cache_key, file, expire=self.ttl.MEDIA_FILE)
                return file

        return None
    async def delete(self, id: Any) -> bool:
        """Delete entity"""
        try:
            collection = await self.collection

            result = await self.db_pool.execute_with_retry(
                collection.delete_one, {"file_unique_id": id}
            )
            if result.deleted_count > 0:
                # Clear all possible cache entries
                cache_key = self._get_cache_key(id)
                await self.cache.delete(cache_key)
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
                    # Cache the new file
                    cache_key = self._get_cache_key(media.file_unique_id)
                    await self.cache.set(cache_key, media, expire=self.ttl.MEDIA_FILE)
                    # Invalidate search caches
                    await self.cache_invalidator.invalidate_all_search_results()
                    return True, 1, None
                else:
                    return False, 2, None
            else:
                # Single database mode - use existing create method
                success = await self.create(media)
                if success:
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
        
        # Use batch optimization if available, fallback to individual checks
        if self.batch_ops:
            try:
                return await self.batch_ops.batch_duplicate_check(media_files)
            except Exception as e:
                logger.warning(f"Batch duplicate check failed, falling back: {e}")
        
        # Fallback to individual duplicate checks
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
            use_caption: bool = True
    ) -> Tuple[List[MediaFile], int, int]:
        """
        Search for files across all databases
        Returns: (files, next_offset, total_count)
        """
        # Generate cache key
        normalized_query = normalize_query(query)
        cache_key = CacheKeyGenerator.search_results(
            query,
            file_type.value if file_type else None,
            offset,
            limit,
            use_caption
        )
        cached = await self.cache.get(cache_key)
        if cached:
            return (
                [self._dict_to_entity(f) for f in cached['files']],
                cached['next_offset'],
                cached['total']
            )

        # Build search filter
        search_filter = self._build_search_filter(normalized_query, file_type, use_caption)

        if self.is_multi_db:
            # Multi-database search
            total = await self.multi_db_manager.count_across_all_databases(
                self.collection_name, search_filter
            )
            
            # Get files from all databases
            files_data = await self.multi_db_manager.search_across_all_databases(
                self.collection_name,
                search_filter,
                limit=limit,
                skip=offset,
                sort=[('indexed_at', -1)]
            )
            files = [self._dict_to_entity(f) for f in files_data]
        else:
            # Single database search
            total = await self.count(search_filter)
            files = await self.find_many(
                search_filter,
                limit=limit,
                skip=offset,
                sort=[('indexed_at', -1)]
            )

        # Calculate next offset
        next_offset = offset + limit if offset + limit < total else 0

        # Cache results
        cache_data = {
            'files': [self._entity_to_dict(f) for f in files],
            'next_offset': next_offset,
            'total': total
        }
        await self.cache.set(cache_key, cache_data, expire=self.ttl.SEARCH_RESULTS)
        return files, next_offset, total

    def _build_search_filter(
            self,
            query: str,
            file_type: Optional[FileType],
            use_caption: bool
    ) -> Dict[str, Any]:
        """Build MongoDB search filter"""
        # Build regex pattern
        if not query:
            pattern = '.'
        elif ' ' not in query:
            pattern = rf'(\b|[\.\+\-_]){query}(\b|[\.\+\-_])'
        else:
            pattern = query.replace(' ', r'.*[\s\.\+\-_]')

        regex = {'$regex': pattern, '$options': 'i'}

        # Build filter
        search_filter = {}

        if use_caption:
            search_filter['$or'] = [
                {'file_name': regex},
                {'caption': regex}
            ]
        else:
            search_filter['file_name'] = regex

        if file_type:
            search_filter['file_type'] = file_type.value

        return search_filter

    async def update(self, id: Any, update_data: Dict[str, Any], upsert: bool = False) -> bool:
        """Update entity and invalidate cache properly"""
        success = await super().update(id, update_data, upsert)

        if success:
            # Get the file to invalidate all its cache entries
            file = await self.find_file(id)
            if file:
                await self.cache_invalidator.invalidate_file_cache(file)

        return success

    async def delete_files_by_keyword(self, keyword: str) -> int:
        """Delete all files matching keyword"""
        search_filter = self._build_search_filter(keyword, None, True)

        # Get files to delete
        files = await self.find_many(search_filter)

        if not files:
            return 0

        # Build bulk delete operations
        operations = [DeleteOne({'file_unique_id': f.file_unique_id}) for f in files]

        # Execute bulk delete
        success = await self.bulk_write(operations)

        # Clear cache for deleted files
        for file in files:
            await self.cache_invalidator.invalidate_file_cache(file)

        return len(files) if success else 0

    async def get_file_stats(self) -> Dict[str, Any]:
        """Get file statistics"""
        cache_key = CacheKeyGenerator.file_stats()
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
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

        results = await self.aggregate(pipeline, limit=None)  # Stats need unlimited results
        if results:
            facets = results[0]
            stats = {
                'total_files': facets['total'][0]['count'] if facets['total'] else 0,
                'total_size': facets['total_size'][0]['size'] if facets['total_size'] else 0,
                'by_type': {}
            }

            for type_stat in facets.get('by_type', []):
                stats['by_type'][type_stat['_id']] = {
                    'count': type_stat['count'],
                    'size': type_stat['size']
                }
            await self.cache.set(cache_key, stats, expire=self.ttl.FILE_STATS)
            return stats

        return {
            'total_files': 0,
            'total_size': 0,
            'by_type': {}
        }


    async def create_indexes(self) -> None:
        """Create necessary indexes for optimal performance"""
        indexes = [
            ([('file_name', 'text'), ('caption', 'text')], {'name': 'text_search'}),
            ([('file_name', 1), ('caption', 1)], {'name': 'text_name_unique', 'unique': True}),
            ([('file_type', 1), ('indexed_at', -1)], {'name': 'type_date'}),
            ([('file_size', 1)], {'name': 'size_index'}),
            ([('indexed_at', -1)], {'name': 'date_index'}),
            ([('file_ref', 1)], {'name': 'file_ref_index', 'unique': True, 'sparse': True}),
            ([('file_type', 1), ('file_name', 1)], {'name': 'type_name_index'}),
            ([('file_unique_id', 1)], {'name': 'unique_id_index', 'unique': True})
        ]

        for keys, kwargs in indexes:
            try:
                await self.create_index(keys, **kwargs)
            except Exception as e:
                logger.warning(f"Error creating index {kwargs.get('name', '')}: {e}")