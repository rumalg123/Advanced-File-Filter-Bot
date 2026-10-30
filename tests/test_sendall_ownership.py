from sendall_support import fixture, run
import pytest


@pytest.mark.asyncio
async def test_sendall_forged_owner_does_not_read_another_users_cached_results(monkeypatch):
    handler, client, query, _, _ = fixture(monkeypatch)
    handler.bot.cache.get.return_value['user_id'] = 99
    await run(handler, client, query)
    client.send_cached_media.assert_not_awaited()
    handler.bot.user_repo.reserve_quota_atomic.assert_not_awaited()
    assert 'another user' in query.answer.await_args.args[0].lower()

