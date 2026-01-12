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
    MULTI_DB_NOT_ENABLED = "❌ Multi-database mode is not enabled."
    SESSION_NOT_AVAILABLE = "❌ Session management not available."

    # Inline search messages
    INLINE_AUTH_ERROR = "❌ Authentication Error"
    INLINE_ACCESS_DENIED = "❌ Access Denied"
    INLINE_NO_RESULTS = "❌ No results found"
    INLINE_SEARCH_ERROR = "❌ Search Error"
    INLINE_BANNED = "🚫 You are banned"
    INLINE_PREMIUM_MODE = "⚠️ Inline mode disabled (Premium mode active)"
    INLINE_JOIN_CHANNEL = "🔒 Join channel to use bot"

    # Indexing messages
    INDEXING_IN_PROGRESS = "Another indexing is in progress"
    BOT_SHUTTING_DOWN = "Bot is shutting down"

    # Indexing errors
    FORWARD_FROM_CHANNEL = "❌ Please forward from a channel, not a group"
    MESSAGE_NOT_FOUND = "❌ The specified message doesn't exist"
    CHANNEL_ADMIN_REQUIRED = "❌ Error accessing the channel. Make sure I'm an admin in the channel."
    BOT_ACCESS_REQUIRED = (
        "❌ <b>Bot Access Required</b>\n"
        "I cannot access this channel. Please:\n"
        "1. Add me to the channel as an admin\n"
        "2. Make sure the channel is public OR\n"
        "3. Ensure I have proper permissions\n"
        "Then try forwarding the message again."
    )
    INDEX_REQUEST_FAILED = "❌ Failed to create index request"
    GENERIC_ERROR = "❌ An error occurred. Please try again."
    SKIP_POSITIVE = "❌ Skip number must be positive"
    INVALID_NUMBER = "❌ Invalid number format"

    # Deletion errors
    DELETION_CANCELLED = "❌ Deletion cancelled."
    DELETION_EXPIRED = "❌ Deletion request expired. Please try again."

    # Stats errors
    STATS_ERROR = "❌ Error retrieving statistics. Please try again later."

    # Broadcast errors
    BROADCAST_CANCELLED = "❌ Broadcast cancelled."
    NO_LOG_FILE = "❌ No log file found."

    # Database errors
    NO_DB_STATS = "❌ No database statistics available."
    INVALID_DB_NUMBER = "❌ Invalid database number. Please provide a valid number."
    DB_SWITCH_FAILED = "❌ Failed to switch database."
    MULTI_DB_NOT_CONFIGURED = "❌ Multi-database mode is not properly configured."
    CALLBACK_ERROR = "❌ Error processing request"

    # Settings errors
    SETTING_NOT_FOUND = "❌ Setting not found!"
    NO_EDIT_SESSION = "❌ No active edit session to cancel."

    # Channel errors
    INVALID_USERNAME = "❌ Invalid username. Please check and try again."
    CHANNEL_ADD_FAILED = "❌ Failed to add channel. Please try again."
    CHANNEL_REMOVE_FAILED = "❌ Failed to remove channel. Please try again."
    CHANNEL_STATUS_FAILED = "❌ Failed to update channel status."

    # Filter errors
    ANONYMOUS_ADMIN_USE_PM = "You are anonymous admin. Use /connect in PM"
    ADMIN_REQUIRED_ADD_FILTER = "You need to be an admin to add filters!"
    ADMIN_REQUIRED_VIEW_FILTER = "You need to be an admin to view filters!"
    ADMIN_REQUIRED_DELETE_FILTER = "You need to be an admin to delete filters!"
    FILTER_ADD_FAILED = "Failed to add filter!"
    FILTER_REMOVE_ALL_FAILED = "Couldn't remove all filters from group!"
    OWNER_OR_AUTH_REQUIRED = "You need to be Group Owner or an Auth User to do that!"
    ALERT_PARSE_ERROR = "Error parsing alert data"
    NOT_CONNECTED_TO_GROUPS = "I'm not connected to any groups!\nCheck /connections or connect to any groups"
    OWNER_ONLY_DELETE_ALL = "Only group owner or bot admins can delete all filters!"

    # Filestore errors
    REPLY_TO_MESSAGE = "Reply to a message to get a shareable link."
    LINK_GENERATE_FAILED = "Failed to generate link. Make sure you replied to a supported media."

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