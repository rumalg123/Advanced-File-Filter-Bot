# core/utils/error_formatter.py
"""Utilities for formatting error and status messages consistently"""
from typing import Optional


class ErrorMessageFormatter:
    """Formatter for consistent error and status messages"""

    @staticmethod
    def format_error(
        message: str,
        title: Optional[str] = None,
        include_prefix: bool = True
    ) -> str:
        """
        Format error messages consistently.
        
        Args:
            message: Error message text
            title: Optional title (defaults to "Error")
            include_prefix: Whether to include emoji prefix (default: True)
            
        Returns:
            Formatted error message with HTML
            
        Example:
            >>> ErrorMessageFormatter.format_error("File not found")
            '❌ <b>Error:</b> File not found'
            >>> ErrorMessageFormatter.format_error("Invalid input", title="Validation")
            '❌ <b>Validation:</b> Invalid input'
        """
        prefix = "❌ " if include_prefix else ""
        title_text = title if title else "Error"
        return f"{prefix}<b>{title_text}:</b> {message}"

    @staticmethod
    def format_failed(
        message: str,
        action: Optional[str] = None,
        include_prefix: bool = True
    ) -> str:
        """
        Format failure messages consistently.
        
        Args:
            message: Failure message text
            action: Optional action that failed (e.g., "to send file")
            include_prefix: Whether to include emoji prefix (default: True)
            
        Returns:
            Formatted failure message with HTML
            
        Example:
            >>> ErrorMessageFormatter.format_failed("to send file")
            '❌ <b>Failed</b> to send file'
            >>> ErrorMessageFormatter.format_failed("Operation", action="to process")
            '❌ <b>Failed</b> to process Operation'
        """
        prefix = "❌ " if include_prefix else ""
        if action:
            return f"{prefix}<b>Failed</b> {action}: {message}"
        return f"{prefix}<b>Failed:</b> {message}"

    @staticmethod
    def format_success(
        message: str,
        title: Optional[str] = None,
        include_prefix: bool = True
    ) -> str:
        """
        Format success messages consistently.
        
        Args:
            message: Success message text
            title: Optional title (defaults to "Success")
            include_prefix: Whether to include emoji prefix (default: True)
            
        Returns:
            Formatted success message with HTML
            
        Example:
            >>> ErrorMessageFormatter.format_success("File sent")
            '✅ <b>Success:</b> File sent'
        """
        prefix = "✅ " if include_prefix else ""
        title_text = title if title else "Success"
        return f"{prefix}<b>{title_text}:</b> {message}"

    @staticmethod
    def format_warning(
        message: str,
        title: Optional[str] = None,
        include_prefix: bool = True
    ) -> str:
        """
        Format warning messages consistently.
        
        Args:
            message: Warning message text
            title: Optional title (defaults to "Warning")
            include_prefix: Whether to include emoji prefix (default: True)
            
        Returns:
            Formatted warning message with HTML
            
        Example:
            >>> ErrorMessageFormatter.format_warning("Rate limit approaching")
            '⚠️ <b>Warning:</b> Rate limit approaching'
        """
        prefix = "⚠️ " if include_prefix else ""
        title_text = title if title else "Warning"
        return f"{prefix}<b>{title_text}:</b> {message}"

    @staticmethod
    def format_info(
        message: str,
        title: Optional[str] = None,
        include_prefix: bool = True
    ) -> str:
        """
        Format info messages consistently.
        
        Args:
            message: Info message text
            title: Optional title (defaults to "Info")
            include_prefix: Whether to include emoji prefix (default: True)
            
        Returns:
            Formatted info message with HTML
            
        Example:
            >>> ErrorMessageFormatter.format_info("Processing request")
            'ℹ️ <b>Info:</b> Processing request'
        """
        prefix = "ℹ️ " if include_prefix else ""
        title_text = title if title else "Info"
        return f"{prefix}<b>{title_text}:</b> {message}"

    @staticmethod
    def format_access_denied(
        reason: Optional[str] = None,
        include_prefix: bool = True
    ) -> str:
        """
        Format access denied messages consistently.
        
        Args:
            reason: Optional reason for denial
            include_prefix: Whether to include emoji prefix (default: True)
            
        Returns:
            Formatted access denied message with HTML
            
        Example:
            >>> ErrorMessageFormatter.format_access_denied("User banned")
            '❌ <b>Access Denied:</b> User banned'
        """
        prefix = "❌ " if include_prefix else ""
        message = f"{prefix}<b>Access Denied:</b>"
        if reason:
            message += f" {reason}"
        return message

    @staticmethod
    def format_not_found(
        item: str,
        include_prefix: bool = True
    ) -> str:
        """
        Format "not found" messages consistently.
        
        Args:
            item: Item that was not found (e.g., "File", "User")
            include_prefix: Whether to include emoji prefix (default: True)
            
        Returns:
            Formatted not found message with HTML
            
        Example:
            >>> ErrorMessageFormatter.format_not_found("File")
            '❌ <b>File</b> not found'
        """
        prefix = "❌ " if include_prefix else ""
        return f"{prefix}<b>{item}</b> not found"

    @staticmethod
    def format_invalid(
        item: str,
        details: Optional[str] = None,
        include_prefix: bool = True
    ) -> str:
        """
        Format "invalid" messages consistently.
        
        Args:
            item: Item that is invalid (e.g., "link format", "user ID")
            details: Optional additional details
            include_prefix: Whether to include emoji prefix (default: True)
            
        Returns:
            Formatted invalid message with HTML
            
        Example:
            >>> ErrorMessageFormatter.format_invalid("link format")
            '❌ <b>Invalid</b> link format'
        """
        prefix = "❌ " if include_prefix else ""
        message = f"{prefix}<b>Invalid</b> {item}"
        if details:
            message += f": {details}"
        return message
