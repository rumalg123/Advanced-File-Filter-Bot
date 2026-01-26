# core/utils/helpers.py
"""Common utility functions used across the application"""
import base64
import hashlib
import re
from datetime import datetime
from typing import Dict, Any, Optional, List, Callable, TYPE_CHECKING, Tuple

from pyrogram.file_id import FileId

if TYPE_CHECKING:
    from pyrogram.types import User, Chat, Message as PyrogramMessage


def format_file_size(size: int) -> str:
    """Format file size in human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
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
        return hashlib.md5(file_id.encode()).hexdigest()[:20]


_SEASON_EPISODE_PATTERN = re.compile(
    r"[Ss](?P<season>\d{1,2})[ ._/-]*[Ee](?P<episode>\d{1,3})"
)

_EPISODE_ONLY_PATTERN = re.compile(
    r"[^\w]?[Ee](?P<episode>\d{1,3})(?:\D|$)"
)

_RESOLUTION_PATTERN = re.compile(
    r"(?P<resolution>\d{3,4}p)\b",
    re.IGNORECASE,
)

_PIXEL_RESOLUTION_PATTERN = re.compile(
    r"(?P<width>\d{3,4})[xX](?P<height>\d{3,4})"
)


def parse_media_metadata(
    file_name: str,
    caption: Optional[str] = None
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Best-effort parser for season, episode and resolution from text.

    Examples it handles:
    TV Shows:
    - Our.Golden.Days.S01E50.x264.540p.WEB-DL-Phanteam..mkv → season=01, episode=50, resolution=540p
    - Our.Golden.Days.E50.END.KBS.540p.x265.mkv → season=None, episode=50, resolution=540p
    - Positively.Yours.E04.NF.1080p.x265.mkv → season=None, episode=04, resolution=1080p
    - Love.Me.S01E12.NF.x264.720p.mkv → season=01, episode=12, resolution=720p
    - Loving.Strangers.S01E24.2160p.YOUKU.W.mkv → season=01, episode=24, resolution=2160p
    
    Movies (no season/episode):
    - Big.Deal.2025.x265.1080p.iTunes.WEB-DL.mkv → season=None, episode=None, resolution=1080p
    - Heart.Blackened.2017.x265.720p.NF.WEB-DL.mkv → season=None, episode=None, resolution=720p
    """
    text = file_name or ""
    if caption:
        text = f"{text} {caption}"

    season: Optional[str] = None
    episode: Optional[str] = None
    resolution: Optional[str] = None

    # Season + episode first (S01E50)
    match = _SEASON_EPISODE_PATTERN.search(text)
    if match:
        season = match.group("season").zfill(2)
        episode = match.group("episode").zfill(2)
    else:
        # Episode-only patterns (E50 / E04.END)
        match = _EPISODE_ONLY_PATTERN.search(text)
        if match:
            episode = match.group("episode").zfill(2)

    # Resolution like 540p / 1080p / 2160p
    match = _RESOLUTION_PATTERN.search(text)
    if match:
        resolution = match.group("resolution").lower()
    else:
        # Fallback for 1920x1080 style
        match = _PIXEL_RESOLUTION_PATTERN.search(text)
        if match:
            resolution = f"{match.group('width')}x{match.group('height')}"

    return season, episode, resolution


# Patterns for parsing user search queries (natural language)
_QUERY_SEASON_EPISODE_PATTERN = re.compile(
    r"(?:season\s*)?[Ss](?P<season>\d{1,2})(?:\s*episode\s*)?[Ee](?P<episode>\d{1,3})",
    re.IGNORECASE
)

_QUERY_EPISODE_PATTERN = re.compile(
    r"(?:episode\s*|ep\s*)[Ee]?(?P<episode>\d{1,3})\b",
    re.IGNORECASE
)

_QUERY_SEASON_PATTERN = re.compile(
    r"(?:season\s*)[Ss]?(?P<season>\d{1,2})\b",
    re.IGNORECASE
)

_QUERY_RESOLUTION_PATTERN = re.compile(
    r"\b(?P<resolution>\d{3,4}p)\b",
    re.IGNORECASE
)


def parse_search_query(
    query: str
) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    """
    Parse user search query to extract season, episode, resolution and return cleaned query.
    
    Handles natural language queries like:
    - "our golden days episode 45" → cleaned="our golden days", episode="45", season=None, resolution=None
    - "our golden days 540p episode 45" → cleaned="our golden days", episode="45", resolution="540p", season=None
    - "ep45 s01" → cleaned="", episode="45", season="01", resolution=None
    - "our golden days season 1 episode 45" → cleaned="our golden days", season="01", episode="45", resolution=None
    - "our golden days s01e45 1080p" → cleaned="our golden days", season="01", episode="45", resolution="1080p"
    - "our golden days ep 45 tv show" → cleaned="our golden days", episode="45", season=None, resolution=None
    
    Returns:
        (cleaned_query, season, episode, resolution)
    """
    original_query = query
    season: Optional[str] = None
    episode: Optional[str] = None
    resolution: Optional[str] = None
    
    # Extract season + episode together first (S01E45, season 1 episode 45)
    match = _QUERY_SEASON_EPISODE_PATTERN.search(query)
    if match:
        season = match.group("season").zfill(2)
        episode = match.group("episode").zfill(2)
        # Remove the matched pattern from query
        query = _QUERY_SEASON_EPISODE_PATTERN.sub("", query)
    else:
        # Try episode-only patterns (episode 45, ep45, e45, ep 45)
        match = _QUERY_EPISODE_PATTERN.search(query)
        if match:
            episode = match.group("episode").zfill(2)
            query = _QUERY_EPISODE_PATTERN.sub("", query)
        
        # Try season-only patterns (season 1, s01)
        match = _QUERY_SEASON_PATTERN.search(query)
        if match:
            season = match.group("season").zfill(2)
            query = _QUERY_SEASON_PATTERN.sub("", query)
    
    # Extract resolution (540p, 1080p, etc.)
    match = _QUERY_RESOLUTION_PATTERN.search(query)
    if match:
        resolution = match.group("resolution").lower()
        query = _QUERY_RESOLUTION_PATTERN.sub("", query)
    
    # Remove common noise words that don't help with search
    noise_words = ['tv', 'show', 'series', 'drama', 'movie', 'film', 'video', 'file']
    words = query.split()
    cleaned_words = [w for w in words if w.lower() not in noise_words]
    query = ' '.join(cleaned_words)
    
    # Clean up the query: remove extra spaces, trim
    cleaned = re.sub(r'\s+', ' ', query).strip()
    
    return cleaned, season, episode, resolution


def build_fuzzy_regex_pattern(query: str) -> str:
    """
    Build a fuzzy regex pattern that handles:
    - Flexible word boundaries (dots, dashes, underscores)
    - Flexible spacing between words
    - Case-insensitive matching
    
    Examples:
    - "our golden days" → matches "our.golden.days", "our-golden-days", "our_golden_days", etc.
    - "golden" → matches "golden", "golden.", "golden-", "Golden", etc.
    - Handles variations like "our golden days" matching "Our.Golden.Days.S01E45.mkv"
    """
    if not query:
        return '.'
    
    # Split into words and clean
    words = [w.strip() for w in query.split() if w.strip()]
    
    if not words:
        return '.'
    
    if len(words) == 1:
        # Single word: allow flexible boundaries
        word = re.escape(words[0])
        # Match word with flexible boundaries (allows dots, dashes, underscores, spaces)
        return rf'(\b|[\.\+\-\s_]){word}(\b|[\.\+\-\s_])'
    
    # Multiple words: match all words with flexible spacing/separators
    # This allows "our golden days" to match:
    # - "our.golden.days"
    # - "our-golden-days" 
    # - "our_golden_days"
    # - "our golden days"
    # - "Our.Golden.Days.S01E45"
    escaped_words = [re.escape(word) for word in words]
    
    # Join words with flexible separators (space, dot, dash, underscore, or any combination)
    # This makes the search more forgiving of filename formatting
    pattern = r'[\s\.\+\-_]+'.join(escaped_words)
    
    # Wrap with flexible boundaries
    return rf'(\b|[\.\+\-\s_]){pattern}(\b|[\.\+\-\s_])'


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
    
    Note: This function now uses the unified media_extractor module internally
    for consistency. For direct media object extraction, use extract_media_from_message()
    from core.utils.media_extractor.

    Args:
        message: Pyrogram Message object

    Returns:
        Dictionary with file info or None if no media found
    """
    # Use unified media extractor for consistency
    from core.utils.media_extractor import extract_media_info_dict
    return extract_media_info_dict(message)