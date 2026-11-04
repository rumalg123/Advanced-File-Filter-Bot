import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.services.indexing import IndexingService
from handlers.channel import ChannelHandler


class IteratingBot:
    def __init__(self, service, cancel_after_first=False):
        self.service = service
        self.cancel_after_first = cancel_after_first
        self.first_message_id = None

    async def iter_messages(self, _chat_id, _last_message_id, first_message_id):
        self.first_message_id = first_message_id
        yield SimpleNamespace(id=1)
        if self.cancel_after_first:
            self.service.cancel()
        yield SimpleNamespace(id=2)


@pytest.mark.asyncio
async def test_setskip_reaches_iterator_and_is_one_shot():
    service = IndexingService(SimpleNamespace(), SimpleNamespace())
    service._process_message_batch = AsyncMock(return_value={})
    bot = IteratingBot(service)

    await service.set_skip_number(50)
    stats = await service.index_files(bot, -1001, 100)

    assert bot.first_message_id == 50
    assert stats["total_messages"] == 2
    assert service.current_index == 0


@pytest.mark.asyncio
async def test_cancelled_indexing_processes_pending_batch_once():
    service = IndexingService(SimpleNamespace(), SimpleNamespace())
    service._process_message_batch = AsyncMock(return_value={})
    bot = IteratingBot(service, cancel_after_first=True)

    await service.index_files(bot, -1001, 100)

    service._process_message_batch.assert_awaited_once()


@pytest.mark.asyncio
async def test_full_channel_queue_uses_overflow_without_blocking():
    handler = object.__new__(ChannelHandler)
    handler.bot = SimpleNamespace(config=SimpleNamespace())
    handler.message_queue = asyncio.Queue(maxsize=1)
    handler.message_queue.put_nowait({"existing": True})
    handler.overflow_queue = []
    handler.max_overflow_size = 2
    handler.last_warning_time = 0
    handler.queue_full_warnings = 0

    message = SimpleNamespace(
        chat=SimpleNamespace(id=-1001),
        from_user=None
    )
    await asyncio.wait_for(handler.handle_channel_media(SimpleNamespace(), message), timeout=0.1)

    assert handler.overflow_queue[0]["message"] is message


@pytest.mark.asyncio
@pytest.mark.parametrize('validation_error',[None,'Bot cannot access this channel'])
async def test_handled_index_link_stops_later_file_search(monkeypatch, validation_error):
    from pyrogram import StopPropagation
    from handlers.indexing import IndexingHandler
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    handler=object.__new__(IndexingHandler)
    handler.bot=SimpleNamespace(config=SimpleNamespace(ADMINS=[1]))
    handler.indexing_service=SimpleNamespace(validate_channel=AsyncMock(return_value=(123,validation_error)))
    message=SimpleNamespace(from_user=SimpleNamespace(id=1),
        text='https://t.me/c/123456/2',reply=AsyncMock())
    client=SimpleNamespace(get_messages=AsyncMock())
    monkeypatch.setattr('handlers.indexing.telegram_api.call_api',AsyncMock(return_value=SimpleNamespace(empty=False)))
    with pytest.raises(StopPropagation):
        await handler.handle_index_request(client,message)
    message.reply.assert_awaited_once()
