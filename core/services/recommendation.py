# core/services/recommendation.py
"""Service for generating smart recommendations based on user behavior and file metadata"""

from typing import List, Optional, Dict, Any
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

    @staticmethod
    def _as_text(value) -> str:
        return value.decode('utf-8') if isinstance(value, bytes) else str(value)

    async def invalidate_user_recommendations(self, user_id: int) -> None:
        """Force the next recommendation read to recompute the user's ranking."""
        try:
            await self.cache.delete(CacheKeyGenerator.user_recommendations_cache(user_id))
        except Exception as e:
            logger.debug(f"Error invalidating recommendations for user {user_id}: {e}")

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
        if not file_unique_id:
            return
        
        try:
            normalized_query = query.lower().strip() if query else ""

            # Only session-backed clicks may influence a query-to-file relationship.
            if normalized_query:
                query_files_key = CacheKeyGenerator.query_files_mapping(normalized_query)
                await self.cache.zincrby(query_files_key, 1.0, file_unique_id)
                await self.cache.expire(query_files_key, self.ttl.QUERY_FILES_MAPPING)
            
            # Track user file interactions
            user_interactions_key = CacheKeyGenerator.user_file_interactions(user_id)
            await self.cache.zincrby(user_interactions_key, 1.0, file_unique_id)
            await self.cache.expire(user_interactions_key, self.ttl.USER_SEARCH_HISTORY)

            await self.invalidate_user_recommendations(user_id)
            
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
                if normalized_prev and normalized_prev != normalized_current:
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

            await self.invalidate_user_recommendations(user_id)
            
        except Exception as e:
            logger.error(f"Error tracking search sequence for user {user_id}: {e}")

    async def track_successful_search(self, user_id: int, current_query: str) -> None:
        """Persist and sequence a successful search within the configured time window."""
        if not current_query or len(current_query.strip()) < 2:
            return

        last_search_key = CacheKeyGenerator.user_last_search(user_id)
        try:
            previous_state = await self.cache.get(last_search_key)
            if isinstance(previous_state, dict):
                previous_query = previous_state.get('query')
            elif isinstance(previous_state, (str, bytes)):
                previous_query = self._as_text(previous_state)
            else:
                previous_query = None

            await self.track_search_sequence(user_id, previous_query, current_query)
            await self.cache.set(
                last_search_key,
                {'query': current_query.lower().strip()},
                expire=self.ttl.USER_LAST_SEARCH
            )
        except Exception as e:
            logger.error(f"Error persisting successful search for user {user_id}: {e}")

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
        Get queries similar to the current one based on co-occurrence.
        Falls back to fuzzy matching if co-occurrence data is insufficient.
        
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
                candidate = self._as_text(result)
                if candidate.lower().strip() != normalized_query and candidate not in similar_queries:
                    similar_queries.append(candidate)
            
            # If we don't have enough co-occurrence data, try fuzzy matching as fallback
            if len(similar_queries) < limit and hasattr(self, 'search_history_service') and self.search_history_service:
                try:
                    # Get global top searches for fuzzy matching
                    global_keywords = await self.search_history_service.get_global_top_searches(limit=20)
                    if global_keywords:
                        from core.utils.helpers import find_similar_queries
                        fuzzy_matches = find_similar_queries(
                            normalized_query,
                            global_keywords,
                            threshold=70.0,  # 70% similarity
                            max_results=limit - len(similar_queries)
                        )
                        # Add fuzzy matches that aren't already in co-occurrence results
                        for match, _ in fuzzy_matches:
                            if match not in similar_queries and match != normalized_query:
                                similar_queries.append(match)
                                if len(similar_queries) >= limit:
                                    break
                except Exception as e:
                    logger.debug(f"Error in fuzzy matching fallback for similar queries: {e}")
            
            return similar_queries[:limit]
            
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
                'trending_files': [...],  # List of file_unique_ids
                'based_on_history': [...]  # List of file_unique_ids
            }
        """
        try:
            # Check cache first
            cache_key = CacheKeyGenerator.user_recommendations_cache(user_id)
            cached = await self.cache.get(cache_key)
            if isinstance(cached, dict):
                return cached
            if cached is not None:
                await self.cache.delete(cache_key)
            
            recommendations = {
                'similar_queries': [],
                'trending_files': [],
                'based_on_history': []
            }
            recommendation_reasons = {}

            feedback = {'more': [], 'less': []}
            feature_service = getattr(self, 'feature_service', None)
            if (
                feature_service
                and feature_service.enabled('FEATURE_RECOMMENDATION_FEEDBACK')
            ):
                try:
                    feedback = await feature_service.repository.get_recommendation_feedback(
                        user_id
                    )
                except Exception as e:
                    logger.debug(f"Could not load recommendation feedback for {user_id}: {e}")

            # Use clicked files as the primary profile signal, then recommend
            # related files that appeared alongside them. Do not recommend files
            # the user has already interacted with.
            interaction_key = CacheKeyGenerator.user_file_interactions(user_id)
            interaction_values = await self.cache.zrevrange(
                interaction_key, 0, 4, with_scores=False
            )
            interacted_file_ids = [self._as_text(value) for value in interaction_values]
            interacted_file_set = set(interacted_file_ids)
            interacted_file_set.update(feedback.get('more', []))
            negative_file_set = set(feedback.get('less', []))
            profile_sources = list(dict.fromkeys(
                feedback.get('more', []) + interacted_file_ids
            ))

            for file_id in profile_sources:
                related_values = await self.cache.zrevrange(
                    CacheKeyGenerator.file_cooccurrence(file_id),
                    0,
                    limit - 1,
                    with_scores=False
                )
                for related in related_values:
                    related_id = self._as_text(related)
                    if (
                        related_id not in interacted_file_set
                        and related_id not in negative_file_set
                    ):
                        recommendations['based_on_history'].append(related_id)
                        recommendation_reasons.setdefault(
                            related_id,
                            "Related to a file you liked or downloaded"
                        )
            
            # Get user's recent searches
            if hasattr(self, 'search_history_service') and self.search_history_service:
                user_keywords = await self.search_history_service.get_most_searched_keywords(user_id, limit=3)
                
                if user_keywords:
                    # Get similar queries based on user's top searches
                    for keyword in user_keywords:
                        similar = await self.get_similar_queries(keyword, limit=2)
                        recommendations['similar_queries'].extend(similar)
                    
                    # Get files based on user's search history
                    for keyword in user_keywords[:2]:
                        files = await self.get_recommended_files_from_query(keyword, limit=3)
                        recommendations['based_on_history'].extend(files)
                        for file_id in files:
                            recommendation_reasons.setdefault(
                                file_id, f"Because you searched for {keyword}"
                            )
                else:
                    # New user with no search history - use global trends as fallback
                    logger.debug(f"User {user_id} has no search history, using global trends")
                
                # Get trending files (from global top searches) - always show these
                global_keywords = await self.search_history_service.get_global_top_searches(limit=5)
                for keyword in global_keywords:
                    files = await self.get_recommended_files_from_query(keyword, limit=2)
                    recommendations['trending_files'].extend(files)
                    for file_id in files:
                        recommendation_reasons.setdefault(file_id, "Trending with users")
                    
                    # If user has no history, also add global keywords as similar queries
                    if not user_keywords:
                        recommendations['similar_queries'].extend(global_keywords[:3])
            
            # Remove duplicates and limit
            recommendations['similar_queries'] = list(dict.fromkeys(recommendations['similar_queries']))[:limit]
            recommendations['trending_files'] = [
                file_id for file_id in dict.fromkeys(recommendations['trending_files'])
                if file_id not in interacted_file_set and file_id not in negative_file_set
            ][:limit]
            recommendations['based_on_history'] = [
                file_id for file_id in dict.fromkeys(recommendations['based_on_history'])
                if file_id not in interacted_file_set and file_id not in negative_file_set
            ][:limit]

            if (
                feature_service
                and feature_service.enabled('FEATURE_RECOMMENDATION_EXPLANATIONS')
            ):
                returned_file_ids = set(
                    recommendations['trending_files']
                    + recommendations['based_on_history']
                )
                recommendations['reasons'] = {
                    file_id: reason
                    for file_id, reason in recommendation_reasons.items()
                    if file_id in returned_file_ids
                }
            
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
