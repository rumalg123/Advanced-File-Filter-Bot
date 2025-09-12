"""
Robust Telegram link parsing and validation utilities
"""
import re
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass

from core.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ParsedTelegramLink:
    """Parsed Telegram link information"""
    chat_identifier: str  # Username or numeric ID
    message_id: int
    chat_id: Optional[int] = None  # Resolved numeric chat ID
    is_private_channel: bool = False  # True if /c/ link format
    original_link: str = ""


class TelegramLinkParser:
    """Robust parser for Telegram message links"""
    
    # Comprehensive regex pattern for Telegram links
    LINK_PATTERN = re.compile(
        r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/"
        r"(?:c/)?([a-zA-Z][a-zA-Z0-9_]{4,31}|\d+)/(\d+)/?(?:\?[^#]*)?(?:#.*)?$"
    )
    
    # Private channel pattern (/c/ links)
    PRIVATE_CHANNEL_PATTERN = re.compile(
        r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/"
        r"c/(\d+)/(\d+)/?(?:\?[^#]*)?(?:#.*)?$"
    )
    
    @classmethod
    def parse_link(cls, link: str) -> Optional[ParsedTelegramLink]:
        """
        Parse a Telegram message link
        
        Args:
            link: Telegram message link to parse
            
        Returns:
            ParsedTelegramLink if valid, None if invalid
        """
        if not link or not isinstance(link, str):
            logger.warning(f"Invalid link input: {link}")
            return None
            
        link = link.strip()
        if not link:
            return None
        
        # Try private channel pattern first
        private_match = cls.PRIVATE_CHANNEL_PATTERN.match(link)
        if private_match:
            chat_id_str = private_match.group(1)
            message_id_str = private_match.group(2)
            
            try:
                # Private channels need -100 prefix
                chat_id = int("-100" + chat_id_str)
                message_id = int(message_id_str)
                
                if message_id <= 0:
                    logger.warning(f"Invalid message ID in link: {message_id}")
                    return None
                
                return ParsedTelegramLink(
                    chat_identifier=chat_id_str,
                    message_id=message_id,
                    chat_id=chat_id,
                    is_private_channel=True,
                    original_link=link
                )
            except ValueError as e:
                logger.warning(f"Failed to parse private channel link: {link}, error: {e}")
                return None
        
        # Try general pattern
        match = cls.LINK_PATTERN.match(link)
        if not match:
            logger.warning(f"Link doesn't match Telegram format: {link}")
            return None
        
        chat_identifier = match.group(1)
        message_id_str = match.group(2)
        
        try:
            message_id = int(message_id_str)
            if message_id <= 0:
                logger.warning(f"Invalid message ID in link: {message_id}")
                return None
                
            # Determine if it's a numeric chat ID or username
            chat_id = None
            if chat_identifier.isdigit():
                # Numeric chat ID
                parsed_id = int(chat_identifier)
                # Check if it's a reasonable chat ID
                if parsed_id > 0:
                    chat_id = parsed_id if parsed_id < 1000000000 else -parsed_id
                else:
                    logger.warning(f"Invalid numeric chat ID: {parsed_id}")
                    return None
            else:
                # Username - validate format
                if not cls._is_valid_username(chat_identifier):
                    logger.warning(f"Invalid username format: {chat_identifier}")
                    return None
            
            return ParsedTelegramLink(
                chat_identifier=chat_identifier,
                message_id=message_id,
                chat_id=chat_id,
                is_private_channel=False,
                original_link=link
            )
            
        except ValueError as e:
            logger.warning(f"Failed to parse link: {link}, error: {e}")
            return None
    
    @classmethod
    def parse_link_pair(cls, first_link: str, second_link: str) -> Optional[Tuple[ParsedTelegramLink, ParsedTelegramLink]]:
        """
        Parse and validate a pair of Telegram links for batch operations
        
        Args:
            first_link: First message link
            second_link: Last message link
            
        Returns:
            Tuple of parsed links if valid, None if invalid
        """
        first_parsed = cls.parse_link(first_link)
        second_parsed = cls.parse_link(second_link)
        
        if not first_parsed or not second_parsed:
            return None
        
        # Validate that both links are from the same chat
        if first_parsed.chat_identifier != second_parsed.chat_identifier:
            logger.warning(f"Links are from different chats: {first_parsed.chat_identifier} vs {second_parsed.chat_identifier}")
            return None
        
        # Validate message ID order
        if first_parsed.message_id >= second_parsed.message_id:
            logger.warning(f"Invalid message order: {first_parsed.message_id} >= {second_parsed.message_id}")
            return None
        
        # Check for reasonable batch size
        message_count = second_parsed.message_id - first_parsed.message_id + 1
        if message_count > 10000:  # Reasonable limit
            logger.warning(f"Batch size too large: {message_count} messages")
            return None
        
        logger.info(f"Parsed batch links: {message_count} messages from {first_parsed.chat_identifier}")
        return first_parsed, second_parsed
    
    @staticmethod
    def _is_valid_username(username: str) -> bool:
        """Validate username format according to Telegram rules"""
        if not username or len(username) < 5 or len(username) > 32:
            return False
        
        # Username must start with letter
        if not username[0].isalpha():
            return False
        
        # Username can contain letters, digits, and underscores
        return all(c.isalnum() or c == '_' for c in username)
    
    @classmethod
    def normalize_link(cls, link: str) -> str:
        """Normalize a Telegram link to standard format"""
        parsed = cls.parse_link(link)
        if not parsed:
            return link
        
        if parsed.is_private_channel:
            return f"https://t.me/c/{parsed.chat_identifier}/{parsed.message_id}"
        else:
            return f"https://t.me/{parsed.chat_identifier}/{parsed.message_id}"


# Validation decorator for command handlers
def validate_batch_links(first_link_param: str = "first_link", second_link_param: str = "second_link"):
    """
    Decorator to validate batch link parameters in command handlers
    
    Args:
        first_link_param: Name of first link parameter
        second_link_param: Name of second link parameter
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Extract links from kwargs or positional args
            first_link = kwargs.get(first_link_param)
            second_link = kwargs.get(second_link_param)
            
            # Try to get from message if not in kwargs
            if not first_link or not second_link:
                if len(args) >= 3 and hasattr(args[2], 'text'):  # Assume message is 3rd arg
                    parts = args[2].text.strip().split()
                    if len(parts) >= 3:
                        first_link = parts[1]
                        second_link = parts[2]
            
            if not first_link or not second_link:
                return await func(*args, **kwargs)
            
            # Parse and validate
            parsed_links = TelegramLinkParser.parse_link_pair(first_link, second_link)
            if not parsed_links:
                # Invalid links - let the handler decide how to respond
                return await func(*args, **kwargs)
            
            # Add parsed links to kwargs
            kwargs['_parsed_links'] = parsed_links
            return await func(*args, **kwargs)
        return wrapper
    return decorator