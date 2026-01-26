# core/utils/file_type.py
"""Utilities for converting between different file type representations"""
from typing import Optional

from pyrogram import enums

from repositories.media import FileType


def get_file_type_from_pyrogram(media_type: enums.MessageMediaType) -> FileType:
    """
    Convert Pyrogram MessageMediaType to FileType enum.
    
    Args:
        media_type: Pyrogram MessageMediaType enum value
        
    Returns:
        FileType enum value, defaults to DOCUMENT if unknown
        
    Example:
        >>> from pyrogram import enums
        >>> file_type = get_file_type_from_pyrogram(enums.MessageMediaType.VIDEO)
        >>> assert file_type == FileType.VIDEO
    """
    mapping = {
        enums.MessageMediaType.VIDEO: FileType.VIDEO,
        enums.MessageMediaType.AUDIO: FileType.AUDIO,
        enums.MessageMediaType.DOCUMENT: FileType.DOCUMENT,
        enums.MessageMediaType.PHOTO: FileType.PHOTO,
        enums.MessageMediaType.ANIMATION: FileType.ANIMATION,
    }
    return mapping.get(media_type, FileType.DOCUMENT)


def get_file_type_from_string(media_type: str) -> FileType:
    """
    Convert string media type to FileType enum.
    
    Supports both lowercase and mixed case strings.
    
    Args:
        media_type: String like 'video', 'audio', 'document', 'VIDEO', etc.
        
    Returns:
        FileType enum value, defaults to DOCUMENT if unknown
        
    Example:
        >>> file_type = get_file_type_from_string('video')
        >>> assert file_type == FileType.VIDEO
        >>> file_type = get_file_type_from_string('VIDEO')
        >>> assert file_type == FileType.VIDEO
    """
    mapping = {
        'video': FileType.VIDEO,
        'audio': FileType.AUDIO,
        'document': FileType.DOCUMENT,
        'photo': FileType.PHOTO,
        'animation': FileType.ANIMATION,
    }
    return mapping.get(media_type.lower(), FileType.DOCUMENT)


def get_file_type_from_value(value: str) -> Optional[FileType]:
    """
    Convert FileType enum value string to FileType enum.
    
    This is useful when you have a string that matches FileType enum values
    (e.g., from database or API responses).
    
    Args:
        value: String matching FileType enum value (e.g., 'video', 'audio', 'document')
        
    Returns:
        FileType enum value if valid, None otherwise
        
    Example:
        >>> file_type = get_file_type_from_value('video')
        >>> assert file_type == FileType.VIDEO
        >>> file_type = get_file_type_from_value('invalid')
        >>> assert file_type is None
    """
    try:
        return FileType(value.lower())
    except (ValueError, AttributeError):
        return None
