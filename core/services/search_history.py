# core/services/search_history.py
"""Service for managing user search history and most searched keywords"""

from typing import List, Tuple, Optional
from core.cache.config import CacheKeyGenerator, CacheTTLConfig
from core.cache.redis_cache import CacheManager
from core.utils.logger import get_logger

logger = get_logger(__name__)


class SearchHistoryService:
    """Service for tracking and retrieving user search history"""

    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager
        self.ttl = CacheTTLConfig()
        self.max_keywords = 8  # Maximum keywords to show in keyboard

    async def track_search(self, user_id: int, query: str, track_global: bool = True) -> None:
        """
        Track a search query for a user and optionally globally
        
        Args:
            user_id: User ID
            query: Search query string (will be normalized)
            track_global: Whether to also track in global search history (default: True)
        """
        if not query or len(query.strip()) < 2:
            return
        
        # Normalize query (lowercase, strip)
        normalized_query = query.lower().strip()
        
        # Skip if query is too long (Telegram keyboard button limit)
        if len(normalized_query) > 64:
            return
        
        try:
            # Track user-specific search
            user_cache_key = CacheKeyGenerator.user_search_history(user_id)
            await self.cache.zincrby(user_cache_key, 1.0, normalized_query)
            await self.cache.expire(user_cache_key, self.ttl.USER_SEARCH_HISTORY)
            
            # Track global search if enabled
            if track_global:
                global_cache_key = CacheKeyGenerator.global_search_history()
                await self.cache.zincrby(global_cache_key, 1.0, normalized_query)
                await self.cache.expire(global_cache_key, self.ttl.GLOBAL_SEARCH_HISTORY)
            
        except Exception as e:
            logger.error(f"Error tracking search for user {user_id}, query {query}: {e}")

    async def get_most_searched_keywords(self, user_id: int, limit: int = None) -> List[str]:
        """
        Get most searched keywords for a user
        
        Args:
            user_id: User ID
            limit: Maximum number of keywords to return (default: max_keywords)
            
        Returns:
            List of keyword strings, sorted by search count (descending)
        """
        if limit is None:
            limit = self.max_keywords
        
        try:
            cache_key = CacheKeyGenerator.user_search_history(user_id)
            
            # Get top keywords (with scores)
            results = await self.cache.zrevrange(cache_key, 0, limit - 1, with_scores=False)
            
            # Convert bytes to strings if needed
            keywords = []
            for result in results:
                if isinstance(result, bytes):
                    keywords.append(result.decode('utf-8'))
                else:
                    keywords.append(str(result))
            
            return keywords
            
        except Exception as e:
            logger.error(f"Error getting search history for user {user_id}: {e}")
            return []

    async def get_global_top_searches(self, limit: int = 10) -> List[str]:
        """
        Get top global searches across all users
        
        Args:
            limit: Maximum number of keywords to return (default: 10)
            
        Returns:
            List of keyword strings, sorted by search count (descending)
        """
        try:
            global_cache_key = CacheKeyGenerator.global_search_history()
            
            # Get top keywords
            results = await self.cache.zrevrange(global_cache_key, 0, limit - 1, with_scores=False)
            
            # Convert bytes to strings if needed
            keywords = []
            for result in results:
                if isinstance(result, bytes):
                    keywords.append(result.decode('utf-8'))
                else:
                    keywords.append(str(result))
            
            return keywords
            
        except Exception as e:
            logger.error(f"Error getting global top searches: {e}")
            return []

    async def clear_search_history(self, user_id: int) -> bool:
        """
        Clear search history for a user
        
        Args:
            user_id: User ID
            
        Returns:
            True if successful, False otherwise
        """
        try:
            cache_key = CacheKeyGenerator.user_search_history(user_id)
            return await self.cache.delete(cache_key)
        except Exception as e:
            logger.error(f"Error clearing search history for user {user_id}: {e}")
            return False

    async def find_similar_queries(
        self, 
        query: str, 
        user_id: Optional[int] = None,
        threshold: float = 0.6,
        max_results: int = 3
    ) -> List[str]:
        """
        Find similar queries using fuzzy matching from user and global search history
        
        Args:
            query: The query to find similar matches for
            user_id: Optional user ID to also search user's search history
            threshold: Minimum similarity score (0.0 to 1.0) to include a result
            max_results: Maximum number of results to return
            
        Returns:
            List of similar query strings, sorted by similarity (descending)
        """
        if not query or len(query.strip()) < 2:
            return []
        
        try:
            from core.utils.helpers import find_similar_queries
            
            candidate_queries = []
            
            # Get user's search history if user_id provided
            if user_id:
                user_keywords = await self.get_most_searched_keywords(user_id, limit=50)
                candidate_queries.extend(user_keywords)
            
            # Get global top searches
            global_keywords = await self.get_global_top_searches(limit=50)
            candidate_queries.extend(global_keywords)
            
            # Remove duplicates while preserving order
            seen = set()
            unique_candidates = []
            for q in candidate_queries:
                if q not in seen:
                    seen.add(q)
                    unique_candidates.append(q)
            
            # Find similar queries
            similar = find_similar_queries(
                query, 
                unique_candidates, 
                threshold=threshold,
                max_results=max_results
            )
            
            # Return just the query strings (without scores)
            return [q for q, _ in similar]
            
        except Exception as e:
            logger.error(f"Error finding similar queries for {query}: {e}")
            return []
