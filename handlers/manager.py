"""
Centralized handler manager with proper cleanup to prevent memory leaks
"""
import asyncio
import logging
from typing import Dict, List, Set
from weakref import WeakSet
from pyrogram import Client
from pyrogram.handlers import MessageHandler, CallbackQueryHandler

from core.utils.logger import get_logger

logger = get_logger(__name__)


class HandlerManager:
    """Manages all handlers and background tasks with proper cleanup"""

    def __init__(self, bot):
        self.bot = bot
        self.handlers: List = []
        self.background_tasks: Set[asyncio.Task] = set()
        self.auto_delete_tasks: WeakSet = WeakSet()  # Use WeakSet for auto-cleanup
        self.handler_instances: Dict = {}
        self._shutdown_event = asyncio.Event()

    def add_handler(self, handler):
        """Register a handler with the bot"""
        self.bot.add_handler(handler)
        self.handlers.append(handler)

    def create_background_task(self, coro, name=None):
        """Create and track a background task"""
        task = asyncio.create_task(coro, name=name)
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)
        return task

    def create_auto_delete_task(self, coro):
        """Create an auto-delete task that doesn't need explicit cleanup"""
        task = asyncio.create_task(coro)
        self.auto_delete_tasks.add(task)  # WeakSet auto-removes completed tasks
        return task

    async def cleanup(self):
        """Clean up all handlers and tasks"""
        logger.info("Starting handler manager cleanup...")

        # Set shutdown event
        self._shutdown_event.set()

        # Cancel all background tasks
        for task in self.background_tasks:
            if not task.done():
                task.cancel()

        # Wait for background tasks to complete
        if self.background_tasks:
            await asyncio.gather(*self.background_tasks, return_exceptions=True)

        # Cancel remaining auto-delete tasks
        for task in list(self.auto_delete_tasks):
            if not task.done():
                task.cancel()

        # Remove all handlers from bot
        for handler in self.handlers:
            try:
                self.bot.remove_handler(handler)
            except Exception as e:
                logger.error(f"Error removing handler: {e}")

        # Clean up handler instances
        for name, instance in self.handler_instances.items():
            if hasattr(instance, 'cleanup'):
                try:
                    await instance.cleanup()
                except Exception as e:
                    logger.error(f"Error cleaning up {name}: {e}")

        self.handlers.clear()
        self.handler_instances.clear()
        self.background_tasks.clear()

        logger.info("Handler manager cleanup complete")