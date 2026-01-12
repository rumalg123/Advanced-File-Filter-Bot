# core/utils/messages.py
"""Centralized message templates"""


class ErrorMessages:
    """Centralized error messages for consistent user feedback"""

    # Validation errors
    INVALID_DATA = "Invalid data"
    INVALID_CALLBACK = "Invalid callback data"
    INVALID_FORMAT = "Invalid data format"
    INVALID_FILE_TYPE = "❌ Invalid file type."

    # Access/Permission errors
    ACCESS_DENIED = "❌ Access denied"
    NOT_YOUR_MESSAGE = "❌ You cannot interact with this message!"
    NOT_YOUR_SUBSCRIPTION = "❌ This subscription check is for another user. Please use your own command."
    ADMIN_RIGHTS_REQUIRED = "You need admin rights!"
    ANONYMOUS_USER = "❌ Anonymous users cannot use this bot."

    # Not found errors
    FILE_NOT_FOUND = "❌ File not found."
    FILE_NOT_IN_DB = "❌ File not found in database."
    NO_RESULTS = "❌ No results found"
    NO_FILES_FOUND = "❌ No files found."
    NO_MEDIA_FOUND = "❌ No supported media found in the message."
    ALERT_NOT_FOUND = "Alert not found"
    BATCH_NOT_FOUND = "❌ Batch not found or expired."

    # Session errors
    SESSION_EXPIRED = "❌ Session expired. Please try again."
    SEARCH_EXPIRED = "❌ Search results expired. Please search again."

    # Operation errors
    SEARCH_ERROR = "❌ An error occurred while searching. Please try again."
    SEND_FAILED = "❌ Failed to send file. Please try again."
    SEND_FILES_FAILED = "❌ Failed to send files."
    SEND_BATCH_FAILED = "❌ Failed to send batch files."
    SEND_ERROR = "❌ Error sending file. Try again."
    DELETE_FAILED = "Failed to delete"
    INVALID_LINK = "❌ Invalid link format."
    USER_NOT_FOUND = "❌ User not found. Please start the bot again."

    # Subscription errors
    JOIN_CHANNELS = "❌ You still need to join the required channel(s)!"

    # Bot interaction
    START_BOT_FIRST = "❌ Please start the bot first!"

    # Admin/User errors
    INVALID_USER_ID = "❌ Invalid user ID format."
    CHANNEL_NOT_FOUND = "❌ Channel not found in the indexing list."
    CHANNEL_ACCESS_ERROR = "❌ Error: Could not find channel."
    NO_BROADCAST_PENDING = "❌ No pending broadcast found."
    NO_BROADCAST_IN_PROGRESS = "❌ No broadcast is currently in progress."
    NOT_BROADCAST_OWNER = "❌ Only the admin who initiated this broadcast can confirm it."

    # Settings/Config errors
    SETTING_UPDATE_FAILED = "❌ Failed to update setting."
    FEATURE_NOT_AVAILABLE = "❌ This feature is not available."

    # Inline search messages
    INLINE_AUTH_ERROR = "❌ Authentication Error"
    INLINE_ACCESS_DENIED = "❌ Access Denied"
    INLINE_NO_RESULTS = "❌ No results found"
    INLINE_SEARCH_ERROR = "❌ Search Error"

    @classmethod
    def no_results_for(cls, query: str) -> str:
        """Format no results message with query"""
        return f"❌ No results found for <b>{query}</b>"

    @classmethod
    def file_error(cls, reason: str) -> str:
        """Format file error with reason"""
        return f"❌ {reason}"


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