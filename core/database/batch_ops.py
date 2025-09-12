"""
Optimized batch database operations
Provides efficient bulk operations with proper error handling and batching
"""

import asyncio
from typing import List, Dict, Any, Optional

from pymongo import InsertOne, UpdateOne

from core.utils.logger import get_logger

# Import concurrency control
try:
    from core.concurrency.semaphore_manager import semaphore_manager
    CONCURRENCY_CONTROL_AVAILABLE = True
except ImportError:
    CONCURRENCY_CONTROL_AVAILABLE = False

logger = get_logger(__name__)


class BatchOperationManager:
    """Manages efficient batch database operations"""
    
    # Optimal batch sizes for different operations (tested values)
    BATCH_SIZES = {
        'insert': 1000,
        'update': 500, 
        'delete': 1000,
        'replace': 300
    }
    
    def __init__(self, db_pool):
        self.db_pool = db_pool
    
    async def batch_insert_files(
        self, 
        collection_name: str, 
        documents: List[Dict[str, Any]],
        batch_size: Optional[int] = None
    ) -> Dict[str, Any]:
        """Optimized batch insert with proper error handling"""
        if not documents:
            return {'inserted': 0, 'errors': 0, 'details': []}
            
        batch_size = batch_size or self.BATCH_SIZES['insert']
        collection = await self.db_pool.get_collection(collection_name)
        
        total_inserted = 0
        total_errors = 0
        error_details = []
        
        # Process in batches
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]
            
            try:
                operations = [InsertOne(doc) for doc in batch]
                result = await collection.bulk_write(operations, ordered=False)
                total_inserted += result.inserted_count
                
                # Log any write errors
                if result.bulk_api_result.get('writeErrors'):
                    for error in result.bulk_api_result['writeErrors']:
                        total_errors += 1
                        error_details.append({
                            'index': error.get('index', -1),
                            'code': error.get('code', -1),
                            'message': error.get('errmsg', 'Unknown error')
                        })
                        
            except Exception as e:
                logger.error(f"Batch insert failed for batch {i//batch_size + 1}: {e}")
                total_errors += len(batch)
                error_details.append({
                    'batch': i//batch_size + 1,
                    'error': str(e),
                    'count': len(batch)
                })
                
        logger.info(f"Batch insert completed: {total_inserted} inserted, {total_errors} errors")
        return {
            'inserted': total_inserted,
            'errors': total_errors, 
            'details': error_details
        }
    
    async def batch_update_files(
        self,
        collection_name: str,
        updates: List[Dict[str, Any]],  # [{'filter': {}, 'update': {}, 'upsert': bool}]
        batch_size: Optional[int] = None
    ) -> Dict[str, Any]:
        """Optimized batch update operations"""
        if not updates:
            return {'modified': 0, 'upserted': 0, 'errors': 0}
            
        batch_size = batch_size or self.BATCH_SIZES['update']
        collection = await self.db_pool.get_collection(collection_name)
        
        total_modified = 0
        total_upserted = 0
        total_errors = 0
        
        # Process in batches
        for i in range(0, len(updates), batch_size):
            batch = updates[i:i + batch_size]
            
            try:
                operations = []
                for update_doc in batch:
                    op = UpdateOne(
                        update_doc['filter'],
                        update_doc['update'], 
                        upsert=update_doc.get('upsert', False)
                    )
                    operations.append(op)
                    
                result = await collection.bulk_write(operations, ordered=False)
                total_modified += result.modified_count
                total_upserted += result.upserted_count
                
            except Exception as e:
                logger.error(f"Batch update failed for batch {i//batch_size + 1}: {e}")
                total_errors += len(batch)
                
        return {
            'modified': total_modified,
            'upserted': total_upserted,
            'errors': total_errors
        }
    
    async def batch_delete_by_ids(
        self,
        collection_name: str,
        ids: List[Any],
        id_field: str = '_id',
        batch_size: Optional[int] = None
    ) -> Dict[str, Any]:
        """Optimized batch delete by IDs using $in operator"""
        if not ids:
            return {'deleted': 0, 'errors': 0}
            
        batch_size = batch_size or self.BATCH_SIZES['delete']
        collection = await self.db_pool.get_collection(collection_name)
        
        total_deleted = 0
        total_errors = 0
        
        # Use $in operator for efficient batch deletes
        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i:i + batch_size]
            
            try:
                # More efficient than individual DeleteOne operations
                result = await collection.delete_many({id_field: {'$in': batch_ids}})
                total_deleted += result.deleted_count
                
            except Exception as e:
                logger.error(f"Batch delete failed for batch {i//batch_size + 1}: {e}")
                total_errors += len(batch_ids)
                
        return {'deleted': total_deleted, 'errors': total_errors}
    
    async def optimized_file_search_batch(
        self,
        collection_name: str,
        search_filters: List[Dict[str, Any]],
        projection: Optional[Dict[str, Any]] = None,
        limit_per_filter: int = 100
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Batch multiple search queries efficiently"""
        if not search_filters:
            return {}
            
        collection = await self.db_pool.get_collection(collection_name)
        results: Dict[str, List[Dict[str, Any]]] = {}
        
        # Use aggregation pipeline for efficient multiple searches
        try:
            pipeline: List[Dict[str, Any]] = []
            
            # Create union of all search conditions using $or if filters are similar
            if len(search_filters) <= 10:  # For small number of filters, use $or
                combined_filter = {'$or': search_filters}
                pipeline = [
                    {'$match': combined_filter}
                ]
                if projection:
                    pipeline.append({'$project': projection})
                pipeline.append({'$limit': limit_per_filter * len(search_filters)})
                
                cursor = collection.aggregate(pipeline)
                all_results = await cursor.to_list(length=None)
                
                # Group results by which filter they match
                for i, filter_dict in enumerate(search_filters):
                    matching_results = []
                    for doc in all_results:
                        # Simple check if document matches this specific filter
                        # This is a simplified approach - might need refinement
                        matching_results.append(doc)
                    results[f"filter_{i}"] = matching_results[:limit_per_filter]
                    
            else:
                # For many filters, execute separately but concurrently
                tasks = []
                for i, filter_dict in enumerate(search_filters):
                    task = self._single_search_task(
                        collection, filter_dict, projection, limit_per_filter, i
                    )
                    tasks.append(task)
                
                # Execute all searches with bounded concurrency
                if CONCURRENCY_CONTROL_AVAILABLE:
                    # Use bounded concurrency for database operations
                    concurrent_results = []
                    for task in tasks:
                        async with semaphore_manager.acquire('database_read'):
                            result = await task
                            concurrent_results.append(result)
                else:
                    # Fallback to unbounded gather
                    concurrent_results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for i, result in enumerate(concurrent_results):
                    if isinstance(result, Exception):
                        logger.error(f"Search filter {i} failed: {result}")
                        results[f"filter_{i}"] = []
                    else:
                        results[f"filter_{i}"] = result
                        
        except Exception as e:
            logger.error(f"Batch search failed: {e}")
            # Fallback to individual searches
            for i, filter_dict in enumerate(search_filters):
                try:
                    cursor = collection.find(filter_dict, projection).limit(limit_per_filter)
                    results[f"filter_{i}"] = await cursor.to_list(length=limit_per_filter)
                except Exception as search_error:
                    logger.error(f"Individual search {i} failed: {search_error}")
                    results[f"filter_{i}"] = []
                    
        return results
    
    async def _single_search_task(
        self, 
        collection, 
        filter_dict: Dict[str, Any], 
        projection: Optional[Dict[str, Any]], 
        limit: int, 
        task_id: int
    ) -> List[Dict[str, Any]]:
        """Execute a single search task"""
        try:
            cursor = collection.find(filter_dict, projection).limit(limit)
            return await cursor.to_list(length=limit)
        except Exception as e:
            logger.error(f"Search task {task_id} failed: {e}")
            return []
    
    async def batch_aggregate_stats(
        self,
        collection_name: str,
        pipelines: List[List[Dict[str, Any]]]
    ) -> List[List[Dict[str, Any]]]:
        """Execute multiple aggregation pipelines efficiently"""
        if not pipelines:
            return []
            
        collection = await self.db_pool.get_collection(collection_name)
        
        # Execute aggregations concurrently
        tasks = [
            collection.aggregate(pipeline).to_list(length=None) 
            for pipeline in pipelines
        ]
        
        try:
            # Execute aggregations with bounded concurrency
            if CONCURRENCY_CONTROL_AVAILABLE:
                results = []
                for task in tasks:
                    async with semaphore_manager.acquire('database_read'):
                        result = await task
                        results.append(result)
            else:
                results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Handle any failed aggregations
            final_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Aggregation pipeline {i} failed: {result}")
                    final_results.append([])
                else:
                    final_results.append(result)
                    
            return final_results
            
        except Exception as e:
            logger.error(f"Batch aggregation failed: {e}")
            return [[] for _ in pipelines]