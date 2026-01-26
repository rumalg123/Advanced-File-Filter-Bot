# core/services/recommendation.py
"""Service for generating smart recommendations based on user behavior and file metadata"""

from typing import List, Optional, Dict, Any, Tuple
from core.cache.config import CacheKeyGenerator, CacheTTLConfig
from core.cache.redis_cache import CacheManager
from core.utils.logger import get_logger
from repositories.media import MediaFile

logger = get_logger(__name__)


class RecommendationService:
    """Service for generating smart recommendations"""

    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager
        self.ttl = CacheTTLConfig()

    async def track_file_click(
        self, 
        user_id: int, 
        query: str, 
        file_unique_id: str
    ) -> None:
        """
        Track when a user clicks/downloads a file from search results
        
        Args:
            user_id: User ID
            query: Search query that led to this file
            file_unique_id: Unique ID of the file clicked
        """
        if not query or not file_unique_id:
            return
        
        try:
            normalized_query = query.lower().strip()
            
            # Track query-to-files mapping (which files are clicked from which queries)
            query_files_key = CacheKeyGenerator.query_files_mapping(normalized_query)
            await self.cache.zincrby(query_files_key, 1.0, file_unique_id)
            await self.cache.expire(query_files_key, self.ttl.QUERY_FILES_MAPPING)
            
            # Track user file interactions
            user_interactions_key = CacheKeyGenerator.user_file_interactions(user_id)
            await self.cache.zincrby(user_interactions_key, 1.0, file_unique_id)
            await self.cache.expire(user_interactions_key, self.ttl.USER_SEARCH_HISTORY)
            
            # Track file co-occurrence (files clicked together)
            # This will be updated when we track multiple files from same query
            # For now, we'll track it when we have query context
            
        except Exception as e:
            logger.error(f"Error tracking file click for user {user_id}, query {query}, file {file_unique_id}: {e}")

    async def track_search_sequence(
        self, 
        user_id: int, 
        previous_query: Optional[str], 
        current_query: str
    ) -> None:
        """
        Track search sequences to understand user search patterns
        
        Args:
            user_id: User ID
            previous_query: Previous search query (if any)
            current_query: Current search query
        """
        if not current_query:
            return
        
        try:
            normalized_current = current_query.lower().strip()
            
            # Track user search pattern
            if previous_query:
                normalized_prev = previous_query.lower().strip()
                pattern_key = CacheKeyGenerator.user_search_pattern(user_id)
                pattern = f"{normalized_prev}->{normalized_current}"
                await self.cache.zincrby(pattern_key, 1.0, pattern)
                await self.cache.expire(pattern_key, self.ttl.USER_SEARCH_HISTORY)
                
                # Track query co-occurrence (queries searched together)
                cooccur_key = CacheKeyGenerator.query_cooccurrence(normalized_prev)
                await self.cache.zincrby(cooccur_key, 1.0, normalized_current)
                await self.cache.expire(cooccur_key, self.ttl.QUERY_COOCCURRENCE)
                
                # Also track reverse (bidirectional)
                cooccur_reverse_key = CacheKeyGenerator.query_cooccurrence(normalized_current)
                await self.cache.zincrby(cooccur_reverse_key, 1.0, normalized_prev)
                await self.cache.expire(cooccur_reverse_key, self.ttl.QUERY_COOCCURRENCE)
            
        except Exception as e:
            logger.error(f"Error tracking search sequence for user {user_id}: {e}")

    async def track_files_from_query(
        self, 
        query: str, 
        file_unique_ids: List[str]
    ) -> None:
        """
        Track which files were shown for a query (for co-occurrence)
        
        Args:
            query: Search query
            file_unique_ids: List of file unique IDs shown in results
        """
        if not query or not file_unique_ids:
            return
        
        try:
            normalized_query = query.lower().strip()
            
            # Track files shown together (co-occurrence)
            for i, file_id1 in enumerate(file_unique_ids):
                for file_id2 in file_unique_ids[i+1:]:
                    # Track bidirectional co-occurrence
                    cooccur_key1 = CacheKeyGenerator.file_cooccurrence(file_id1)
                    await self.cache.zincrby(cooccur_key1, 0.1, file_id2)  # Lower weight for just being shown
                    await self.cache.expire(cooccur_key1, self.ttl.FILE_COOCCURRENCE)
                    
                    cooccur_key2 = CacheKeyGenerator.file_cooccurrence(file_id2)
                    await self.cache.zincrby(cooccur_key2, 0.1, file_id1)
                    await self.cache.expire(cooccur_key2, self.ttl.FILE_COOCCURRENCE)
            
        except Exception as e:
            logger.error(f"Error tracking files from query {query}: {e}")

    async def get_similar_queries(self, query: str, limit: int = 5) -> List[str]:
        """
        Get queries similar to the current one based on co-occurrence
        
        Args:
            query: Current search query
            limit: Maximum number of similar queries to return
            
        Returns:
            List of similar query strings
        """
        if not query:
            return []
        
        try:
            normalized_query = query.lower().strip()
            cooccur_key = CacheKeyGenerator.query_cooccurrence(normalized_query)
            
            # Get top co-occurring queries
            results = await self.cache.zrevrange(cooccur_key, 0, limit - 1, with_scores=False)
            
            # Convert bytes to strings if needed
            similar_queries = []
            for result in results:
                if isinstance(result, bytes):
                    similar_queries.append(result.decode('utf-8'))
                else:
                    similar_queries.append(str(result))
            
            return similar_queries
            
        except Exception as e:
            logger.error(f"Error getting similar queries for {query}: {e}")
            return []

    async def get_recommended_files_from_query(
        self, 
        query: str, 
        limit: int = 5
    ) -> List[str]:
        """
        Get recommended file IDs based on query (files clicked from similar queries)
        
        Args:
            query: Search query
            limit: Maximum number of files to return
            
        Returns:
            List of file_unique_ids
        """
        if not query:
            return []
        
        try:
            normalized_query = query.lower().strip()
            
            # Get files clicked from this exact query
            query_files_key = CacheKeyGenerator.query_files_mapping(normalized_query)
            files = await self.cache.zrevrange(query_files_key, 0, limit - 1, with_scores=False)
            
            # Get files from similar queries
            similar_queries = await self.get_similar_queries(query, limit=3)
            for similar_query in similar_queries:
                if len(files) >= limit:
                    break
                similar_key = CacheKeyGenerator.query_files_mapping(similar_query)
                similar_files = await self.cache.zrevrange(similar_key, 0, limit - 1, with_scores=False)
                for file_id in similar_files:
                    if file_id not in files:
                        files.append(file_id)
                    if len(files) >= limit:
                        break
            
            # Convert bytes to strings if needed
            file_ids = []
            for result in files[:limit]:
                if isinstance(result, bytes):
                    file_ids.append(result.decode('utf-8'))
                else:
                    file_ids.append(str(result))
            
            return file_ids
            
        except Exception as e:
            logger.error(f"Error getting recommended files from query {query}: {e}")
            return []

    async def get_recommendations_for_user(
        self, 
        user_id: int, 
        limit: int = 10
    ) -> Dict[str, Any]:
        """
        Get personalized recommendations for a user
        
        Args:
            user_id: User ID
            limit: Maximum number of recommendations
            
        Returns:
            Dictionary with recommendation data:
            {
                'similar_queries': [...],
                'trending_files': [...],
                'based_on_history': [...]
            }
        """
        try:
            # Check cache first
            cache_key = CacheKeyGenerator.user_recommendations_cache(user_id)
            cached = await self.cache.get(cache_key)
            if cached:
                return cached
            
            recommendations = {
                'similar_queries': [],
                'trending_files': [],
                'based_on_history': []
            }
            
            # Get user's recent searches
            if hasattr(self, 'search_history_service') and self.search_history_service:
                user_keywords = await self.search_history_service.get_most_searched_keywords(user_id, limit=3)
                
                # Get similar queries based on user's top searches
                for keyword in user_keywords:
                    similar = await self.get_similar_queries(keyword, limit=2)
                    recommendations['similar_queries'].extend(similar)
                
                # Get files based on user's search history
                for keyword in user_keywords[:2]:
                    files = await self.get_recommended_files_from_query(keyword, limit=3)
                    recommendations['based_on_history'].extend(files)
                
                # Get trending files (from global top searches)
                global_keywords = await self.search_history_service.get_global_top_searches(limit=3)
                for keyword in global_keywords:
                    files = await self.get_recommended_files_from_query(keyword, limit=2)
                    recommendations['trending_files'].extend(files)
            
            # Remove duplicates and limit
            recommendations['similar_queries'] = list(dict.fromkeys(recommendations['similar_queries']))[:limit]
            recommendations['trending_files'] = list(dict.fromkeys(recommendations['trending_files']))[:limit]
            recommendations['based_on_history'] = list(dict.fromkeys(recommendations['based_on_history']))[:limit]
            
            # Cache recommendations
            await self.cache.set(cache_key, recommendations, expire=self.ttl.USER_RECOMMENDATIONS)
            
            return recommendations
            
        except Exception as e:
            logger.error(f"Error getting recommendations for user {user_id}: {e}")
            return {
                'similar_queries': [],
                'trending_files': [],
                'based_on_history': []
            }

    async def get_content_based_recommendations(
        self, 
        file: MediaFile, 
        limit: int = 5
    ) -> List[str]:
        """
        Get recommendations based on file metadata (content-based filtering)
        
        Args:
            file: MediaFile to find similar files for
            limit: Maximum number of recommendations
            
        Returns:
            List of file_unique_ids
        """
        if not file:
            return []
        
        try:
            # Get files that co-occur with this file
            cooccur_key = CacheKeyGenerator.file_cooccurrence(file.file_unique_id)
            results = await self.cache.zrevrange(cooccur_key, 0, limit - 1, with_scores=False)
            
            # Convert bytes to strings if needed
            file_ids = []
            for result in results:
                if isinstance(result, bytes):
                    file_ids.append(result.decode('utf-8'))
                else:
                    file_ids.append(str(result))
            
            return file_ids
            
        except Exception as e:
            logger.error(f"Error getting content-based recommendations for file {file.file_unique_id}: {e}")
            return []
