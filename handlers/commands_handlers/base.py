# handlers/commands_handlers/base.py
import asyncio
from typing import Tuple

from core.utils.logger import get_logger

logger = get_logger(__name__)


class BaseCommandHandler:
    """Base class with shared utilities for command handlers"""

    def __init__(self, bot):
        self.bot = bot

    async def _auto_delete_message(self, message, delay: int):
        """Auto-delete message after delay"""
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except Exception as e:
            logger.debug(f"Failed to delete message: {e}")

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