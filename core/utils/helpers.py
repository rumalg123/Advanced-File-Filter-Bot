# core/utils/helpers.py
"""Common utility functions used across the application"""
import base64
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional, List, Callable, TYPE_CHECKING

from pyrogram.file_id import FileId

from core.constants import ByteConstants, DisplayConstants

if TYPE_CHECKING:
    from pyrogram.types import User, Chat, Message as PyrogramMessage


def format_file_size(size: int) -> str:
    """Format file size in human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < ByteConstants.KB:
            return f"{size:.2f} {unit}"
        size /= ByteConstants.KB
    return f"{size:.2f} TB"


def extract_file_ref(file_id: str) -> str:
    """
    Extract file reference from Telegram file_id.

    Args:
        file_id: Telegram file ID string

    Returns:
        URL-safe base64 encoded file reference or fallback hash
    """
    try:
        decoded = FileId.decode(file_id)
        file_ref = base64.urlsafe_b64encode(
            decoded.file_reference
        ).decode().rstrip("=")
        return file_ref
    except Exception:
        # Generate a fallback ref using hash
        return hashlib.md5(file_id.encode()).hexdigest()[:DisplayConstants.FALLBACK_HASH_LENGTH]


class MessageProxy:
    """
    A proxy class for creating message-like objects from callback queries.

    This replaces the fragile `type('obj', (object,), {...})()` pattern
    used to create fake message objects when handling subscription callbacks.

    Provides all commonly used Message attributes with sensible defaults.
    """

    def __init__(
        self,
        from_user: 'User',
        chat: Optional['Chat'] = None,
        text: str = '',
        command: Optional[List[str]] = None,
        reply_text: Optional[Callable] = None,
        reply: Optional[Callable] = None,
        message_id: Optional[int] = None,
        date: Optional[datetime] = None
    ):
        # Core attributes
        self.from_user = from_user
        self.chat = chat
        self.text = text
        self.command = command or []
        self.message_id = message_id
        self.date = date

        # Reply methods - use provided callbacks or no-op
        self._reply_text = reply_text
        self._reply = reply

        # Message metadata
        self.reply_to_message = None
        self.forward_from = None
        self.forward_from_chat = None
        self.edit_date = None
        self.media_group_id = None
        self.author_signature = None
        self.via_bot = None
        self.outgoing = False
        self.matches = []

        # Content attributes
        self.caption = None
        self.entities = []
        self.caption_entities = []

        # Media attributes (all None for proxy)
        self.audio = None
        self.document = None
        self.photo = None
        self.sticker = None
        self.animation = None
        self.game = None
        self.video = None
        self.voice = None
        self.video_note = None
        self.contact = None
        self.location = None
        self.venue = None
        self.web_page = None
        self.poll = None
        self.dice = None

    async def reply_text(self, *args, **kwargs):
        """Proxy reply_text method"""
        if self._reply_text:
            return await self._reply_text(*args, **kwargs)
        return None

    async def reply(self, *args, **kwargs):
        """Proxy reply method"""
        if self._reply:
            return await self._reply(*args, **kwargs)
        return None

    @classmethod
    def from_callback_query(
        cls,
        query,
        text: str = '',
        command: Optional[List[str]] = None
    ) -> 'MessageProxy':
        """
        Create a MessageProxy from a CallbackQuery.

        Args:
            query: The CallbackQuery object
            text: The text for the fake message (e.g., '/start param')
            command: Parsed command parts (e.g., ['/start', 'param'])

        Returns:
            MessageProxy instance
        """
        return cls(
            from_user=query.from_user,
            chat=query.message.chat if query.message else None,
            text=text,
            command=command,
            reply_text=query.message.reply_text if query.message else None,
            reply=query.message.reply if query.message else None,
            message_id=query.message.id if query.message else None,
            date=query.message.date if query.message else None
        )


def extract_file_info(message: 'PyrogramMessage') -> Optional[Dict[str, Any]]:
    """
    Extract file information from a message.

    Consolidated utility to replace duplicate file extraction logic
    in delete.py and channel.py handlers.

    Args:
        message: Pyrogram Message object

    Returns:
        Dictionary with file info or None if no media found
    """
    media_types = [
        ('document', lambda m: m.document),
        ('video', lambda m: m.video),
        ('audio', lambda m: m.audio),
        ('photo', lambda m: m.photo),
        ('animation', lambda m: m.animation),
        ('voice', lambda m: m.voice),
        ('video_note', lambda m: m.video_note),
        ('sticker', lambda m: m.sticker)
    ]

    for media_type, getter in media_types:
        media = getter(message)
        if media:
            file_name = getattr(media, 'file_name', None)
            if not file_name:
                # Generate a descriptive name
                file_name = f"{media_type.title()}_{media.file_unique_id[:DisplayConstants.FILE_UNIQUE_ID_DISPLAY_LENGTH]}"

            return {
                'file_unique_id': media.file_unique_id,
                'file_id': media.file_id,
                'file_name': file_name,
                'file_size': getattr(media, 'file_size', 0),
                'media_type': media_type,
                'mime_type': getattr(media, 'mime_type', None),
                'message': message
            }

    return None