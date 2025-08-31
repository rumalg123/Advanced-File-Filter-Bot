# handlers/commands_handlers/base.py
import asyncio

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