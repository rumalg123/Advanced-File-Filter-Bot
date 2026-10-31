from unittest.mock import AsyncMock

import pytest

from subscription_support import fixture


SESSION = 'deeplink_42_aabbccdd'


@pytest.mark.asyncio
@pytest.mark.parametrize('uid,subscribed', [(7, True), (42, False)])
async def test_unsuccessful_retry_preserves_the_original_users_link(uid, subscribed):
    handler, query, cache = fixture('checksub#dl#'+SESSION, uid=uid, subscribed=subscribed)
    cache.values[SESSION] = {'user_id': 42, 'deeplink': 'encoded-file'}
    await handler.handle_checksub_callback(None, query)
    assert SESSION in cache.values
    handler.bot.cache_invalidator.invalidate_subscription_session.assert_not_awaited()
    query.message.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_joining_after_repeated_failed_checks_resumes_the_original_link(monkeypatch):
    handler, query, cache = fixture('checksub#dl#'+SESSION, subscribed=False)
    cache.values[SESSION] = {'user_id': 42, 'deeplink': 'encoded-file'}
    replay = AsyncMock()
    monkeypatch.setattr('handlers.deeplink.DeepLinkHandler.handle_deep_link_internal', replay)
    await handler.handle_checksub_callback(None, query)
    await handler.handle_checksub_callback(None, query)
    handler.bot.subscription_manager.is_subscribed.return_value = True
    await handler.handle_checksub_callback(None, query)
    replay.assert_awaited_once()
    assert replay.await_args.args[-1] == 'encoded-file'
    assert replay.await_args.args[-2].from_user.id == 42
    assert SESSION not in cache.values


@pytest.mark.asyncio
@pytest.mark.parametrize('stored', ['bad-data', {}, {'deeplink': 'encoded-file'},
    {'user_id': None, 'deeplink': 'encoded-file'}])
async def test_malformed_session_cannot_replay_or_be_consumed(monkeypatch, stored):
    handler, query, cache = fixture('checksub#dl#'+SESSION)
    cache.values[SESSION] = stored
    replay = AsyncMock()
    monkeypatch.setattr('handlers.deeplink.DeepLinkHandler.handle_deep_link_internal', replay)
    await handler.handle_checksub_callback(None, query)
    replay.assert_not_awaited()
    handler.bot.cache_invalidator.invalidate_subscription_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_callback_cannot_delete_an_unrelated_cache_key():
    handler, query, cache = fixture('checksub#dl#user:42')
    cache.values['user:42'] = {'user_id': 42, 'deeplink': 'general'}
    await handler.handle_checksub_callback(None, query)
    assert 'user:42' in cache.values
    handler.bot.cache_invalidator.invalidate_subscription_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_retry_returns_a_bounded_response():
    handler, query, _ = fixture('checksub#dl#'+SESSION)
    await handler.handle_checksub_callback(None, query)
    assert 'expired' in query.answer.await_args.args[0].lower()
    assert len(query.answer.await_args.args[0].encode()) <= 200
