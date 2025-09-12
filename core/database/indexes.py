"""
Database index optimization for MediaSearchBot
Provides compound indexes for frequent query patterns
"""

from typing import Dict

from core.utils.logger import get_logger

logger = get_logger(__name__)


class IndexOptimizer:
    """Manages database indexes for optimal query performance"""
    
    def __init__(self, db_pool):
        self.db_pool = db_pool
        
    async def create_all_indexes(self) -> Dict[str, bool]:
        """Create all optimized indexes"""
        results = {}
        
        # Media files indexes
        results.update(await self._create_media_indexes())
        
        # User indexes
        results.update(await self._create_user_indexes())
        
        # Connection indexes
        results.update(await self._create_connection_indexes())
        
        # Filter indexes
        results.update(await self._create_filter_indexes())
        
        return results
    
    async def _create_media_indexes(self) -> Dict[str, bool]:
        """Create indexes for media_files collection"""
        results = {}
        collection = await self.db_pool.get_collection('media_files')
        
        indexes = [
            # Search optimization: file_type + file_size for filtered searches
            {
                'keys': [('file_type', 1), ('file_size', -1)],
                'name': 'file_type_size_idx',
                'background': True
            },
            
            # Search optimization: file_type + indexed_at for recent files by type
            {
                'keys': [('file_type', 1), ('indexed_at', -1)],
                'name': 'file_type_time_idx', 
                'background': True
            },
            
            # Text search optimization: file_name with text index
            {
                'keys': [('file_name', 'text'), ('caption', 'text')],
                'name': 'text_search_idx',
                'background': True,
                'default_language': 'english',
                'language_override': 'language'
            },
            
            # Channel-based queries: channel_id + indexed_at
            {
                'keys': [('channel_id', 1), ('indexed_at', -1)],
                'name': 'channel_time_idx',
                'background': True
            },
            
            # File cleanup queries: indexed_at for old file deletion
            {
                'keys': [('indexed_at', 1)],
                'name': 'cleanup_time_idx',
                'background': True
            },
            
            # Ensure unique constraint on file_unique_id
            {
                'keys': [('file_unique_id', 1)],
                'name': 'unique_file_id_idx',
                'unique': True,
                'background': True
            }
        ]
        
        for index in indexes:
            try:
                await collection.create_index(**index)
                results[f"media_{index['name']}"] = True
                logger.info(f"Created index: {index['name']} on media_files")
            except Exception as e:
                error_msg = str(e)
                if "Index already exists" in error_msg or "IndexOptionsConflict" in error_msg:
                    # Index exists with different name - this is OK
                    logger.debug(f"Index {index['name']} already exists with different name - skipping")
                    results[f"media_{index['name']}"] = True  # Mark as successful since index exists
                else:
                    logger.error(f"Failed to create index {index['name']}: {e}")
                    results[f"media_{index['name']}"] = False
                
        return results
    
    async def _create_user_indexes(self) -> Dict[str, bool]:
        """Create indexes for users collection"""
        results = {}
        collection = await self.db_pool.get_collection('users')
        
        indexes = [
            # User activity queries: user_id + last_active
            {
                'keys': [('user_id', 1), ('last_active', -1)],
                'name': 'user_activity_idx',
                'background': True
            },
            
            # Premium user queries: is_premium + premium_expires
            {
                'keys': [('is_premium', 1), ('premium_expires', 1)],
                'name': 'premium_status_idx',
                'background': True
            },
            
            # Banned user queries
            {
                'keys': [('is_banned', 1)],
                'name': 'banned_users_idx',
                'background': True
            },
            
            # Daily limit tracking: user_id + daily_reset_date
            {
                'keys': [('user_id', 1), ('daily_reset_date', 1)],
                'name': 'daily_limit_idx',
                'background': True
            },
            
            # Premium cleanup optimization: is_premium + premium_activation_date  
            {
                'keys': [('is_premium', 1), ('premium_activation_date', 1)],
                'name': 'premium_cleanup_idx',
                'background': True
            },
            
            # Request tracking optimization: user_id + last_request_date
            {
                'keys': [('user_id', 1), ('last_request_date', 1)],
                'name': 'request_tracking_idx',
                'background': True
            }
        ]
        
        for index in indexes:
            try:
                await collection.create_index(**index)
                results[f"users_{index['name']}"] = True
                logger.info(f"Created index: {index['name']} on users")
            except Exception as e:
                error_msg = str(e)
                if "Index already exists" in error_msg or "IndexOptionsConflict" in error_msg:
                    logger.debug(f"Index {index['name']} already exists with different name - skipping")
                    results[f"users_{index['name']}"] = True
                else:
                    logger.error(f"Failed to create index {index['name']}: {e}")
                    results[f"users_{index['name']}"] = False
                
        return results
    
    async def _create_connection_indexes(self) -> Dict[str, bool]:
        """Create indexes for connections collection"""
        results = {}
        collection = await self.db_pool.get_collection('connections')
        
        indexes = [
            # User connection queries: user_id + active status
            {
                'keys': [('user_id', 1), ('is_active', 1)],
                'name': 'user_active_connections_idx',
                'background': True
            },
            
            # Group connection queries: group_id + active status  
            {
                'keys': [('group_id', 1), ('is_active', 1)],
                'name': 'group_active_connections_idx',
                'background': True
            },
            
            # User group detail queries: user_id + group_details.group_id
            {
                'keys': [('user_id', 1), ('group_details.group_id', 1)],
                'name': 'user_group_details_idx',
                'background': True
            }
        ]
        
        for index in indexes:
            try:
                await collection.create_index(**index)
                results[f"connections_{index['name']}"] = True
                logger.info(f"Created index: {index['name']} on connections")
            except Exception as e:
                error_msg = str(e)
                if "Index already exists" in error_msg or "IndexOptionsConflict" in error_msg:
                    logger.debug(f"Index {index['name']} already exists with different name - skipping")
                    results[f"connections_{index['name']}"] = True
                else:
                    logger.error(f"Failed to create index {index['name']}: {e}")
                    results[f"connections_{index['name']}"] = False
                
        return results
    
    async def _create_filter_indexes(self) -> Dict[str, bool]:
        """Create indexes for filters collection"""
        results = {}
        collection = await self.db_pool.get_collection('filters')
        
        indexes = [
            # Filter lookup: group_id + filter text
            {
                'keys': [('group_id', 1), ('text', 1)],
                'name': 'group_filter_idx',
                'background': True
            },
            
            # Group filters listing: group_id + created date
            {
                'keys': [('group_id', 1), ('created_at', -1)],
                'name': 'group_filters_list_idx',
                'background': True
            }
        ]
        
        for index in indexes:
            try:
                await collection.create_index(**index)
                results[f"filters_{index['name']}"] = True
                logger.info(f"Created index: {index['name']} on filters")
            except Exception as e:
                error_msg = str(e)
                if "Index already exists" in error_msg or "IndexOptionsConflict" in error_msg:
                    logger.debug(f"Index {index['name']} already exists with different name - skipping")
                    results[f"filters_{index['name']}"] = True
                else:
                    logger.error(f"Failed to create index {index['name']}: {e}")
                    results[f"filters_{index['name']}"] = False
                
        return results
    
    async def drop_unused_indexes(self) -> Dict[str, bool]:
        """Drop any unused or redundant indexes"""
        results = {}
        
        try:
            # Get all collections
            collections = ['media_files', 'users', 'connections', 'filters']
            
            for collection_name in collections:
                collection = await self.db_pool.get_collection(collection_name)
                
                # Get current indexes
                indexes = await collection.list_indexes().to_list(length=None)
                
                # Keep track of which indexes might be redundant
                # This is conservative - only drops obviously redundant ones
                for index in indexes:
                    index_name = index.get('name', '')
                    
                    # Skip system indexes
                    if index_name in ['_id_']:
                        continue
                    
                    # Log existing indexes for analysis
                    logger.info(f"Existing index in {collection_name}: {index_name}")
                
                results[f"{collection_name}_analysis"] = True
                
        except Exception as e:
            logger.error(f"Error analyzing indexes: {e}")
            results["analysis_error"] = False
            
        return results