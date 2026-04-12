"""
Enhanced Handler Manager with comprehensive resource tracking and cleanup
"""
import asyncio
import gc
from typing import Dict, List, Set, Optional, Any
from weakref import WeakSet, WeakValueDictionary

from core.utils.logger import get_logger

logger = get_logger(__name__)


class HandlerManager:
    """Manages all handlers and background tasks with proper cleanup"""

    def __init__(self, bot):
        self.bot = bot

        # Handler tracking
        self.handlers: List = []  # All registered handlers
        self.handler_instances: Dict[str, Any] = {}  # Named handler instances
        self.removed_handlers: Set = set()  # Track already removed handlers

        # Task tracking with different strategies
        self.background_tasks: Set[asyncio.Task] = set()  # Long-running tasks
        self.auto_delete_tasks: WeakSet = WeakSet()  # Auto-cleanup tasks
        self.named_tasks: Dict[str, asyncio.Task] = {}  # Named tasks for easy access

        # Memory management
        self._task_refs: WeakValueDictionary = WeakValueDictionary()  # Weak refs to tasks
        self._shutdown_event = asyncio.Event()
        self._cleanup_lock = asyncio.Lock()

        # Statistics
        self.stats = {
            'tasks_created': 0,
            'tasks_completed': 0,
            'tasks_cancelled': 0,
            'handlers_registered': 0,
            'handlers_removed': 0,
            'handlers_removal_failed': 0
        }

    def add_handler(self, handler):
        """Register a handler with the bot"""
        try:
            self.bot.add_handler(handler)
            self.handlers.append(handler)
            self.stats['handlers_registered'] += 1
            logger.debug(f"Registered handler: {type(handler).__name__}")
        except Exception as e:
            logger.error(f"Error adding handler: {e}")
            raise

    def remove_handler(self, handler):
        """Remove a handler from the bot - safely handles already removed handlers"""
        # Check if already removed
        handler_id = id(handler)
        if handler_id in self.removed_handlers:
            logger.debug(f"Handler already removed: {type(handler).__name__}")
            return

        try:
            # Try to remove from bot
            self.bot.remove_handler(handler)

            # Mark as removed
            self.removed_handlers.add(handler_id)

            # Remove from our tracking list
            if handler in self.handlers:
                self.handlers.remove(handler)

            self.stats['handlers_removed'] += 1
            logger.debug(f"Successfully removed handler: {type(handler).__name__}")

        except ValueError as e:
            # Handler not in list - this is okay, it might have been removed already
            if "x not in list" in str(e):
                logger.debug(f"Handler not found in dispatcher (already removed?): {type(handler).__name__}")
                # Still mark as removed to prevent future attempts
                self.removed_handlers.add(handler_id)

                # Remove from our tracking list if present
                if handler in self.handlers:
                    self.handlers.remove(handler)

                # Don't count this as a failure - it's expected during cleanup
                # self.stats['handlers_removal_failed'] += 1
            else:
                # Some other ValueError
                logger.error(f"Unexpected ValueError removing handler: {e}")
                raise

        except Exception as e:
            logger.error(f"Error removing handler {type(handler).__name__}: {e}")
            self.stats['handlers_removal_failed'] += 1

    def create_background_task(self, coro, name: Optional[str] = None) -> asyncio.Task|None:
        """Create and track a long-running background task"""
        if self._shutdown_event.is_set():
            logger.warning(f"Attempted to create task '{name}' during shutdown")
            coro.close()
            return None

        task = asyncio.create_task(coro)

        # Track the task
        self.background_tasks.add(task)
        self.stats['tasks_created'] += 1

        if name:
            if name in self.named_tasks:
                old_task = self.named_tasks[name]
                if not old_task.done():
                    logger.warning(f"Cancelling existing task with name: {name}")
                    old_task.cancel()
            self.named_tasks[name] = task
            task.set_name(name)

        # Cleanup callback
        def cleanup_callback(t):
            self.background_tasks.discard(t)
            if name and name in self.named_tasks and self.named_tasks[name] == t:
                del self.named_tasks[name]
            self.stats['tasks_completed'] += 1
            logger.debug(f"Background task '{name or 'unnamed'}' completed")

        task.add_done_callback(cleanup_callback)
        logger.debug(f"Created background task: {name or 'unnamed'}")
        return task

    def create_auto_delete_task(self, coro) -> asyncio.Task|None:
        """Create a task that auto-cleans up (for short-lived tasks)"""
        if self._shutdown_event.is_set():
            logger.debug("Shutdown in progress, not creating auto-delete task")
            coro.close()
            return None

        task = asyncio.create_task(coro)
        self.auto_delete_tasks.add(task)  # WeakSet auto-removes when done
        self.stats['tasks_created'] += 1

        # Light cleanup callback
        task.add_done_callback(lambda t: self.stats.__setitem__('tasks_completed',
                                                                  self.stats['tasks_completed'] + 1))
        return task

    def get_task(self, name: str) -> Optional[asyncio.Task]:
        """Get a named task if it exists"""
        return self.named_tasks.get(name)

    def cancel_task(self, name: str) -> bool:
        """Cancel a specific named task"""
        task = self.named_tasks.get(name)
        if task and not task.done():
            task.cancel()
            self.stats['tasks_cancelled'] += 1
            logger.info(f"Cancelled task: {name}")
            return True
        return False

    async def cleanup_handler(self, handler_name: str):
        """Clean up a specific handler"""
        if handler_name in self.handler_instances:
            instance = self.handler_instances[handler_name]
            if hasattr(instance, 'cleanup'):
                try:
                    logger.info(f"Cleaning up handler: {handler_name}")
                    await instance.cleanup()
                except Exception as e:
                    logger.error(f"Error cleaning up {handler_name}: {e}")
            del self.handler_instances[handler_name]

    async def cleanup(self):
        """Comprehensive cleanup of all resources"""
        async with self._cleanup_lock:
            logger.info("=" * 50)
            logger.info("Starting HandlerManager cleanup...")
            logger.info(f"Current state: {self.get_stats()}")

            # Set shutdown event
            self._shutdown_event.set()

            # Step 1: Cancel named tasks first (they're usually important)
            for name, task in list(self.named_tasks.items()):
                if not task.done():
                    logger.debug(f"Cancelling named task: {name}")
                    task.cancel()
                    self.stats['tasks_cancelled'] += 1

            # Step 2: Cancel background tasks
            background_tasks = list(self.background_tasks)
            for task in background_tasks:
                if not task.done():
                    task.cancel()
                    self.stats['tasks_cancelled'] += 1

            # Wait for background tasks with timeout
            if background_tasks:
                logger.info(f"Waiting for {len(background_tasks)} background tasks...")
                done, pending = await asyncio.wait(
                    background_tasks,
                    timeout=5.0,
                    return_when=asyncio.ALL_COMPLETED
                )
                if pending:
                    logger.warning(f"{len(pending)} tasks did not complete in time")

            # Step 3: Cancel auto-delete tasks
            auto_delete_tasks = list(self.auto_delete_tasks)
            for task in auto_delete_tasks:
                if not task.done():
                    task.cancel()
                    self.stats['tasks_cancelled'] += 1

            # Brief wait for auto-delete tasks
            if auto_delete_tasks:
                await asyncio.gather(*auto_delete_tasks, return_exceptions=True)

            # Step 4: Clean up handler instances (they will remove their own handlers)
            logger.info(f"Cleaning up {len(self.handler_instances)} handler instances...")
            for name in list(self.handler_instances.keys()):
                await self.cleanup_handler(name)

            # Step 5: Remove remaining handlers from bot (only those not already removed)
            remaining_handlers = [h for h in self.handlers if id(h) not in self.removed_handlers]
            if remaining_handlers:
                logger.info(f"Removing {len(remaining_handlers)} remaining handlers from bot...")
                for handler in remaining_handlers:
                    self.remove_handler(handler)

            # Clear all tracking structures
            self.handlers.clear()
            self.handler_instances.clear()
            self.background_tasks.clear()
            self.named_tasks.clear()
            self.removed_handlers.clear()  # Clear the removed handlers set
            # auto_delete_tasks clears itself (WeakSet)

            # Force garbage collection
            gc.collect()

            logger.info(f"Final stats: {self.get_stats()}")
            logger.info("HandlerManager cleanup complete")
            logger.info("=" * 50)

    def get_stats(self) -> Dict[str, Any]:
        """Get manager statistics"""
        return {
            'handlers_active': len(self.handlers),
            'handler_instances': len(self.handler_instances),
            'background_tasks': len(self.background_tasks),
            'auto_delete_tasks': len(self.auto_delete_tasks),
            'named_tasks': len(self.named_tasks),
            'already_removed_handlers': len(self.removed_handlers),
            'total_created': self.stats['tasks_created'],
            'total_completed': self.stats['tasks_completed'],
            'total_cancelled': self.stats['tasks_cancelled'],
            'handlers_registered': self.stats['handlers_registered'],
            'handlers_removed': self.stats['handlers_removed'],
            'handlers_removal_failed': self.stats['handlers_removal_failed']
        }

    def is_shutting_down(self) -> bool:
        """Check if manager is shutting down"""
        return self._shutdown_event.is_set()

    async def wait_for_shutdown(self, timeout: Optional[float] = None):
        """Wait for shutdown signal"""
        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout)
        except asyncio.TimeoutError:
            pass