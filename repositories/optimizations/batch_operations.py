"""
Optimized batch operations to eliminate N+1 queries
Using MongoDB aggregation pipelines for efficient joins and lookups
"""

import asyncio
from typing import List, Dict, Any, Tuple, Optional, TYPE_CHECKING
from datetime import datetime, UTC, date, timedelta

from pymongo import UpdateOne, InsertOne
from pymongo.errors import BulkWriteError

from core.utils.logger import get_logger

# Use TYPE_CHECKING to avoid circular imports
if TYPE_CHECKING:
    from repositories.media import MediaFile
    from repositories.user import User

logger = get_logger(__name__)


class BatchOptimizations:
    """Optimized batch operations using aggregation pipelines"""
    
    def __init__(self, db_pool, cache_manager):
        self.db_pool = db_pool
        self.cache = cache_manager
    
    async def batch_premium_status_check(
        self, 
        user_ids: List[int]
    ) -> Dict[int, Tuple[bool, Optional[str]]]:
        """
        Batch premium status check using aggregation pipeline
        Eliminates N+1 queries by checking all users in single operation
        """
        if not user_ids:
            return {}
        
        collection = await self.db_pool.get_collection('users')
        
        # Use aggregation pipeline for efficient batch processing
        pipeline = [
            {"$match": {"_id": {"$in": user_ids}}},
            {"$project": {
                "_id": 1,
                "is_premium": 1,
                "premium_activation_date": 1,
                "computed_status": {
                    "$cond": {
                        "if": {"$eq": ["$is_premium", True]},
                        "then": {
                            "is_active": {
                                "$cond": {
                                    "if": {"$ne": ["$premium_activation_date", None]},
                                    "then": {
                                        "$gt": [
                                            {"$add": ["$premium_activation_date", {"$multiply": [30, 24, 60, 60, 1000]}]},  # 30 days in ms
                                            {"$toDate": "$$NOW"}
                                        ]
                                    },
                                    "else": False
                                }
                            },
                            "days_remaining": {
                                "$cond": {
                                    "if": {"$ne": ["$premium_activation_date", None]},
                                    "then": {
                                        "$divide": [
                                            {"$subtract": [
                                                {"$add": ["$premium_activation_date", {"$multiply": [30, 24, 60, 60, 1000]}]},
                                                {"$toDate": "$$NOW"}
                                            ]},
                                            {"$multiply": [24, 60, 60, 1000]}  # Convert ms to days
                                        ]
                                    },
                                    "else": 0
                                }
                            }
                        },
                        "else": {"is_active": False, "days_remaining": 0}
                    }
                }
            }}
        ]
        
        try:
            cursor = collection.aggregate(pipeline)
            results = await cursor.to_list(length=None)
            
            status_map = {}
            expired_users = []
            
            for result in results:
                user_id = result["_id"]
                computed = result["computed_status"]
                
                if result["is_premium"]:
                    if computed["is_active"]:
                        days_remaining = max(0, int(computed["days_remaining"]))
                        status_map[user_id] = (True, f"Premium active ({days_remaining} days remaining)")
                    else:
                        # Mark for batch expiration update
                        expired_users.append(user_id)
                        status_map[user_id] = (False, "Premium subscription expired")
                else:
                    status_map[user_id] = (False, None)
            
            # Batch update expired users
            if expired_users:
                await self._batch_expire_premium_users(expired_users)
            
            # Fill in missing users (not found in DB)
            for user_id in user_ids:
                if user_id not in status_map:
                    status_map[user_id] = (False, None)
            
            return status_map
            
        except Exception as e:
            logger.error(f"Batch premium status check failed: {e}")
            # Fallback to individual checks
            return {user_id: (False, None) for user_id in user_ids}
    
    async def batch_duplicate_check(
        self, 
        media_files: List['MediaFile']
    ) -> Dict[str, Optional['MediaFile']]:
        """
        Batch duplicate check using aggregation pipeline with $lookup
        Eliminates N+1 duplicate checking queries
        """
        if not media_files:
            return {}
        
        unique_ids = [media.file_unique_id for media in media_files]
        collection = await self.db_pool.get_collection('media_files')
        
        # Use aggregation with optimized projection
        pipeline = [
            {"$match": {"file_unique_id": {"$in": unique_ids}}},
            {"$project": {
                "file_unique_id": 1,
                "file_id": 1,
                "file_name": 1,
                "file_size": 1,
                "file_type": 1,
                "created_at": 1
            }}
        ]
        
        try:
            cursor = collection.aggregate(pipeline)
            results = await cursor.to_list(length=None)
            
            # Build lookup map
            existing_map = {}
            for result in results:
                unique_id = result["file_unique_id"]
                # Convert back to MediaFile object (dynamic import to avoid circular dependency)
                from repositories.media import MediaFile
                existing_file = MediaFile(
                    file_id=result["file_id"],
                    file_unique_id=result["file_unique_id"],
                    file_ref="",  # Not needed for duplicate check
                    file_name=result["file_name"],
                    file_size=result["file_size"],
                    file_type=result["file_type"]
                )
                existing_map[unique_id] = existing_file
            
            # Fill in None for non-duplicates
            for media in media_files:
                if media.file_unique_id not in existing_map:
                    existing_map[media.file_unique_id] = None
            
            logger.info(f"Batch duplicate check completed: {len(results)} duplicates found out of {len(media_files)} files")
            return existing_map
            
        except Exception as e:
            logger.error(f"Batch duplicate check failed: {e}")
            return {media.file_unique_id: None for media in media_files}
    
    async def batch_user_activity_aggregation(
        self, 
        user_ids: List[int], 
        days_back: int = 30
    ) -> Dict[int, Dict[str, Any]]:
        """
        Batch user activity aggregation using pipeline joins
        Combines user data with activity metrics in single operation
        """
        if not user_ids:
            return {}
        
        collection = await self.db_pool.get_collection('users')
        
        # Complex aggregation pipeline with lookups
        pipeline = [
            {"$match": {"_id": {"$in": user_ids}}},
            {"$lookup": {
                "from": "media_files",
                "let": {"user_id": "$_id"},
                "pipeline": [
                    {"$match": {
                        "$expr": {
                            "$and": [
                                {"$eq": ["$user_id", "$$user_id"]},
                                {"$gte": ["$created_at", {"$dateSubtract": {
                                    "startDate": "$$NOW",
                                    "unit": "day",
                                    "amount": days_back
                                }}]}
                            ]
                        }
                    }},
                    {"$group": {
                        "_id": None,
                        "files_shared": {"$sum": 1},
                        "total_size": {"$sum": "$file_size"}
                    }}
                ],
                "as": "activity_data"
            }},
            {"$project": {
                "_id": 1,
                "username": 1,
                "is_premium": 1,
                "created_at": 1,
                "daily_retrieval_count": 1,
                "last_retrieval_date": 1,
                "activity": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$activity_data", 0]},
                        {"files_shared": 0, "total_size": 0}
                    ]
                }
            }}
        ]
        
        try:
            cursor = collection.aggregate(pipeline)
            results = await cursor.to_list(length=None)
            
            activity_map = {}
            for result in results:
                user_id = result["_id"]
                activity_map[user_id] = {
                    "username": result.get("username", "Unknown"),
                    "is_premium": result.get("is_premium", False),
                    "created_at": result.get("created_at"),
                    "daily_retrieval_count": result.get("daily_retrieval_count", 0),
                    "last_retrieval_date": result.get("last_retrieval_date"),
                    "files_shared": result["activity"]["files_shared"],
                    "total_size_shared": result["activity"]["total_size"]
                }
            
            logger.info(f"Batch user activity aggregation completed for {len(results)} users")
            return activity_map
            
        except Exception as e:
            logger.error(f"Batch user activity aggregation failed: {e}")
            return {}
    
    async def _batch_expire_premium_users(self, user_ids: List[int]) -> bool:
        """Batch update expired premium users"""
        if not user_ids:
            return True
        
        collection = await self.db_pool.get_collection('users')
        
        try:
            operations = [
                UpdateOne(
                    {"_id": user_id},
                    {"$set": {
                        "is_premium": False,
                        "premium_activation_date": None,
                        "updated_at": datetime.now(UTC)
                    }}
                ) for user_id in user_ids
            ]
            
            result = await collection.bulk_write(operations, ordered=False)
            logger.info(f"Batch expired {result.modified_count} premium users")
            return result.modified_count > 0
            
        except BulkWriteError as e:
            logger.error(f"Batch premium expiration failed: {e.details}")
            return False
        except Exception as e:
            logger.error(f"Batch premium expiration error: {e}")
            return False


# Enhanced indexes for optimal performance
OPTIMIZED_INDEXES = {
    'users': [
        # Compound index for premium status checks
        ('is_premium', 'premium_activation_date', '_id'),
        # Index for user activity lookups
        ('_id', 'created_at', 'last_retrieval_date'),
    ],
    'media_files': [
        # Compound index for duplicate checks and user lookups
        ('file_unique_id', 'file_id', 'user_id'),
        # Index for user activity aggregations
        ('user_id', 'created_at', 'file_size'),
        # Index for file type statistics
        ('file_type', 'created_at', 'file_size'),
    ]
}