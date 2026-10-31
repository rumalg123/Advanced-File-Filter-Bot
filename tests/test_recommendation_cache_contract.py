"""Ranking caches must match requested limits, flags and result shape."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.cache.config import CacheKeyGenerator
from core.services.recommendation import RecommendationService
from test_recommendations_and_similarity import SortedMemoryCache


def recommender():
    cache = SortedMemoryCache()
    cache.sorted_sets[CacheKeyGenerator.user_file_interactions(42)] = {'seed': 1}
    cache.sorted_sets[CacheKeyGenerator.file_cooccurrence('seed')] = {'first': 2, 'second': 1}
    flags = {'FEATURE_RECOMMENDATION_FEEDBACK': True, 'FEATURE_RECOMMENDATION_EXPLANATIONS': True}
    feedback = {'more': [], 'less': []}
    service = RecommendationService(cache)
    service.feature_service = SimpleNamespace(enabled=lambda name: flags.get(name, False),
        repository=SimpleNamespace(get_recommendation_feedback=AsyncMock(side_effect=lambda uid: feedback)))
    return service, cache, flags, feedback


@pytest.mark.asyncio
@pytest.mark.parametrize('first,second', [(1, 2), (2, 1)])
async def test_cached_ranking_matches_requested_limit(first, second):
    service, _, _, _ = recommender()
    assert len((await service.get_recommendations_for_user(42, first))['based_on_history']) == first
    assert len((await service.get_recommendations_for_user(42, second))['based_on_history']) == second


@pytest.mark.asyncio
async def test_explanation_flag_change_rejects_old_cached_reasons():
    service, _, flags, _ = recommender()
    assert (await service.get_recommendations_for_user(42))['reasons']
    flags['FEATURE_RECOMMENDATION_EXPLANATIONS'] = False
    assert 'reasons' not in await service.get_recommendations_for_user(42)


@pytest.mark.asyncio
async def test_feedback_flag_change_recomputes_cached_profile():
    service, _, flags, feedback = recommender()
    feedback['less'] = ['seed']
    assert not (await service.get_recommendations_for_user(42))['based_on_history']
    flags['FEATURE_RECOMMENDATION_FEEDBACK'] = False
    assert (await service.get_recommendations_for_user(42))['based_on_history'] == ['first', 'second']


@pytest.mark.asyncio
@pytest.mark.parametrize('cached', [
    {}, {'based_on_history': ['stale']},
    {'similar_queries': 12, 'based_on_history': [], 'trending_files': []},
    {'similar_queries': [], 'based_on_history': [12], 'trending_files': []},
    {'similar_queries': [], 'based_on_history': [], 'trending_files': [], 'reasons': 'invalid'},
])
async def test_legacy_or_malformed_cache_is_recomputed(cached):
    service, cache, _, _ = recommender()
    cache.values[CacheKeyGenerator.user_recommendations_cache(42)] = cached
    assert (await service.get_recommendations_for_user(42))['based_on_history'] == ['first', 'second']


@pytest.mark.asyncio
@pytest.mark.parametrize('limit', [0, -1, True, '3'])
async def test_nonpositive_or_noninteger_limit_returns_empty(limit):
    service, _, _, _ = recommender()
    assert await service.get_recommendations_for_user(42, limit) == {
        'similar_queries': [], 'based_on_history': [], 'trending_files': [],
    }


@pytest.mark.asyncio
async def test_valid_matching_cache_hit_avoids_feedback_read():
    service, _, _, _ = recommender()
    first = await service.get_recommendations_for_user(42)
    service.feature_service.repository.get_recommendation_feedback.reset_mock()
    assert await service.get_recommendations_for_user(42) == first
    service.feature_service.repository.get_recommendation_feedback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('data', [None,
    {'similar_queries': [], 'based_on_history': [12], 'trending_files': [], 'reasons': {}},
    {'similar_queries': [], 'based_on_history': [], 'trending_files': [], 'reasons': {'id': 12}},
    {'similar_queries': ['query']*11, 'based_on_history': [], 'trending_files': [], 'reasons': {}},
])
async def test_versioned_cache_with_invalid_data_is_recomputed(data):
    service, cache, _, _ = recommender()
    cache.values[CacheKeyGenerator.user_recommendations_cache(42)] = {
        'options': {'version': 1, 'limit': 10, 'feedback': True, 'explanations': True}, 'data': data,
    }
    assert (await service.get_recommendations_for_user(42))['based_on_history'] == ['first', 'second']
