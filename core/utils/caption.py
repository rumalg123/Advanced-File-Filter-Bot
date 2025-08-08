# core/utils/caption.py
from typing import Optional
from pyrogram import enums

from core.utils.helpers import format_file_size
from core.utils.messages import AUTO_DEL_MSG
from repositories.media import MediaFile
from core.utils.logger import get_logger

logger = get_logger(__name__)


class CaptionFormatter:
    """Centralized caption formatting utility"""

    @staticmethod
    def format_file_caption(
            file: MediaFile,
            custom_caption: Optional[str] = None,
            batch_caption: Optional[str] = None,
            keep_original: bool = False,
            is_batch: bool = False,
            disable_notification: bool = False,
            auto_delete_minutes: Optional[int] = None
    ) -> Optional[str]:
        """
        Format caption based on configuration

        Args:
            file: MediaFile object
            custom_caption: CUSTOM_FILE_CAPTION from env
            batch_caption: BATCH_FILE_CAPTION from env
            keep_original: KEEP_ORIGINAL_CAPTION from env
            is_batch: Whether this is a batch file (from /batch or /pbatch command)
            disable_notification: Whether to disable notification
            auto_delete_minutes: Auto-delete time in minutes

        Returns:
            Formatted caption or None
        """
        caption = None

        # For batch files (from /batch or /pbatch command), always use batch caption if available
        if is_batch and batch_caption:
            caption = CaptionFormatter._format_template(batch_caption, file)

        # For regular files (including files sent via "Send All")
        elif not is_batch:
            if custom_caption:
                # If custom caption is set, always use it
                caption = CaptionFormatter._format_template(custom_caption, file)
            elif keep_original and file.caption:
                # If only keep_original is set, use original caption
                caption = file.caption
            # If neither is set, caption remains None

        # Add auto-delete notification if needed
        if caption and auto_delete_minutes and not disable_notification:
            caption += f"\n\n{AUTO_DEL_MSG.format(content_type='file', minutes=auto_delete_minutes)}"
        elif not caption and auto_delete_minutes and not disable_notification:
            # If no caption but auto-delete is enabled, create minimal caption
            caption = AUTO_DEL_MSG.format(content_type='file', minutes=auto_delete_minutes)

        return caption

    @staticmethod
    def _format_template(template: str, file: MediaFile) -> str:
        """Format template with placeholders"""
        try:
            return template.format(
                filename=file.file_name,
                size=format_file_size(file.file_size)
            )
        except Exception as e:
            logger.error(f"Error formatting caption template: {e}")
            # Return template as-is if formatting fails
            return template



    @staticmethod
    def get_parse_mode() -> enums.ParseMode:
        """Get parse mode for captions"""
        return enums.ParseMode.HTML