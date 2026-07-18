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
