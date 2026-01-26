# core/utils/media_factory.py
"""Factory for creating MediaFile objects from Pyrogram media"""
from typing import Optional, Any, Union

from pyrogram import enums
from pyrogram.types import Message

from repositories.media import MediaFile, FileType
from core.utils.helpers import extract_file_ref, parse_media_metadata
from core.utils.validators import normalize_filename_for_search
from core.utils.file_type import get_file_type_from_pyrogram, get_file_type_from_string


class MediaFileFactory:
    """Factory for creating MediaFile objects from various sources"""

    @staticmethod
    def get_file_type_from_pyrogram(media_type: enums.MessageMediaType) -> FileType:
        """
        Convert Pyrogram MessageMediaType to FileType enum.
        
        Delegates to core.utils.file_type.get_file_type_from_pyrogram().
        
        Args:
            media_type: Pyrogram MessageMediaType enum value
            
        Returns:
            FileType enum value, defaults to DOCUMENT if unknown
        """
        return get_file_type_from_pyrogram(media_type)

    @staticmethod
    def get_file_type_from_string(media_type: str) -> FileType:
        """
        Convert string media type to FileType enum.
        
        Delegates to core.utils.file_type.get_file_type_from_string().
        
        Args:
            media_type: String like 'video', 'audio', 'document'
            
        Returns:
            FileType enum value, defaults to DOCUMENT if unknown
        """
        return get_file_type_from_string(media_type)

    @staticmethod
    def from_pyrogram_media(
        media: Any,
        message: Message,
        file_type: Optional[Union[FileType, enums.MessageMediaType, str]] = None,
        file_unique_id: Optional[str] = None
    ) -> MediaFile:
        """
        Create MediaFile from Pyrogram media object.
        
        This method handles all the common logic:
        - Extracting file metadata
        - Normalizing filename
        - Parsing season/episode/resolution
        - Determining resolution from dimensions or parsed value
        
        Args:
            media: Pyrogram media object (document, video, audio, etc.)
            message: Pyrogram Message object containing the media
            file_type: Optional file type. Can be:
                - FileType enum (used as-is)
                - enums.MessageMediaType (converted to FileType)
                - str like 'video', 'audio' (converted to FileType)
                - None (will try to infer from media object)
            file_unique_id: Optional file_unique_id. If not provided, uses media.file_unique_id
            
        Returns:
            MediaFile instance with all fields populated
            
        Example:
            >>> media = message.document
            >>> media_file = MediaFileFactory.from_pyrogram_media(
            ...     media=media,
            ...     message=message,
            ...     file_type=enums.MessageMediaType.DOCUMENT
            ... )
        """
        # Determine file_unique_id
        identifier = file_unique_id if file_unique_id is not None else media.file_unique_id
        
        # Determine file_type
        if file_type is None:
            # Try to infer from message.media if available
            if hasattr(message, 'media') and message.media:
                file_type_enum = get_file_type_from_pyrogram(message.media)
            else:
                file_type_enum = FileType.DOCUMENT
        elif isinstance(file_type, FileType):
            file_type_enum = file_type
        elif isinstance(file_type, enums.MessageMediaType):
            file_type_enum = get_file_type_from_pyrogram(file_type)
        elif isinstance(file_type, str):
            file_type_enum = get_file_type_from_string(file_type)
        else:
            file_type_enum = FileType.DOCUMENT

        # Extract and normalize filename
        raw_file_name = getattr(media, 'file_name', None)
        if not raw_file_name:
            # Generate fallback filename
            file_type_str = file_type_enum.value if hasattr(file_type_enum, 'value') else 'file'
            raw_file_name = f'{file_type_str}_{media.file_unique_id}'
        
        normalized_name = normalize_filename_for_search(raw_file_name)

        # Extract caption
        caption_html = None
        if message.caption:
            caption_html = message.caption.html if hasattr(message.caption, 'html') else str(message.caption)
        elif hasattr(message, 'reply_to_message') and message.reply_to_message:
            if message.reply_to_message.caption:
                caption_html = message.reply_to_message.caption.html if hasattr(message.reply_to_message.caption, 'html') else str(message.reply_to_message.caption)

        # Parse metadata (season, episode, resolution)
        season, episode, parsed_resolution = parse_media_metadata(raw_file_name, caption_html)

        # Determine resolution (prefer real dimensions, fallback to parsed)
        resolution = None
        width = getattr(media, 'width', None)
        height = getattr(media, 'height', None)
        if width and height:
            resolution = f"{width}x{height}"
        elif parsed_resolution:
            resolution = parsed_resolution

        # Extract file reference
        file_ref = extract_file_ref(media.file_id)

        # Create and return MediaFile
        return MediaFile(
            file_id=media.file_id,
            file_unique_id=identifier,
            file_ref=file_ref,
            file_name=normalized_name,
            file_size=media.file_size,
            file_type=file_type_enum,
            resolution=resolution,
            episode=episode,
            season=season,
            mime_type=getattr(media, 'mime_type', None),
            caption=caption_html
        )
