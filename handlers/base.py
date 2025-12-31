"""
Base handler class to eliminate duplicate cleanup and registration patterns.

All handlers should inherit from BaseHandler to get consistent:
- Handler registration with handler_manager support
- Cleanup logic with proper shutdown handling
- Auto-delete task tracking
- Queue management
- Background task cleanup
"""
import asyncio
from abc import ABC, abstractmethod
from typing import List, Optional, Callable, Tuple, Any, Dict
from weakref import WeakSet

from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.types import Message

from core.utils.logger import get_logger

logger = get_logger(__name__)


class BaseHandler(ABC):
    """Base class for all handlers with common cleanup and registration logic"""

    def __init__(self, bot):
        self.bot = bot
        self._handlers: List[Any] = []
        self._shutdown = asyncio.Event()
        self.auto_delete_tasks: WeakSet = WeakSet()
        self._handler_name = self.__class__.__name__
        self._background_tasks: List[asyncio.Task] = []
        self._queues: List[asyncio.Queue] = []

    def _register_handler(self, handler) -> None:
        """Register a single handler with handler_manager support"""
        if hasattr(self.bot, 'handler_manager') and self.bot.handler_manager:
            self.bot.handler_manager.add_handler(handler)
        else:
            self.bot.add_handler(handler)
        self._handlers.append(handler)

    def _register_message_handlers(
        self,
        handlers_to_register: List[Tuple[Callable, Any]]
    ) -> None:
        """
        Register multiple message handlers.

        Args:
            handlers_to_register: List of (handler_func, filter) tuples
        """
        for handler_func, handler_filter in handlers_to_register:
            handler = MessageHandler(handler_func, handler_filter)
            self._register_handler(handler)

    def _register_callback_handlers(
        self,
        handlers_to_register: List[Tuple[Callable, Any]]
    ) -> None:
        """
        Register multiple callback query handlers.

        Args:
            handlers_to_register: List of (handler_func, filter) tuples
        """
        for handler_func, handler_filter in handlers_to_register:
            handler = CallbackQueryHandler(handler_func, handler_filter)
            self._register_handler(handler)

    def _create_auto_delete_task(self, coro) -> Optional[asyncio.Task]:
        """Create an auto-delete task with proper tracking"""
        if self._shutdown.is_set():
            logger.debug(f"{self._handler_name}: Shutdown in progress, not creating new task")
            coro.close()
            return None

        if hasattr(self.bot, 'handler_manager') and self.bot.handler_manager:
            return self.bot.handler_manager.create_auto_delete_task(coro)
        else:
            task = asyncio.create_task(coro)
            self.auto_delete_tasks.add(task)
            return task

    def _schedule_auto_delete(self, message: Message, delay: int) -> Optional[asyncio.Task]:
        """Schedule auto-deletion of a message"""
        if delay <= 0 or self._shutdown.is_set():
            return None

        coro = self._auto_delete_message(message, delay)
        return self._create_auto_delete_task(coro)

    def _track_task(self, coro) -> Optional[asyncio.Task]:
        """Create and track a background task"""
        if self._shutdown.is_set():
            coro.close()
            return None

        task = asyncio.create_task(coro)
        self._background_tasks.append(task)
        return task

    def _register_queue(self, queue: asyncio.Queue) -> None:
        """Register a queue for cleanup"""
        self._queues.append(queue)

    def _clear_queues(self) -> int:
        """Clear all registered queues, returns total items cleared"""
        total_cleared = 0
        for queue in self._queues:
            while not queue.empty():
                try:
                    queue.get_nowait()
                    total_cleared += 1
                except asyncio.QueueEmpty:
                    break
        return total_cleared

    async def _auto_delete_message(self, message: Message, delay: int) -> None:
        """Auto-delete message after delay"""
        try:
            await asyncio.sleep(delay)
            if not self._shutdown.is_set():
                await message.delete()
        except asyncio.CancelledError:
            logger.debug(f"{self._handler_name}: Auto-delete task cancelled")
        except Exception as e:
            logger.debug(f"{self._handler_name}: Failed to delete message: {e}")

    async def cleanup(self) -> None:
        """Clean up handler resources"""
        logger.info(f"Cleaning up {self._handler_name}...")

        # Signal shutdown
        self._shutdown.set()

        # Clear queues first (always do this)
        queue_items_cleared = self._clear_queues()
        if queue_items_cleared > 0:
            logger.info(f"{self._handler_name}: Cleared {queue_items_cleared} items from queues")

        # Cancel and await background tasks
        if self._background_tasks:
            cancelled_bg = 0
            for task in self._background_tasks:
                if not task.done():
                    task.cancel()
                    cancelled_bg += 1
            if cancelled_bg > 0:
                await asyncio.gather(*self._background_tasks, return_exceptions=True)
                logger.debug(f"{self._handler_name}: Cancelled {cancelled_bg} background tasks")
            self._background_tasks.clear()

        # If handler_manager is available, let it handle handler removal
        if hasattr(self.bot, 'handler_manager') and self.bot.handler_manager:
            logger.info(f"{self._handler_name}: HandlerManager will handle handler removal")
            for handler in self._handlers:
                handler_id = id(handler)
                self.bot.handler_manager.removed_handlers.add(handler_id)
            self._handlers.clear()
            self.auto_delete_tasks.clear()
            logger.info(f"{self._handler_name} cleanup complete")
            return

        # Manual cleanup only if no handler_manager
        # Cancel auto-delete tasks
        active_tasks = list(self.auto_delete_tasks)
        cancelled_count = 0

        for task in active_tasks:
            if not task.done():
                task.cancel()
                cancelled_count += 1

        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)

        logger.debug(f"{self._handler_name}: Cancelled {cancelled_count} auto-delete tasks")

        # Remove handlers
        for handler in self._handlers:
            try:
                self.bot.remove_handler(handler)
            except ValueError as e:
                if "x not in list" in str(e):
                    logger.debug(f"{self._handler_name}: Handler already removed")
                else:
                    logger.error(f"{self._handler_name}: Error removing handler: {e}")
            except Exception as e:
                logger.error(f"{self._handler_name}: Error removing handler: {e}")

        self._handlers.clear()
        self.auto_delete_tasks.clear()
        logger.info(f"{self._handler_name} cleanup complete")

    @abstractmethod
    def register_handlers(self) -> None:
        """Register handlers - must be implemented by subclasses"""
        pass

    def is_shutting_down(self) -> bool:
        """Check if handler is shutting down"""
        return self._shutdown.is_set()
