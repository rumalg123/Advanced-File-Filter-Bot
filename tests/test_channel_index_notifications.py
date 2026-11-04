"""Admin indexing notifications must not change successful indexing outcomes."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from handlers.channel import ChannelHandler


def handler_fixture(monkeypatch, *, channel=-1009, status=1, acknowledged=True):
    import handlers.channel as module

    handler = object.__new__(ChannelHandler)
    handler._shutdown = asyncio.Event()
    handler.processing_config = SimpleNamespace(inter_message_delay=0)
    media = SimpleNamespace(file_name='QA indexed file')
    job = {'_id': '-1001:17', 'chat_id': -1001, 'media': {'file_name': media.file_name}}
    state = {'acknowledged': False}

    async def acknowledge(_job):
        state['acknowledged'] = acknowledged
        handler._shutdown.set()
        return acknowledged

    async def fail(_job, _error):
        handler._shutdown.set()
        return 'pending'

    handler.durable_jobs = SimpleNamespace(
        ensure_indexes=AsyncMock(), claim=AsyncMock(return_value=job),
        acknowledge=AsyncMock(side_effect=acknowledge), fail=AsyncMock(side_effect=fail))
    handler.bot = SimpleNamespace(config=SimpleNamespace(LOG_CHANNEL=channel),
        send_message=AsyncMock(), media_repo=SimpleNamespace(
            _dict_to_entity=lambda snapshot: media,
            save_media=AsyncMock(return_value=(status == 1, status, None))),
        feature_service=SimpleNamespace(persist_new_media=AsyncMock()))
    handler.channel_repo = SimpleNamespace(update_indexed_count=AsyncMock())

    async def gateway(operation, *args, **kwargs):
        assert kwargs.pop('chat_id') == channel
        return await operation(*args, **kwargs)

    call = AsyncMock(side_effect=gateway)
    monkeypatch.setattr(module.telegram_api, 'call_api', call)
    return handler, call, state


@pytest.mark.asyncio
async def test_durable_indexing_sends_summary_only_after_job_acknowledgement(monkeypatch):
    handler, call, state = handler_fixture(monkeypatch)

    async def send(chat_id, text):
        assert state['acknowledged'] is True
        handler.bot.feature_service.persist_new_media.assert_awaited_once()
        assert chat_id == -1009
        assert 'Auto-Index Batch Summary' in text
        assert 'Indexed: 1' in text
        assert 'Duplicates: 0' in text
        assert 'Errors: 0' in text
        assert 'Total Processed: 1' in text

    handler.bot.send_message.side_effect = send
    await handler._process_durable_queue()
    handler.bot.send_message.assert_awaited_once()
    handler.durable_jobs.fail.assert_not_awaited()
    call.assert_awaited_once()


@pytest.mark.asyncio
async def test_notification_failure_keeps_index_job_acknowledged_without_retry(monkeypatch, caplog):
    handler, call, state = handler_fixture(monkeypatch)
    handler.bot.send_message.side_effect = RuntimeError('fixture Telegram failure')
    await handler._process_durable_queue()
    handler.bot.send_message.assert_awaited_once()
    assert state['acknowledged'] is True
    handler.bot.media_repo.save_media.assert_awaited_once()
    handler.durable_jobs.fail.assert_not_awaited()
    handler.bot.feature_service.persist_new_media.assert_awaited_once()
    assert 'auto-index summary' in caplog.text.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize('channel,status,acknowledged', [
    (0, 1, True),       # Explicitly disabled log channel.
    (-1009, 0, True),   # Duplicate, including a replay after an earlier save.
    (-1009, 2, True),   # Media save rejected: no success notification.
    (-1009, 1, False),  # Lost lease: this worker must not announce success.
])
async def test_no_success_notification_for_disabled_duplicate_failed_or_unowned_jobs(
        monkeypatch, channel, status, acknowledged):
    handler, call, state = handler_fixture(monkeypatch, channel=channel,
                                          status=status, acknowledged=acknowledged)
    await handler._process_durable_queue()
    handler.bot.send_message.assert_not_awaited()
    call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('side_effect', ['channel_counter', 'saved_search'])
async def test_other_optional_side_effect_failure_does_not_hide_index_summary(monkeypatch, side_effect):
    handler, call, state = handler_fixture(monkeypatch)
    operation = (handler.channel_repo.update_indexed_count if side_effect == 'channel_counter'
                 else handler.bot.feature_service.persist_new_media)
    operation.side_effect = RuntimeError('fixture optional side effect failure')
    await handler._process_durable_queue()
    handler.bot.send_message.assert_awaited_once()
    handler.durable_jobs.fail.assert_not_awaited()
    assert state['acknowledged'] is True


@pytest.mark.asyncio
async def test_cancellation_during_summary_does_not_requeue_saved_media(monkeypatch):
    handler, call, state = handler_fixture(monkeypatch)
    handler.bot.send_message.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await handler._process_durable_queue()
    assert state['acknowledged'] is True
    handler.durable_jobs.fail.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_batch_retains_one_summary_with_complete_counts(monkeypatch):
    import handlers.channel as module
    handler, call, state = handler_fixture(monkeypatch)
    handler._process_single_message = AsyncMock(side_effect=['indexed', 'duplicate', 'error'])
    monkeypatch.setattr(module.asyncio, 'sleep', AsyncMock())
    await handler._process_message_batch([{'message': object()} for _ in range(3)])
    handler.bot.send_message.assert_awaited_once()
    body = handler.bot.send_message.await_args.args[1]
    for expected in ['Indexed: 1', 'Duplicates: 1', 'Errors: 1', 'Total Processed: 3']:
        assert expected in body


@pytest.mark.asyncio
async def test_legacy_notification_failure_is_logged_without_failing_batch(monkeypatch, caplog):
    import handlers.channel as module
    handler, call, state = handler_fixture(monkeypatch)
    handler._process_single_message = AsyncMock(return_value='indexed')
    handler.bot.send_message.side_effect = RuntimeError('fixture Telegram failure')
    monkeypatch.setattr(module.asyncio, 'sleep', AsyncMock())
    await handler._process_message_batch([{'message': object()}])
    handler.bot.send_message.assert_awaited_once()
    assert 'auto-index summary' in caplog.text.lower()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize('send_fails', [False, True])
async def test_real_mongo_job_stays_done_after_log_notification(monkeypatch, send_fails):
    import os
    from uuid import uuid4
    from motor.motor_asyncio import AsyncIOMotorClient
    from repositories.channel_index_jobs import ChannelIndexJobRepository
    from scripts.profile_media_search import is_local

    uri = os.getenv('TEST_MONGO_URI')
    if not uri:
        pytest.skip('Requires disposable local MongoDB')
    assert is_local(uri)
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=3000)
    name = 'qa_index_log_' + uuid4().hex
    collection = client[name].channel_index_jobs

    class Pool:
        async def get_collection(self, collection_name):
            return client[name][collection_name]

    handler, call, state = handler_fixture(monkeypatch)
    jobs = ChannelIndexJobRepository(Pool())
    handler.durable_jobs = jobs
    fail = AsyncMock(wraps=jobs.fail)
    monkeypatch.setattr(jobs, 'fail', fail)
    acknowledge = jobs.acknowledge

    async def acknowledge_and_stop(job):
        result = await acknowledge(job)
        handler._shutdown.set()
        return result

    monkeypatch.setattr(jobs, 'acknowledge', acknowledge_and_stop)

    async def send(chat_id, text):
        record = await collection.find_one({'_id': '-1001:17'})
        assert record['status'] == 'done'
        if send_fails:
            raise RuntimeError('fixture Telegram failure')

    handler.bot.send_message.side_effect = send
    try:
        await jobs.enqueue(-1001, 17, {'file_name': 'QA indexed file'})
        await handler._process_durable_queue()
        handler.bot.send_message.assert_awaited_once()
        fail.assert_not_awaited()
        record = await collection.find_one({'_id': '-1001:17'})
        assert record['status'] == 'done'
        assert record['attempts'] == 1
        assert record['finished_at'] is not None
        assert await jobs.claim() is None
    finally:
        await client.drop_database(name)
        client.close()
