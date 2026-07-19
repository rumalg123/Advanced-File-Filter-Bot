# handlers/commands_handlers/base.py
import asyncio
from typing import Any, Tuple

from core.utils.logger import get_logger

logger = get_logger(__name__)


class BaseCommandHandler:
    """Base class with shared utilities for command handlers"""

    def __init__(self, bot):
        self.bot = bot

    async def _auto_delete_message(self, message, delay: int):
        """Auto-delete message after delay"""
        if delay <= 0:
            return
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except Exception as e:
            logger.debug(f"Failed to delete message: {e}")

    def _schedule_auto_delete(self, message, delay: int | None = None):
        """Schedule a transient command response through the shared task manager."""
        if message is None:
            return None

        if delay is None:
            delay = getattr(
                getattr(self.bot, 'config', None),
                'MESSAGE_DELETE_SECONDS',
                0,
            )
        try:
            delay = int(delay or 0)
        except (TypeError, ValueError):
            delay = 0
        if delay <= 0:
            return None

        coroutine = self._auto_delete_message(message, delay)
        manager = getattr(self.bot, 'handler_manager', None)
        if manager:
            return manager.create_auto_delete_task(coroutine)
        return asyncio.create_task(coroutine)

    async def _reply_text_with_auto_delete(
        self,
        message,
        text: str,
        **kwargs: Any,
    ):
        """Reply with text and apply the configured transient-message timer."""
        sent_message = await message.reply_text(text, **kwargs)
        self._schedule_auto_delete(sent_message)
        return sent_message

    async def _reply_photo_with_auto_delete(
        self,
        message,
        **kwargs: Any,
    ):
        """Reply with a photo and apply the configured transient-message timer."""
        sent_message = await message.reply_photo(**kwargs)
        self._schedule_auto_delete(sent_message)
        return sent_message

    async def check_file_access(self, user_id: int) -> Tuple[bool, str]:
        """
        Check if user can access files with owner_id automatically resolved.

        This is a convenience wrapper that handles the common pattern of
        passing owner_id from config.ADMINS[0].

        Args:
            user_id: The user's ID to check

        Returns:
            Tuple of (can_access, reason_message)
        """
        owner_id = self.bot.config.ADMINS[0] if self.bot.config.ADMINS else None
        return await self.bot.user_repo.can_retrieve_file(user_id, owner_id)

    def get_owner_id(self) -> int | None:
        """Get the primary admin/owner ID from config."""
        return self.bot.config.ADMINS[0] if self.bot.config.ADMINS else None
