"""
Shared file reference extraction utility.

This module provides centralized file reference extraction to eliminate
code duplication across services and handlers.
"""

import base64
import hashlib
from typing import Optional

from pyrogram.file_id import FileId
from core.utils.logger import get_logger

logger = get_logger(__name__)


class FileReferenceExtractor:
    """Utility class for extracting file references from Telegram file IDs"""
    
    @staticmethod
    def extract_file_ref(file_id: str) -> str:
        """
        Extract file reference from file_id with fallback handling.
        
        Args:
            file_id: Telegram file ID string
            
        Returns:
            str: URL-safe base64 encoded file reference or fallback hash
        """
        try:
            decoded = FileId.decode(file_id)
            file_ref = base64.urlsafe_b64encode(
                decoded.file_reference
            ).decode().rstrip("=")
            return file_ref
        except Exception as e:
            # Generate a fallback ref using hash
            logger.debug(f"File reference extraction failed for {file_id[:20]}...: {e}")
            return hashlib.md5(file_id.encode()).hexdigest()[:20]
    
    @classmethod
    def extract_safe(cls, file_id: Optional[str]) -> Optional[str]:
        """
        Safe extraction that handles None values.
        
        Args:
            file_id: Optional Telegram file ID string
            
        Returns:
            Optional[str]: Extracted file reference or None if input is None
        """
        if file_id is None:
            return None
        return cls.extract_file_ref(file_id)


# Backwards compatibility alias
extract_file_ref = FileReferenceExtractor.extract_file_ref