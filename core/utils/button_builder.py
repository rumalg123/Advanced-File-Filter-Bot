# core/utils/button_builder.py
"""Utilities for building inline keyboard buttons with consistent formatting"""
from typing import List, Optional

from pyrogram.types import InlineKeyboardButton

from core.utils.file_emoji import get_file_emoji
from core.utils.helpers import format_file_size
from repositories.media import MediaFile

# Maximum filename length for button text
MAX_FILENAME_LENGTH = 50


class ButtonBuilder:
    """Builder for creating standardized inline keyboard buttons"""

    @staticmethod
    def file_button(
        file: MediaFile,
        user_id: Optional[int] = None,
        is_private: bool = True,
        max_filename_length: int = MAX_FILENAME_LENGTH
    ) -> InlineKeyboardButton:
        """
        Create a standardized file button with emoji, size, and filename.
        
        Args:
            file: MediaFile object
            user_id: User ID for non-private chats (for callback data)
            is_private: Whether the chat is private
            max_filename_length: Maximum length for filename display
            
        Returns:
            InlineKeyboardButton for the file
            
        Example:
            >>> button = ButtonBuilder.file_button(file, user_id=123, is_private=False)
            >>> # Creates: "1.5 MB 🎬 filename.mkv" with callback "file#unique_id#123"
        """
        # Get file identifier (prefer file_unique_id, fallback to file_ref)
        # Note: file_id is not used as it's not unique across sessions
        file_identifier = file.file_unique_id if file.file_unique_id else (file.file_ref if file.file_ref else None)
        if not file_identifier:
            raise ValueError("MediaFile must have either file_unique_id or file_ref")
        
        # Build callback data
        if is_private:
            callback_data = f"file#{file_identifier}"
        else:
            if user_id is None:
                raise ValueError("user_id is required for non-private chats")
            callback_data = f"file#{file_identifier}#{user_id}"
        
        # Get file emoji
        file_emoji = get_file_emoji(file.file_type, file.file_name, file.mime_type)
        
        # Format file size
        size_text = format_file_size(file.file_size)
        
        # Truncate filename if needed
        filename_display = file.file_name
        if len(filename_display) > max_filename_length:
            filename_display = filename_display[:max_filename_length] + "..."
        
        # Build button text: "{size} {emoji} {filename}"
        button_text = f"{size_text} {file_emoji} {filename_display}"
        
        return InlineKeyboardButton(
            text=button_text,
            callback_data=callback_data
        )

    @staticmethod
    def send_all_button(
        file_count: int,
        search_key: str,
        user_id: Optional[int] = None,
        is_private: bool = True
    ) -> InlineKeyboardButton:
        """
        Create a "Send All Files" button.
        
        Args:
            file_count: Number of files to send
            search_key: Search session key for callback
            user_id: User ID for non-private chats (for callback data)
            is_private: Whether the chat is private
            
        Returns:
            InlineKeyboardButton for sending all files
            
        Example:
            >>> button = ButtonBuilder.send_all_button(10, "search_abc123", user_id=123, is_private=False)
            >>> # Creates: "📤 Send All Files (10)" with callback "sendall#search_abc123#123"
        """
        # Build callback data
        if is_private:
            callback_data = f"sendall#{search_key}"
        else:
            if user_id is None:
                raise ValueError("user_id is required for non-private chats")
            callback_data = f"sendall#{search_key}#{user_id}"
        
        button_text = f"📤 Send All Files ({file_count})"
        
        return InlineKeyboardButton(
            text=button_text,
            callback_data=callback_data
        )

    @staticmethod
    def file_buttons_row(
        files: List[MediaFile],
        user_id: Optional[int] = None,
        is_private: bool = True,
        max_filename_length: int = MAX_FILENAME_LENGTH
    ) -> List[List[InlineKeyboardButton]]:
        """
        Create a list of button rows, one button per file.
        
        Args:
            files: List of MediaFile objects
            user_id: User ID for non-private chats
            is_private: Whether the chat is private
            max_filename_length: Maximum length for filename display
            
        Returns:
            List of button rows, each containing one file button
            
        Example:
            >>> rows = ButtonBuilder.file_buttons_row([file1, file2], user_id=123, is_private=False)
            >>> # Returns: [[button1], [button2]]
        """
        buttons = []
        for file in files:
            button = ButtonBuilder.file_button(
                file=file,
                user_id=user_id,
                is_private=is_private,
                max_filename_length=max_filename_length
            )
            buttons.append([button])
        
        return buttons

    @staticmethod
    def action_button(
        text: str,
        callback_data: Optional[str] = None,
        url: Optional[str] = None
    ) -> InlineKeyboardButton:
        """
        Create a generic action button.
        
        Args:
            text: Button text
            callback_data: Callback data (for callback buttons)
            url: URL (for URL buttons)
            
        Returns:
            InlineKeyboardButton
            
        Raises:
            ValueError: If neither callback_data nor url is provided
            
        Example:
            >>> button = ButtonBuilder.action_button("📚 Help", callback_data="help")
            >>> button = ButtonBuilder.action_button("➕ Add to Group", url="https://t.me/bot?startgroup=true")
        """
        if callback_data:
            return InlineKeyboardButton(text=text, callback_data=callback_data)
        elif url:
            return InlineKeyboardButton(text=text, url=url)
        else:
            raise ValueError("Either callback_data or url must be provided")

    @staticmethod
    def row(*buttons: InlineKeyboardButton) -> List[InlineKeyboardButton]:
        """
        Create a button row from multiple buttons.
        
        Args:
            *buttons: Variable number of InlineKeyboardButton objects
            
        Returns:
            List of buttons for a single row
            
        Example:
            >>> row = ButtonBuilder.row(button1, button2, button3)
            >>> # Returns: [button1, button2, button3]
        """
        return list(buttons)
