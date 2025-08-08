# handlers/commands_handlers/base.py
import asyncio
from functools import wraps
from pyrogram import Client, enums
from pyrogram.types import Message
from core.utils.logger import get_logger

logger = get_logger(__name__)


def admin_only(func):
    """Decorator to restrict commands to admins only"""
    @wraps(func)
    async def wrapper(self, client: Client, message: Message, *args, **kwargs):
        user_id = message.from_user.id if message.from_user else None
        if not user_id or user_id not in self.bot.config.ADMINS:
            await message.reply_text("⚠️ This command is restricted to bot admins only.")
            return
        return await func(self, client, message, *args, **kwargs)
    return wrapper


def private_only(func):
    """Decorator to restrict commands to private chats only"""
    @wraps(func)
    async def wrapper(self, client: Client, message: Message, *args, **kwargs):
        if message.chat.type != enums.ChatType.PRIVATE:
            await message.reply_text("⚠️ This command can only be used in private chats.")
            return
        return await func(self, client, message, *args, **kwargs)
    return wrapper


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