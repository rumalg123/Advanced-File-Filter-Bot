# core/utils/media_extractor.py
"""Utilities for extracting media objects from Pyrogram messages"""
from typing import Optional, Tuple, Dict, Any, TYPE_CHECKING

from pyrogram import enums

if TYPE_CHECKING:
    from pyrogram.types import Message as PyrogramMessage


def extract_media_from_message(
    message: 'PyrogramMessage',
    supported_types: Optional[list] = None
) -> Optional[Tuple[Any, str, enums.MessageMediaType]]:
    """
    Extract media object, type string, and MessageMediaType from a message.
    
    This is the primary method for extracting media when you need the media object
    itself (e.g., for use with MediaFileFactory).
    
    Args:
        message: Pyrogram Message object
        supported_types: Optional list of media type strings to check.
                        Defaults to ["document", "video", "audio"].
                        Can include: "document", "video", "audio", "photo", 
                        "animation", "voice", "video_note", "sticker"
    
    Returns:
        Tuple of (media_object, media_type_string, MessageMediaType) if found,
        None otherwise
        
    Example:
        >>> media, media_type_str, media_type_enum = extract_media_from_message(message)
        >>> if media:
        ...     media_file = MediaFileFactory.from_pyrogram_media(
        ...         media=media,
        ...         message=message,
        ...         file_type=media_type_str
        ...     )
    """
    if not message or not hasattr(message, 'media'):
        return None
    
    # Default supported types for file indexing
    if supported_types is None:
        supported_types = ["document", "video", "audio"]
    
    # Map string types to MessageMediaType and attribute names
    type_mapping = {
        "document": (enums.MessageMediaType.DOCUMENT, "document"),
        "video": (enums.MessageMediaType.VIDEO, "video"),
        "audio": (enums.MessageMediaType.AUDIO, "audio"),
        "photo": (enums.MessageMediaType.PHOTO, "photo"),
        "animation": (enums.MessageMediaType.ANIMATION, "animation"),
        "voice": (enums.MessageMediaType.VOICE, "voice"),
        "video_note": (enums.MessageMediaType.VIDEO_NOTE, "video_note"),
        "sticker": (enums.MessageMediaType.STICKER, "sticker"),
    }
    
    # Check if message has media attribute
    if hasattr(message, 'media') and message.media:
        # Use message.media if it's a MessageMediaType
        if isinstance(message.media, enums.MessageMediaType):
            media_type_enum = message.media
            # Get the attribute name from the enum value
            attr_name = media_type_enum.value
            media = getattr(message, attr_name, None)
            if media:
                # Find the string type name
                for type_str, (enum_val, _) in type_mapping.items():
                    if enum_val == media_type_enum:
                        return (media, type_str, media_type_enum)
        else:
            # Fallback: try to get media from message.media.value
            try:
                attr_name = str(message.media.value) if hasattr(message.media, 'value') else str(message.media)
                media = getattr(message, attr_name, None)
                if media:
                    # Try to find matching enum
                    for type_str, (enum_val, _) in type_mapping.items():
                        if attr_name == type_str:
                            return (media, type_str, enum_val)
            except (AttributeError, TypeError):
                pass
    
    # Fallback: iterate through supported types
    for media_type_str in supported_types:
        if media_type_str in type_mapping:
            media_type_enum, attr_name = type_mapping[media_type_str]
            media = getattr(message, attr_name, None)
            if media:
                return (media, media_type_str, media_type_enum)
    
    return None


def extract_media_by_type(
    message: 'PyrogramMessage',
    media_type: enums.MessageMediaType
) -> Optional[Any]:
    """
    Extract media object by MessageMediaType enum.
    
    Args:
        message: Pyrogram Message object
        media_type: MessageMediaType enum value
        
    Returns:
        Media object if found, None otherwise
        
    Example:
        >>> if message.media == enums.MessageMediaType.DOCUMENT:
        ...     media = extract_media_by_type(message, enums.MessageMediaType.DOCUMENT)
    """
    if not message or not hasattr(message, 'media'):
        return None
    
    # Get attribute name from enum value
    attr_name = media_type.value
    return getattr(message, attr_name, None)


def extract_media_info_dict(
    message: 'PyrogramMessage',
    supported_types: Optional[list] = None
) -> Optional[Dict[str, Any]]:
    """
    Extract media information as a dictionary (backward compatible with extract_file_info).
    
    This method provides the same interface as the existing extract_file_info()
    but uses the unified extraction logic.
    
    Args:
        message: Pyrogram Message object
        supported_types: Optional list of media type strings to check.
                        Defaults to all supported types.
    
    Returns:
        Dictionary with file info or None if no media found
    """
    if supported_types is None:
        supported_types = [
            "document", "video", "audio", "photo", "animation",
            "voice", "video_note", "sticker"
        ]
    
    result = extract_media_from_message(message, supported_types)
    if not result:
        return None
    
    media, media_type_str, _ = result
    
    file_name = getattr(media, 'file_name', None)
    if not file_name:
        # Generate a descriptive name
        file_name = f"{media_type_str.title()}_{media.file_unique_id[:10]}"
    
    return {
        'file_unique_id': media.file_unique_id,
        'file_id': media.file_id,
        'file_name': file_name,
        'file_size': getattr(media, 'file_size', 0),
        'media_type': media_type_str,
        'mime_type': getattr(media, 'mime_type', None),
        'message': message
    }
