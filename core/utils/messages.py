# core/utils/messages.py
"""Centralized message templates"""

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