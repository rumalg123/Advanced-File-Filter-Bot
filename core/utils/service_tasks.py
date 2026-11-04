"""Task ownership for services used both inside and outside the bot."""
import asyncio

from core.utils.logger import get_logger

logger = get_logger(__name__)


class ServiceTasks:
    def __init__(self, manager=None):
        self.manager = manager
        self.pending = set()
        self.closed = False

    def create(self, coroutine, *, auto_delete=False):
        if self.closed:
            coroutine.close()
            return None
        if self.manager is not None:
            factory = (self.manager.create_auto_delete_task if auto_delete
                       else self.manager.create_background_task)
            return factory(coroutine)
        task = asyncio.create_task(coroutine)
        self.pending.add(task)
        task.add_done_callback(self._done)
        return task

    def _done(self, task):
        self.pending.discard(task)
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                logger.error('Service task failed', exc_info=(type(error), error, error.__traceback__))

    async def close(self):
        self.closed = True
        tasks = list(self.pending)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
