# core/utils/messages.py
"""Centralized message templates with bot settings support"""

from typing import Optional, Any

START_MSG = """<b>👋 Welcome {mention}!</b>

I'm an advanced media search bot with powerful features.

🔍 <b>Features:</b>
- Fast indexed search
- Group filter management  
- File indexing from channels
- Inline search support

Use /help to learn more about my features."""

HELP_MSG = """<b>🔍 How to Use Me</b>

<b>Basic Commands:</b>
- /start - Start the bot
- /help - Show this help
- /about - About the bot
- /stats - Bot statistics
- /plans - View premium plans
- /request_stats - View your request limits and warnings

<b>Search:</b>
- Just send me a search query
- Use @{bot_username} in any chat for inline search

<b>Filter Commands:</b>
- /add <keyword> <reply> - Add filter
- /filters - View all filters
- /del <keyword> - Delete filter
- /delall - Delete all filters

<b>Connection Commands:</b>
- /connect - Connect to a group
- /disconnect - Disconnect from group
- /connections - View connections"""

ABOUT_MSG = """<b>📚 About Me</b>

Bot Name: {bot_name}
Username: @{bot_username}
Version: 2.0.0 [Optimized]

<b>🛠 Features:</b>
- Fast indexed search
- Auto filters
- File indexing from channels
- Connection management
- Inline search support

Built with ❤️ using Pyrogram"""

NO_RESULTS_MSG = """❌ <b>No Results Found</b>

Sorry, I couldn't find any files for <b>{query}</b>.

Please check your spelling and try again."""

FILE_MSG = """📁 <b>File Name:</b> <code>{file_name}</code>
📊 <b>Size:</b> {file_size}
🎬 <b>Type:</b> {file_type}"""

AUTO_DEL_MSG = """⏱ This {content_type} will be auto-deleted after {minutes} minutes"""

BAN_MSG = """🚫 <b>You are banned from using this bot</b>

<b>Reason:</b> {reason}
<b>Banned on:</b> {date}

Contact the bot admin if you think this is a mistake."""

DAILY_LIMIT_MSG = """❌ Daily limit reached ({used}/{limit})"""

FORCE_SUB_MSG = """🔒 <b>Subscription Required</b>

You need to join our channel(s) to use this bot.
Please join the required channel(s) and try again."""


class MessageHelper:
    """Helper class to get messages with bot settings support"""
    
    @staticmethod
    def get_start_message(bot_config: Optional[Any] = None) -> str:
        """
        Get start message, checking bot config first, then falling back to default.
        
        Args:
            bot_config: Bot config object with START_MESSAGE attribute
            
        Returns:
            Start message template string
        """
        if bot_config and hasattr(bot_config, 'START_MESSAGE') and bot_config.START_MESSAGE:
            return bot_config.START_MESSAGE
        return START_MSG
    
    @staticmethod
    def get_help_message(bot_config: Optional[Any] = None) -> str:
        """
        Get help message, checking bot config first, then falling back to default.
        
        Args:
            bot_config: Bot config object with HELP_MESSAGE attribute (if defined)
            
        Returns:
            Help message template string
        """
        if bot_config and hasattr(bot_config, 'HELP_MESSAGE') and bot_config.HELP_MESSAGE:
            return bot_config.HELP_MESSAGE
        return HELP_MSG
    
    @staticmethod
    def get_about_message(bot_config: Optional[Any] = None) -> str:
        """
        Get about message, checking bot config first, then falling back to default.
        
        Args:
            bot_config: Bot config object with ABOUT_MESSAGE attribute (if defined)
            
        Returns:
            About message template string
        """
        if bot_config and hasattr(bot_config, 'ABOUT_MESSAGE') and bot_config.ABOUT_MESSAGE:
            return bot_config.ABOUT_MESSAGE
        return ABOUT_MSG
    
    @staticmethod
    def get_no_results_message(bot_config: Optional[Any] = None) -> str:
        """
        Get no results message, checking bot config first, then falling back to default.
        
        Args:
            bot_config: Bot config object with NO_RESULTS_MESSAGE attribute (if defined)
            
        Returns:
            No results message template string
        """
        if bot_config and hasattr(bot_config, 'NO_RESULTS_MESSAGE') and bot_config.NO_RESULTS_MESSAGE:
            return bot_config.NO_RESULTS_MESSAGE
        return NO_RESULTS_MSG
    
    @staticmethod
    def get_force_sub_message(bot_config: Optional[Any] = None) -> str:
        """
        Get force subscription message, checking bot config first, then falling back to default.
        
        Args:
            bot_config: Bot config object with FORCE_SUB_MESSAGE attribute (if defined)
            
        Returns:
            Force subscription message template string
        """
        if bot_config and hasattr(bot_config, 'FORCE_SUB_MESSAGE') and bot_config.FORCE_SUB_MESSAGE:
            return bot_config.FORCE_SUB_MESSAGE
        return FORCE_SUB_MSG
    
    @staticmethod
    def get_ban_message(bot_config: Optional[Any] = None) -> str:
        """
        Get ban message, checking bot config first, then falling back to default.
        
        Args:
            bot_config: Bot config object with BAN_MESSAGE attribute (if defined)
            
        Returns:
            Ban message template string
        """
        if bot_config and hasattr(bot_config, 'BAN_MESSAGE') and bot_config.BAN_MESSAGE:
            return bot_config.BAN_MESSAGE
        return BAN_MSG
    
    @staticmethod
    def get_daily_limit_message(bot_config: Optional[Any] = None) -> str:
        """
        Get daily limit message, checking bot config first, then falling back to default.
        
        Args:
            bot_config: Bot config object with DAILY_LIMIT_MESSAGE attribute (if defined)
            
        Returns:
            Daily limit message template string
        """
        if bot_config and hasattr(bot_config, 'DAILY_LIMIT_MESSAGE') and bot_config.DAILY_LIMIT_MESSAGE:
            return bot_config.DAILY_LIMIT_MESSAGE
        return DAILY_LIMIT_MSG
    
    @staticmethod
    def get_auto_delete_message(bot_config: Optional[Any] = None) -> str:
        """
        Get auto-delete message, checking bot config first, then falling back to default.
        
        Args:
            bot_config: Bot config object with AUTO_DELETE_MESSAGE attribute
            
        Returns:
            Auto-delete message template string
        """
        if bot_config and hasattr(bot_config, 'AUTO_DELETE_MESSAGE') and bot_config.AUTO_DELETE_MESSAGE:
            return bot_config.AUTO_DELETE_MESSAGE
        return AUTO_DEL_MSG