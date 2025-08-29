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
            use_original_for_batch: bool = False,
            is_batch: bool = False,
            disable_notification: bool = False,
            auto_delete_minutes: Optional[int] = None,
            auto_delete_message: Optional[str] = None  # Add this parameter
    ) -> Optional[str]:
        """
        Format caption based on configuration

        Args:
            file: MediaFile object
            custom_caption: CUSTOM_FILE_CAPTION from env
            batch_caption: BATCH_FILE_CAPTION from env
            keep_original: KEEP_ORIGINAL_CAPTION from env
            use_original_for_batch: USE_ORIGINAL_CAPTION_FOR_BATCH from env
            is_batch: Whether this is a batch file (from /batch or /pbatch command)
            disable_notification: Whether to disable notification
            auto_delete_minutes: Auto-delete time in minutes
            auto_delete_message: Custom auto-delete message template

        Returns:
            Formatted caption or None
        """
        caption = None

        # For batch files (from /batch or /pbatch command), always use batch caption if available
        if is_batch:
            if use_original_for_batch and file.caption:
                caption = file.caption
            elif batch_caption:
                caption = CaptionFormatter._format_template(batch_caption, file)
            elif keep_original and file.caption:
                caption = file.caption

        # For regular files
        elif not is_batch:
            if custom_caption:
                caption = CaptionFormatter._format_template(custom_caption, file)
            elif keep_original and file.caption:
                caption = file.caption

        # Add auto-delete notification if needed
        if caption and auto_delete_minutes and not disable_notification:
            # Use custom message if provided, otherwise use default
            if auto_delete_message:
                delete_msg = auto_delete_message.format(
                    content_type='file',
                    minutes=auto_delete_minutes
                )
            else:
                delete_msg = AUTO_DEL_MSG.format(
                    content_type='file',
                    minutes=auto_delete_minutes
                )
            caption += f"\n\n{delete_msg}"
        elif not caption and auto_delete_minutes and not disable_notification:
            # If no caption but auto-delete is enabled, create minimal caption
            if auto_delete_message:
                caption = auto_delete_message.format(
                    content_type='file',
                    minutes=auto_delete_minutes
                )
            else:
                caption = AUTO_DEL_MSG.format(
                    content_type='file',
                    minutes=auto_delete_minutes
                )

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
            return template

    @staticmethod
    def get_parse_mode() -> enums.ParseMode:
        """Get parse mode for captions"""
        return enums.ParseMode.HTML