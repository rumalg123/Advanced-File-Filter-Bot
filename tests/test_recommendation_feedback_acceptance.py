"""Explicit feedback overrides implicit click seeds without crossing users."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.cache.config import CacheKeyGenerator
from core.services.recommendation import RecommendationService
from test_recommendations_and_similarity import SortedMemoryCache
from favorites_recent_support import storage


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled', [True, False])
async def test_disliked_file_is_not_a_profile_seed(enabled):
    cache = SortedMemoryCache()
    cache.sorted_sets[CacheKeyGenerator.user_file_interactions(42)] = {'disliked': 5, 'liked': 2}
    cache.sorted_sets[CacheKeyGenerator.file_cooccurrence('disliked')] = {'unwanted-neighbor': 10}
    cache.sorted_sets[CacheKeyGenerator.file_cooccurrence('liked')] = {'wanted-neighbor': 1}
    service = RecommendationService(cache)
    service.feature_service = SimpleNamespace(enabled=lambda flag: enabled,
        repository=SimpleNamespace(get_recommendation_feedback=AsyncMock(
            return_value={'more': [], 'less': ['disliked']})))

    result = await service.get_recommendations_for_user(42)

    assert 'wanted-neighbor' in result['based_on_history']
    assert ('unwanted-neighbor' in result['based_on_history']) is (not enabled)


@pytest.mark.asyncio
async def test_explicit_positive_seed_has_priority_and_reset_restores_implicit_seed():
    cache = SortedMemoryCache()
    cache.sorted_sets[CacheKeyGenerator.user_file_interactions(42)] = {'frequent': 10, 'preferred': 1}
    cache.sorted_sets[CacheKeyGenerator.file_cooccurrence('frequent')] = {'ordinary': 1}
    cache.sorted_sets[CacheKeyGenerator.file_cooccurrence('preferred')] = {'preferred-neighbor': 1}
    feedback = {'more': ['preferred'], 'less': []}
    service = RecommendationService(cache)
    service.feature_service = SimpleNamespace(enabled=lambda flag: flag=='FEATURE_RECOMMENDATION_FEEDBACK',
        repository=SimpleNamespace(get_recommendation_feedback=AsyncMock(side_effect=lambda uid: feedback)))
    assert (await service.get_recommendations_for_user(42))['based_on_history'][0] == 'preferred-neighbor'
    feedback.update(more=[], less=['frequent'])
    await service.invalidate_user_recommendations(42)
    assert (await service.get_recommendations_for_user(42))['based_on_history'] == ['preferred-neighbor']
    feedback['less'] = []
    await service.invalidate_user_recommendations(42)
    assert (await service.get_recommendations_for_user(42))['based_on_history'][0] == 'ordinary'


@pytest.mark.integration
@pytest.mark.asyncio
async def test_feedback_upserts_and_resets_are_user_scoped_in_real_mongo(storage):
    repo, _, db = storage
    for signal in ['more', 'more', 'less']:
        assert await repo.set_recommendation_feedback(42, 'same-file', signal)
    assert await repo.set_recommendation_feedback(43, 'same-file', 'more')
    assert await db.recommendation_feedback.count_documents({}) == 2
    assert await repo.get_recommendation_feedback(42) == {'more': [], 'less': ['same-file']}
    assert await repo.get_recommendation_feedback(43) == {'more': ['same-file'], 'less': []}
    assert len(await repo.list_recommendation_feedback(42)) == 1
    assert await repo.delete_recommendation_feedback(42, 'same-file')
    assert not await repo.delete_recommendation_feedback(42, 'same-file')
    assert await repo.get_recommendation_feedback(42) == {'more': [], 'less': []}
    assert await repo.get_recommendation_feedback(43) == {'more': ['same-file'], 'less': []}
