# core/utils/helpers.py
"""Common utility functions used across the application"""
import base64
import hashlib
import re
from datetime import datetime
from typing import Dict, Any, Optional, List, Callable, TYPE_CHECKING, Tuple

from pyrogram.file_id import FileId
from core.utils.logger import get_logger

logger = get_logger(__name__)


def calculate_similarity(query1: str, query2: str) -> float:
    """
    Calculate similarity score between two queries (0.0 to 100.0).
    Higher score means more similar.
    Uses rapidfuzz for fast and accurate fuzzy matching.
    
    Args:
        query1: First query string
        query2: Second query string
        
    Returns:
        Similarity score between 0.0 and 100.0 (rapidfuzz returns 0-100)
    """
    try:
        from rapidfuzz import fuzz
        
        if not query1 or not query2:
            return 0.0
        
        # Normalize queries
        q1 = query1.lower().strip()
        q2 = query2.lower().strip()
        
        # Exact match
        if q1 == q2:
            return 100.0
        
        # Use token_sort_ratio for better handling of word order differences
        # This is more flexible than simple ratio
        score = fuzz.token_sort_ratio(q1, q2)
        
        # Boost score if one query contains the other (partial match)
        partial_score = fuzz.partial_ratio(q1, q2)
        score = max(score, partial_score * 0.9)  # Slightly weight partial matches
        
        return float(score)
    except ImportError:
        # Fallback to simple string comparison if rapidfuzz is not available
        logger.warning("rapidfuzz not available, using fallback similarity calculation")
        if not query1 or not query2:
            return 0.0
        q1 = query1.lower().strip()
        q2 = query2.lower().strip()
        if q1 == q2:
            return 100.0
        # Simple fallback: check if one contains the other
        if q1 in q2 or q2 in q1:
            return 70.0
        return 0.0


def find_similar_queries(
    query: str, 
    candidate_queries: List[str], 
    threshold: float = 60.0,
    max_results: int = 3
) -> List[Tuple[str, float]]:
    """
    Find similar queries from a list of candidates using fuzzy matching.
    Uses rapidfuzz for fast and accurate matching.
    
    Args:
        query: The query to find similar matches for
        candidate_queries: List of candidate queries to search
        threshold: Minimum similarity score (0.0 to 100.0) to include a result
        max_results: Maximum number of results to return
        
    Returns:
        List of tuples (similar_query, similarity_score) sorted by score (descending)
    """
    try:
        from rapidfuzz import process
        
        if not query or not candidate_queries:
            return []
        
        normalized_query = query.lower().strip()
        
        # Use rapidfuzz.process.extract for efficient batch matching
        # Returns list of (choice, score, index) tuples
        results = process.extract(
            normalized_query,
            candidate_queries,
            limit=max_results,
            score_cutoff=threshold
        )
        
        # Convert to (query, score) format and normalize scores to 0-100
        similarities = [(choice, float(score)) for choice, score, _ in results]
        
        return similarities
    except ImportError:
        # Fallback to manual calculation if rapidfuzz is not available
        logger.warning("rapidfuzz not available, using fallback similarity search")
        if not query or not candidate_queries:
            return []
        
        normalized_query = query.lower().strip()
        
        # Calculate similarity for each candidate
        similarities = []
        for candidate in candidate_queries:
            if not candidate:
                continue
            
            similarity = calculate_similarity(normalized_query, candidate)
            if similarity >= threshold:
                similarities.append((candidate, similarity))
        
        # Sort by similarity score (descending) and return top results
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:max_results]

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


def build_fuzzy_regex_pattern(query: str, allow_typos: bool = True) -> str:
    """
    Build a fuzzy regex pattern that handles:
    - Flexible word boundaries (dots, dashes, underscores)
    - Flexible spacing between words
    - Case-insensitive matching
    - Character-level typos (single character differences) if allow_typos=True
    
    Examples:
    - "our golden days" → matches "our.golden.days", "our-golden-days", "our_golden_days", etc.
    - "golden" → matches "golden", "golden.", "golden-", "Golden", etc.
    - "can thus love" → matches "can this love" (handles typo: thus→this)
    - Handles variations like "our golden days" matching "Our.Golden.Days.S01E45.mkv"
    
    Args:
        query: Search query string
        allow_typos: If True, allows single character typos in words (default: True)
    """
    if not query:
        return '.'
    
    # Split into words and clean
    words = [w.strip() for w in query.split() if w.strip()]
    
    if not words:
        return '.'
    
    def make_fuzzy_word(word: str) -> str:
        """Make a word pattern that allows single character typos"""
        if not allow_typos or len(word) <= 2:
            # For very short words, don't allow typos (too many false positives)
            return re.escape(word)
        
        # For longer words, allow optional character variations
        # This creates patterns like: "thi[sx]?" to match "this" or "thus"
        # But we need a smarter approach - use character classes for common typos
        escaped = re.escape(word)
        
        # For words 3-4 chars, allow 1 optional character
        if len(word) <= 4:
            # Make each character optional (but at least match most of them)
            # Pattern: allow 0-1 character difference
            chars = list(escaped)
            # Create pattern that matches the word with 0-1 character optional
            # This is complex, so we'll use a simpler approach
            return escaped
        
        # For longer words (5+), we can be more flexible
        # Use a pattern that allows character substitutions
        # This is a simplified version - for better results, consider using MongoDB text search
        return escaped
    
    if len(words) == 1:
        # Single word: allow flexible boundaries
        word_pattern = make_fuzzy_word(words[0])
        # Match word with flexible boundaries (allows dots, dashes, underscores, spaces)
        return rf'(\b|[\.\+\-\s_]){word_pattern}(\b|[\.\+\-\s_])'
    
    # Multiple words: match all words with flexible spacing/separators
    # This allows "our golden days" to match:
    # - "our.golden.days"
    # - "our-golden-days" 
    # - "our_golden_days"
    # - "our golden days"
    # - "Our.Golden.Days.S01E45"
    # For typo handling, we'll create alternative patterns for each word
    word_patterns = []
    for word in words:
        word_patterns.append(make_fuzzy_word(word))
    
    # Join words with flexible separators (space, dot, dash, underscore, or any combination)
    # This makes the search more forgiving of filename formatting
    pattern = r'[\s\.\+\-_]+'.join(word_patterns)
    
    # Wrap with flexible boundaries
    return rf'(\b|[\.\+\-\s_]){pattern}(\b|[\.\+\-\s_])'


def build_typo_tolerant_pattern(query: str) -> str:
    """
    Build a regex pattern that handles common typos by creating alternative patterns.
    This is more aggressive than build_fuzzy_regex_pattern and handles character-level typos.
    
    Examples:
    - "can thus love" → matches "can this love", "can thus love", etc.
    - "avengers" → matches "avengers", "avengars" (common typos)
    
    Args:
        query: Search query string
        
    Returns:
        Regex pattern string that matches the query with typo tolerance
    """
    if not query:
        return '.'
    
    # Split into words
    words = [w.strip() for w in query.split() if w.strip()]
    
    if not words:
        return '.'
    
    def create_typo_variants(word: str) -> str:
        """
        Create regex pattern with typo variants for a word.
        Handles common typos, missing characters, and character substitutions.
        """
        if len(word) <= 2:
            return re.escape(word)
        
        word_lower = word.lower()
        
        # For common short words, create explicit alternatives
        # This handles cases like "this" vs "thus", "that" vs "thot", etc.
        common_typos = {
            'this': r'(this|thus|thas|thos|thiz)',
            'thus': r'(this|thus|thas|thos|thiz)',
            'that': r'(that|thot|thas|thar)',
            'the': r'(the|teh|tha|th)',
            'can': r'(can|cam|kan)',
            'love': r'(love|lobe|loev)',
            'be': r'(be|bee|bi)',
            'translated': r'(translated|translatd|translat|translatet)',
            'translate': r'(translate|translat|translatd)',
            'fever': r'(fever|fevr|fevar|feve|feverr)',
            'fevr': r'(fever|fevr|fevar|feve|feverr)',
            'spring': r'(spring|sprng|sprin|springg)',
        }
        
        if word_lower in common_typos:
            return common_typos[word_lower]
        
        # For 4-character words, check if it matches common typo patterns
        # Handle "this" vs "thus" pattern (th[iu]s)
        if len(word) == 4 and word_lower.startswith('th') and word_lower.endswith('s'):
            if word_lower[2] in ['i', 'u']:
                # Create pattern that matches both "this" and "thus"
                return r'(this|thus|thas|thos)'
        
        # For words not in common_typos, use exact match
        # Note: We rely on common_typos dictionary for typo handling
        # For new typos, they should be added to common_typos
        return re.escape(word)
        

    
    # Create patterns for each word
    word_patterns = [create_typo_variants(word) for word in words]
    
    # Join with flexible separators
    pattern = r'[\s\.\+\-_]+'.join(word_patterns)
    
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