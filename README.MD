# 🎬 Telegram Media Search Bot

A powerful and feature-rich Telegram bot for searching and managing media files with advanced features like auto-indexing, premium subscriptions, rate limiting, distributed caching, and comprehensive bot settings management.

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![Pyrogram](https://img.shields.io/badge/Pyrogram-Pyrofork-orange)
![MongoDB](https://img.shields.io/badge/MongoDB-5.0%2B-green)
![Redis](https://img.shields.io/badge/Redis-6.0%2B-red)
![License](https://img.shields.io/badge/License-MIT-yellow)

## ✨ Key Features

### 🚀 Core Features
- **⚡ Lightning-Fast Search**: Indexed search across millions of files with MongoDB text search
- **📁 Multiple File Types**: Support for videos, audio, documents, and animations with file-type specific emojis
- **🗃️ Multi-Database Support**: Automatic scaling with multiple MongoDB databases and size limits
- **🔄 Auto-Indexing**: Automatically index files from configured channels
- **💎 Premium System**: Tiered access with configurable daily limits for free users
- **🛡️ Rate Limiting**: Comprehensive rate limiting for search, file requests, inline queries, and broadcasts
- **💾 Redis Caching**: Improved performance with distributed caching and TTL management
- **🚀 uvloop Support**: Enhanced performance on Linux with uvloop event loop
- **🎯 Smart File Emojis**: File-type specific emojis (🎬 for videos, 📦 for archives, 💬 for subtitles, etc.)
- **💡 Smart Recommendations**: Personalized file and search recommendations based on user behavior
- **📊 Search History**: Track and display most searched keywords with keyboard shortcuts
- **🔍 Fuzzy Matching**: Typo-tolerant search with "Did you mean?" suggestions

### 🎯 Advanced Features
- **🔗 Connection Management**: Connect groups to manage filters privately
- **🎭 Custom Filters**: Create custom keyword-based auto-replies with buttons and alerts
- **📤 File Store**: Generate shareable and protected links for files
- **📊 Enhanced Broadcasting**: Send messages to all users with HTML formatting, preview, and confirmation system
- **🔐 Force Subscription**: Require users to join channels/groups
- **🗑️ Auto-Delete**: Automatically delete messages after specified time
- **📱 Inline Search**: Search files directly from any chat
- **📝 Content Requests**: Users can request content via #request in support group
- **🔍 Duplicate Detection**: Advanced duplicate detection using file unique id
- **⚙️ Bot Settings**: Comprehensive settings management via commands
- **🔄 Auto-Update System**: Secure automatic updates with backup and rollback capabilities
- **🐚 Secure Shell Access**: Execute system commands with safety checks (owner-only)
- **🛡️ Advanced Security**: Structured error handling with correlation IDs and audit logging
- **⚡ Performance Optimized**: LRU/TTL caching with metrics tracking and batch database operations
- **🎨 Premium Gating**: Link-level premium requirements with flexible access control
- **💡 Smart Recommendations**: Personalized file and search recommendations based on user behavior
- **📊 Search History**: Track and display most searched keywords with keyboard shortcuts
- **🔍 Fuzzy Matching**: Typo-tolerant search with "Did you mean?" suggestions using rapidfuzz
- **🛡️ Rate Limiting**: Comprehensive rate limiting for search, file requests, inline queries, and broadcasts

### 👨‍💼 Admin Features
- **📈 Detailed Statistics**: User stats, file stats, cache stats, and system metrics
- **🚫 User Management**: Ban/unban users with reasons, add/remove premium
- **📢 Channel Management**: Add/remove/toggle channels for auto-indexing
- **⚙️ Bot Settings**: Manage all bot settings via /bsetting command
- **🗃️ Database Management**: Multi-database statistics, switching, and monitoring
- **🔄 Auto-Updates**: Pull updates from upstream repository
- **💾 Cache Management**: Monitor and optimize cache usage with hit rate analytics
- **⚡ Performance Monitoring**: Real-time performance metrics with correlation tracking
- **🖥️ Shell Access**: Execute shell commands (primary admin only)
- **🗑️ File Management**: Delete files from database by ID or keyword
- **🔍 File Verification**: Verify file access and integrity
- **🛡️ Security Monitoring**: Advanced error tracking with structured logging and audit trails
- **📊 Cache Analytics**: Comprehensive cache performance metrics and optimization tools
- **🎯 Permission System**: Granular access control with admin/moderator/user roles

## 📋 Requirements

- Python 3.9 or higher
- MongoDB 5.0 or higher
- Redis 6.0 or higher
- A Telegram Bot Token (from [@BotFather](https://t.me/botfather))
- API ID and Hash (from [telegram.org](https://my.telegram.org))
- Linux OS (recommended for uvloop optimization)

### Python Dependencies
Key libraries include:
- `pyrogram` - Telegram MTProto API wrapper
- `motor` - Async MongoDB driver
- `redis` - Redis client for caching and rate limiting
- `rapidfuzz` - High-performance fuzzy string matching for typo tolerance
- `pydantic` - Settings management and validation
- `uvloop` (optional) - Enhanced event loop performance on Linux

## 🛠️ Installation

### In Local Deployment make sure to uncomment these lines in bot.py file (remove the # before each line)
    #from dotenv import load_dotenv
    #load_dotenv()

### 1. Clone the Repository
```bash
git clone https://github.com/rumalg123/Advanced-File-Filter-Bot.git
cd Advanced-File-Filter-Bot
```

### 2. Install Dependencies
```bash
# Create virtual environment (recommended)
python -m venv venv

# Activate virtual environment
# On Linux/Mac:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# Install requirements
pip install -r requirements.txt

# Install uvloop for better performance (Linux/macOS only)
pip install uvloop
```

### 3. Configure Environment Variables
```bash
# Copy sample environment file
cp .env.example .env
# Note: The file is named .env.example (not sample.env)

# Edit .env with your configuration
nano .env  # or use any text editor
```

**Required Variables:**
- `API_ID` and `API_HASH` - Get from [telegram.org](https://my.telegram.org)
- `BOT_TOKEN` - Get from [@BotFather](https://t.me/botfather)
- `DATABASE_URI` - MongoDB connection string
- `REDIS_URI` - Redis connection string
- `ADMINS` - Your Telegram user ID (comma-separated for multiple admins)

See the [Configuration Guide](#-configuration-guide) section for all available options.

### 4. Set Up MongoDB

#### Option A: Local MongoDB
```bash
# Install MongoDB (Ubuntu/Debian)
sudo apt-get install mongodb

# Start MongoDB
sudo systemctl start mongodb
```

#### Option B: MongoDB Atlas (Cloud)
1. Create account at [MongoDB Atlas](https://www.mongodb.com/cloud/atlas)
2. Create a cluster
3. Get connection string and update `DATABASE_URI` in `.env`

### 5. Set Up Redis

#### Option A: Local Redis
```bash
# Install Redis (Ubuntu/Debian)
sudo apt-get install redis-server

# Start Redis
sudo systemctl start redis
```

#### Option B: Redis Cloud
1. Create account at [Redis Cloud](https://redis.com/try-free/)
2. Create database
3. Get connection string and update `REDIS_URI` in `.env`

### 6. Run the Bot
```bash
# On Linux (with uvloop optimization and auto-update support)
bash start.sh

# Or directly with Python
python bot.py
```

## 🔄 Auto-Update System

The bot includes a comprehensive auto-update system with enterprise-grade security features:

### 🛡️ Security Features
- **Repository Validation**: Only HTTPS URLs from trusted platforms (GitHub, GitLab, Bitbucket)
- **Branch Validation**: Prevents injection attacks through branch names
- **Python Syntax Validation**: Validates code before applying updates
- **Backup System**: Automatic backups before updates with rollback capability
- **Docker Environment Detection**: Smart handling for containerized deployments

### 📝 Manual Update Commands
```bash
# Basic update from your repository
python update.py --repo https://github.com/rumalg123/Advanced-File-Filter-Bot.git

# Update from specific branch
python update.py --repo https://github.com/rumalg123/Advanced-File-Filter-Bot.git --branch main

# Update without backup (not recommended)
python update.py --skip-backup

# Rollback to previous version
python update.py --rollback backups/backup_20231201_120000

# View help and examples
python update.py --help
```

### ⚙️ Startup Script Options
```bash
# Normal start
bash start.sh

# Start with update check
bash start.sh --update

# Setup environment only (create venv, install deps)
bash start.sh --setup

# Run health checks only
bash start.sh --check

# View all options
bash start.sh --help
```

### 🔧 Auto-Update Configuration
Add these environment variables to your `.env` file:

```bash
# Auto-Update Settings
UPDATE_REPO=https://github.com/rumalg123/Advanced-File-Filter-Bot
UPDATE_BRANCH=main
AUTO_UPDATE=false              # Auto-update on every start
UPDATE_ON_START=false          # Update once on start
BACKUP_ON_UPDATE=true          # Create backups (recommended)
CONTINUE_ON_UPDATE_FAIL=false  # Continue with old version if update fails (Docker only)
```

**Note**: The bot uses `UPDATE_REPO` and `UPDATE_BRANCH` (not `UPSTREAM_REPO` and `UPSTREAM_BRANCH`). The `UPSTREAM_*` variables are legacy and may still work but `UPDATE_*` is preferred.

### 📚 Update Process
1. **Validation**: Repository URL and branch name validation
2. **Backup**: Create timestamped backup of current installation
3. **Clone**: Secure shallow clone of the specified repository and branch
4. **Validation**: Python syntax validation of critical files
5. **Apply**: Safe file replacement with proper permissions
6. **Cleanup**: Automatic cleanup of temporary files

## 🐳 Docker Deployment

The Docker setup now includes auto-update support, persistent volumes, and enhanced security.

### Using Docker Compose (Recommended)
```bash
# Build and run with auto-update support
docker-compose up -d

# Build and run with auto-update enabled
AUTO_UPDATE=true docker-compose up -d

# View logs
docker-compose logs -f file-filter-bot

# Restart after updates
docker-compose restart file-filter-bot

# Stop
docker-compose down
```

### Docker Features
- **Persistent Volumes**: Automatic backup, log, and data persistence
- **Auto-Update Support**: Built-in git and update script integration
- **Security Hardening**: Non-root user, minimal attack surface
- **Health Checks**: Automatic container health monitoring
- **Redis Integration**: Optimized Redis configuration included

### Docker Environment Variables
```bash
# Auto-Update Configuration
UPDATE_REPO=https://github.com/rumalg123/Advanced-File-Filter-Bot
UPDATE_BRANCH=main
AUTO_UPDATE=false          # Enable auto-updates in container
UPDATE_ON_START=false      # Update on container start
BACKUP_ON_UPDATE=true      # Create backups during updates

# Performance Configuration
MAX_CONNECTIONS=20         # Maximum concurrent connections
CACHE_TTL=3600            # Cache time-to-live in seconds
TZ=UTC                    # Timezone setting
```

### Using Dockerfile (Manual)
```bash
# Build image
docker build -t advanced-file-filter-bot .

# Run container with auto-update support
docker run -d \
  --name file-filter-bot \
  --env-file .env \
  -e UPDATE_REPO=https://github.com/rumalg123/Advanced-File-Filter-Bot \
  -e AUTO_UPDATE=false \
  -v bot-backups:/usr/src/app/backups \
  -v bot-logs:/usr/src/app/logs \
  -p 8000:8000 \
  advanced-file-filter-bot
```

## ⚙️ Configuration Guide

### Essential Settings

| Variable | Description | Example |
|----------|-------------|---------|
| `BOT_TOKEN` | Bot token from BotFather | `123456:ABC-DEF1234...` |
| `API_ID` | Telegram API ID | `12345678` |
| `API_HASH` | Telegram API Hash | `abcdef123456...` |
| `DATABASE_URI` | MongoDB connection string | `mongodb://localhost:27017` |
| `DATABASE_NAME` | Database name | `PIRO` |
| `DATABASE_URIS` | Multiple database URIs (comma separated) | `mongodb://...,mongodb://...` |
| `DATABASE_NAMES` | Multiple database names (comma separated) | `PIRO_DB1,PIRO_DB2` |
| `REDIS_URI` | Redis connection string | `redis://localhost:6379` |
| `ADMINS` | Admin user IDs (comma separated) | `123456789,987654321` |
| `LOG_CHANNEL` | Channel for bot logs | `-1001234567890` |

### Feature Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DISABLE_PREMIUM` | Disable premium features | `True` |
| `DISABLE_FILTER` | Disable filter features | `False` |
| `NON_PREMIUM_DAILY_LIMIT` | Daily file limit for free users | `10` |
| `PREMIUM_PRICE` | Premium subscription price with currency | `$1` |
| `MESSAGE_DELETE_SECONDS` | Auto-delete time in seconds | `300` |
| `USE_CAPTION_FILTER` | Search in file captions | `True` |
| `MAX_BTN_SIZE` | Maximum buttons per page | `10` |
| `PUBLIC_FILE_STORE` | Allow public file store access | `False` |
| `KEEP_ORIGINAL_CAPTION` | Keep original file captions | `True` |
| `DATABASE_AUTO_SWITCH` | Auto-switch databases when full | `True` |
| `DATABASE_SIZE_LIMIT_GB` | Size limit per database (GB) | `0.5` |
| `DATABASE_MAX_FAILURES` | Max failures before circuit breaker opens | `5` |
| `DATABASE_RECOVERY_TIMEOUT` | Recovery timeout in seconds | `300` |
| `DATABASE_HALF_OPEN_CALLS` | Max calls in half-open state | `3` |
| `COLLECTION_NAME` | MongoDB collection name | `FILES` |
| `SESSION` | Bot session name | `Media_search` |
| `PORT` | Server port | `8000` |
| `WORKERS` | Number of workers | `50` |
| `AUTO_DELETE_MESSAGE` | Custom auto-delete message template | `⏱ This {content_type} will be auto-deleted after {minutes} minutes` |
| `START_MESSAGE` | Custom start message template | `Welcome to the bot!` |
| `UPDATE_REPO` | Git repository for auto-updates | `https://github.com/user/repo.git` |
| `UPDATE_BRANCH` | Git branch for updates | `main` |
| `AUTO_UPDATE` | Auto-update on every start | `false` |
| `UPDATE_ON_START` | Update once on start | `false` |
| `BACKUP_ON_UPDATE` | Create backups during updates | `true` |
| `CONTINUE_ON_UPDATE_FAIL` | Continue with old version if update fails (Docker) | `false` |
| `REQUEST_ONLY_FOR_PREMIUM` | Restrict #request feature to premium users only | `False` |
| `REQUEST_PER_DAY` | Daily request limit per user | `3` |
| `REQUEST_WARNING_LIMIT` | Warning limit before ban | `5` |
| `USE_ORIGINAL_CAPTION_FOR_BATCH` | Use original captions in batch mode | `true` |
| `CUSTOM_FILE_CAPTION` | Custom file caption template (placeholders: {filename}, {size}) | Empty (uses default) |
| `BATCH_FILE_CAPTION` | Batch file caption template | Empty (uses default) |
| `TZ` | Timezone setting | `UTC` |

### Optional Features

| Variable | Description               | Required |
|----|---------------------------|----------|
| `AUTH_CHANNEL` | Force subscription channel | Optional |
| `AUTH_GROUPS` | Force subscription groups (comma-separated) | Optional |
| `AUTH_USERS` | Authorized user IDs (comma-separated) | Optional |
| `FILE_STORE_CHANNEL` | Channels for file storage | Optional |
| `SUPPORT_GROUP_ID` | Support group for #request | Optional |
| `SUPPORT_GROUP_URL` | Support group URL | Optional |
| `SUPPORT_GROUP_NAME` | Support group name | Optional |
| `INDEX_REQ_CHANNEL` | Channel for index requests | Optional |
| `DELETE_CHANNEL` | Channel for file deletion | Optional |
| `REQ_CHANNEL` | Request channel ID (uses LOG_CHANNEL if 0) | Optional |
| `PAYMENT_LINK` | Payment Method Link       | Optional |
| `PICS` | Picture URLs for start command (comma-separated) | Optional |
| `CHANNELS` | Channel IDs to index (comma-separated) | Optional |

### Concurrency Configuration (Optional)

| Variable | Description | Default |
|----------|-------------|---------|
| `CONCURRENCY_TELEGRAM_SEND` | Max concurrent Telegram send operations | `10` |
| `CONCURRENCY_TELEGRAM_FETCH` | Max concurrent Telegram fetch operations | `15` |
| `CONCURRENCY_DATABASE_WRITE` | Max concurrent database write operations | `20` |
| `CONCURRENCY_DATABASE_READ` | Max concurrent database read operations | `30` |
| `CONCURRENCY_FILE_PROCESSING` | Max concurrent file processing operations | `5` |
| `CONCURRENCY_BROADCAST` | Max concurrent broadcast operations | `3` |
| `CONCURRENCY_INDEXING` | Max concurrent indexing operations | `8` |

### Processing Limits Configuration (Optional)

| Variable | Description | Default |
|----------|-------------|---------|
| `PROCESSING_BATCH_SIZE_HIGH_LOAD` | Batch size when queue > 500 | `50` |
| `PROCESSING_BATCH_SIZE_MEDIUM_LOAD` | Batch size when queue > 200 | `30` |
| `PROCESSING_BATCH_SIZE_LOW_LOAD` | Batch size when queue <= 200 | `20` |
| `PROCESSING_QUEUE_HIGH_THRESHOLD` | Queue size threshold for high load | `500` |
| `PROCESSING_QUEUE_MEDIUM_THRESHOLD` | Queue size threshold for medium load | `200` |
| `PROCESSING_MAX_BATCH_MESSAGES` | Maximum messages in a single batch link | `10000` |
| `PROCESSING_MESSAGE_QUEUE_SIZE` | Maximum message queue size | `1000` |
| `PROCESSING_OVERFLOW_QUEUE_SIZE` | Maximum overflow queue size | `500` |
| `PROCESSING_INTER_MESSAGE_DELAY` | Delay between processing messages (seconds) | `0.5` |
| `PROCESSING_BATCH_WAIT_TIME_HIGH` | Wait time in high load (seconds) | `2` |
| `PROCESSING_BATCH_WAIT_TIME_MEDIUM` | Wait time in medium load (seconds) | `3` |
| `PROCESSING_BATCH_WAIT_TIME_LOW` | Wait time in low load (seconds) | `5` |

## 📚 Usage Guide

### 🔹 User Commands

| Command | Description |
|---------|-------------|
| `/start` | Start the bot |
| `/help` | Show help message |
| `/about` | About the bot |
| `/stats` | Bot statistics |
| `/plans` | View premium plans |
| `/recommendations` | Get personalized file and search recommendations |
| `/my_keywords` | View your most searched keywords |
| `/popular_keywords` | View globally popular search keywords |

### 🔍 Search Features
- **Direct Search**: Just send any text to search for files
- **Inline Search**: Use `@yourbotusername query` in any chat
- **Filter by Type**: Add file type after pipe: `query | video`
- **Send All**: Click "Send All Files" button to receive all search results
- **Smart File Emojis**: Files display with type-specific emojis for easy identification
- **Cross-Database Search**: Search across multiple databases simultaneously with proper result ordering
- **Auto-Delete Results**: Search results automatically delete after configured time to keep chats clean
- **Fuzzy Matching**: Typo-tolerant search automatically handles common typos (e.g., "fevr" matches "fever")
- **"Did you mean?" Suggestions**: When no results found, bot suggests similar queries with clickable buttons
- **Search History**: Track your search patterns and access frequently used keywords via keyboard shortcuts
- **Smart Recommendations**: Get personalized file and search suggestions based on your search history and behavior

#### File Type Emojis
| File Types | Emoji | Examples |
|------------|--------|----------|
| Videos | 🎬 | .mp4, .mkv, .avi, .mov, .webm |
| Audio | 🎵 | .mp3, .flac, .wav, .aac, .ogg |
| Archives | 📦 | .zip, .rar, .7z, .tar, .gz |
| Subtitles | 💬 | .srt, .vtt, .ass, .ssa, .sub |
| Images | 🖼️ | .jpg, .png, .gif, .webp, .bmp |
| Documents | 📄 | .pdf, .doc, .docx, .txt |
| Code Files | 💻 | .py, .js, .html, .css, .cpp |
| And many more! | 🎲🔒💿📐 | 3D models, certificates, ISOs, CAD files

### 🔗 Connection Commands (Groups & Private)

| Command | Description |
|---------|-------------|
| `/connect` | Connect to a group |
| `/disconnect` | Disconnect from group |
| `/connections` | View all connections |

### 🎭 Filter Commands (if enabled)

| Command | Description |
|---------|-------------|
| `/add <keyword> <reply>` | Add a filter with keyword and response |
| `/filter <keyword> <reply>` | Alternative to add filter |
| `/filters` | View all filters in current chat |
| `/viewfilters` | Alternative to view filters |
| `/delf <keyword>` | Delete a specific filter |
| `/deletef <keyword>` | Alternative to delete filter |
| `/delallf` | Delete all filters in current chat |
| `/deleteallf` | Alternative to delete all filters |

**Filter Features:**
- **Rich Text Support**: Use HTML formatting in filter responses
- **Button Support**: Add inline keyboard buttons to filter responses
- **File Attachments**: Attach files to filter responses
- **Alert Messages**: Show popup alerts when filters trigger

### 📮 Request Feature
- In support group, use `#request <content_name>` to request content
- Bot will search and show results or forward request to admins
- Admins can mark requests as available, unavailable, uploaded, or rejected

### 👮 Admin Commands

#### User Management
| Command | Description |
|---------|-------------|
| `/users` | Get total users count |
| `/broadcast` | Enhanced broadcast with HTML formatting and preview |
| `/stop_broadcast` | Stop ongoing broadcast |
| `/ban <user_id> [reason]` | Ban a user with optional reason |
| `/unban <user_id>` | Unban a user |
| `/addpremium <user_id>` | Add premium status |
| `/removepremium <user_id>` | Remove premium status |

#### 📡 Enhanced Broadcasting System
The bot features an advanced broadcasting system with safety features:

**Features:**
- **HTML Formatting**: Full HTML support with `<b>bold</b>`, `<i>italic</i>`, `<code>code</code>` tags
- **Message Preview**: Shows preview of message and recipient count before sending
- **Confirmation System**: Confirm/Cancel buttons prevent accidental broadcasts
- **Progress Tracking**: Real-time progress updates with statistics
- **Stop Functionality**: Emergency stop capability during broadcast
- **Support for Media**: Text, photos, videos, documents, and other media types

**Usage:**
1. Reply to any message with `/broadcast`
2. Preview your message and recipient count
3. Click "✅ Confirm Broadcast" or "❌ Cancel"  
4. Monitor progress in real-time
5. Use `/stop_broadcast` to emergency stop if needed

**Safety Features:**
- Rate limiting prevents spam
- Preview prevents accidental sends
- Progress tracking allows monitoring
- Emergency stop capability
- Admin-only access with proper validation

#### Channel Management
| Command | Description |
|---------|-------------|
| `/add_channel <id/username>` | Add channel for auto-indexing |
| `/remove_channel <id/username>` | Remove channel |
| `/list_channels` | List all indexed channels |
| `/toggle_channel <id/username>` | Enable/disable channel |

#### File Indexing
| Command | Description |
|---------|-------------|
| Forward a message | Forward from channel to index |
| Send channel link | Send link with last message ID |
| `/setskip <number>` | Set starting message ID for indexing |

#### File Management
| Command | Description |
|---------|-------------|
| `/delete` | Delete file from database (reply to file) |
| `/delete <file_id>` | Delete file by ID |
| `/deleteall <keyword>` | Delete all files matching keyword |

#### Cache Management
| Command | Description |
|---------|-------------|
| `/cache_stats` | View cache statistics |
| `/cache_analyze` | Analyze cache usage patterns |
| `/cache_cleanup confirm` | Clean up duplicate cache entries |

#### Database Management
| Command | Description |
|---------|-------------|
| `/dbstats` | View database statistics, usage, and capacity warnings |
| `/dbinfo` | View detailed database information and health status |
| `/dbswitch <number>` | Manually switch to different write database (e.g., `/dbswitch 2`) |

**Database Features:**
- **Smart Database Selection**: AI-powered load balancing based on usage and health
- **Circuit Breaker Protection**: Automatic fault tolerance with 5-failure threshold
- **Real-time Optimization**: 30-second cache for critical switching decisions
- **Emergency Handling**: Graceful degradation when all databases reach capacity
- **Auto-recovery**: Failed databases automatically recover when healthy

#### System Commands
| Command | Description |
|---------|-------------|
| `/performance` | View performance metrics and system status |
| `/log` | Get bot log file for debugging |
| `/restart` | Restart bot with git updates and version info |

**Enhanced Restart Features:**
- **Git Integration**: Shows current commit hash, date, and message during restart
- **Force Pull Updates**: Automatically pulls latest updates from upstream repository
- **Update Detection**: Displays what changed between restarts
- **Version Tracking**: Success message shows current version details
- **Local Changes Warning**: Alerts when uncommitted changes are detected

#### Primary Admin Only
| Command | Description |
|---------|-------------|
| `/bsetting` | Open bot settings menu |
| `/verify` | Verify file access and integrity |
| `/cancel` | Cancel current operation |
| `/shell <command>` | Execute shell command with security checks |

### 🐚 Secure Shell Command System

The bot includes a secure shell command system for the primary admin (first admin in the list):

#### Features
- **Owner-Only Access**: Only the first admin can execute shell commands
- **Dangerous Command Detection**: Automatically warns about potentially destructive commands
- **Execution Timeout**: Commands timeout after 5 minutes for safety
- **Output Handling**: Small outputs shown inline, large outputs sent as files
- **Comprehensive Logging**: All commands logged with execution details
- **Security Patterns**: Blocks dangerous patterns like `rm -rf`, `chmod 777`, etc.

#### Usage Examples
```bash
# Safe system information commands
/shell ls -la
/shell df -h
/shell ps aux
/shell python --version
/shell git status

# Package management
/shell pip install requests
/shell pip list

# System monitoring
/shell free -h
/shell uptime
/shell uname -a
```

#### Dangerous Commands (Automatically Detected)
The system will warn you about potentially dangerous commands:
- `rm -rf` - Recursive file deletion
- `chmod 777` - Permission changes
- `sudo su` - Privilege escalation
- `mkfs`, `format` - Filesystem operations
- `dd if=` - Direct disk operations
- `fdisk` - Disk partitioning
- `kill -9 1` - System process termination

### 📤 File Store Commands

| Command | Description | Access |
|---------|-------------|--------|
| `/link` | Get shareable link for file | Admin/Public* |
| `/plink` | Get protected link | Admin/Public* |
| `/batch` | Create batch link for multiple files | Admin/Public* |
| `/pbatch` | Create protected batch link | Admin/Public* |
| `/batch_premium` | Create premium-only batch link | Admin/Public* |
| `/pbatch_premium` | Create premium-only protected batch link | Admin/Public* |
| `/bprem` | Create premium batch link (alias) | Admin/Public* |
| `/pbprem` | Create premium protected batch link (alias) | Admin/Public* |

*Public if `PUBLIC_FILE_STORE=True`

### 💎 Premium Batch Links

The bot now supports **premium-only batch links** that provide enhanced access control:

#### Features
- **Link-Level Premium Control**: Individual batch links can require premium membership
- **Global Premium Integration**: Premium batch commands require global premium to be enabled
- **Protected Content Support**: Non-forwardable content for sensitive files
- **Consistent Premium System**: Works in harmony with global premium settings

#### Requirements
- **Global Premium Must Be Enabled**: Set `DISABLE_PREMIUM=false` to use premium batch commands
- **Admin Only**: Only admins can create premium batch links (or public if `PUBLIC_FILE_STORE=True`)

#### Access Control Rules
1. **Global Premium Disabled** (`DISABLE_PREMIUM=true`) → Premium batch commands unavailable
2. **Premium Batch Link** (`premium_only=true`) → User must have premium membership
3. **Global Premium Enabled** → All batch access requires premium membership
4. **No Premium Requirements** → Allow all users (when global premium is disabled)

#### Command Examples
```bash
# Note: These commands only work when DISABLE_PREMIUM=false

# Create premium-only batch link
/batch_premium https://t.me/channel/100 https://t.me/channel/150

# Create premium-only protected batch link (non-forwardable)
/pbatch_premium https://t.me/channel/100 https://t.me/channel/150

# Short aliases
/bprem https://t.me/channel/100 https://t.me/channel/150
/pbprem https://t.me/channel/100 https://t.me/channel/150
```

#### Benefits
- **Monetization**: Offer premium content access as a paid feature
- **Content Protection**: Protect sensitive files from unauthorized sharing
- **Flexible Control**: Mix free and premium content as needed
- **System Consistency**: Premium features work together seamlessly

## 🗃️ Multi-Database System Guide

The bot features an enterprise-grade multi-database system for automatic scaling, fault tolerance, and intelligent load balancing.

### 📋 Multi-Database Overview

The multi-database system provides:
- **🎯 Smart Database Selection**: AI-powered load balancing based on usage, health, and performance
- **🛡️ Circuit Breaker Protection**: Automatic fault tolerance with 5-failure threshold and auto-recovery
- **⚡ Real-time Optimization**: 30-second cache vs 5-minute for critical switching decisions
- **🔒 Thread-safe Operations**: Race condition protection with async locks
- **🚨 Emergency Handling**: Graceful degradation when all databases reach capacity
- **🔍 Cross-database Search**: Proper pagination and sorting across all databases
- **♻️ Auto-recovery**: Failed databases automatically recover when they come back online

### ⚙️ Multi-Database Configuration

#### Environment Variables for Multi-Database
```bash
# Single database (existing setup) - Still supported
DATABASE_URI=mongodb+srv://user:pass@cluster1.mongodb.net
DATABASE_NAME=PIRO

# Multi-database system (enterprise features)
DATABASE_URIS=mongodb+srv://user:pass@cluster1.mongodb.net,mongodb+srv://user:pass@cluster2.mongodb.net,mongodb+srv://user:pass@cluster3.mongodb.net
DATABASE_NAMES=PIRO_DB1,PIRO_DB2,PIRO_DB3

# Smart switching configuration
DATABASE_SIZE_LIMIT_GB=0.5          # Size limit before switching (GB)
DATABASE_AUTO_SWITCH=True           # Enable intelligent auto-switching

# Circuit breaker configuration (optional - uses defaults if not set)
DATABASE_MAX_FAILURES=5             # Max failures before circuit opens (default: 5)
DATABASE_RECOVERY_TIMEOUT=300       # Seconds before testing recovery (default: 300)
```

#### MongoDB Atlas Free Tier Setup (Cost: $0)
Use multiple MongoDB Atlas free clusters (512MB each) for unlimited storage:
```bash
# Example: 3 free clusters = ~1.5GB total storage
DATABASE_URIS=mongodb+srv://user1:pass1@cluster1.mongodb.net,mongodb+srv://user2:pass2@cluster2.mongodb.net,mongodb+srv://user3:pass3@cluster3.mongodb.net
DATABASE_NAMES=MediaBot_Main,MediaBot_Backup,MediaBot_Archive
DATABASE_SIZE_LIMIT_GB=0.45  # Stay under 512MB limit with buffer
DATABASE_AUTO_SWITCH=True
```

### 🧠 Smart Database Selection Algorithm

The system evaluates databases using weighted factors:
- **Storage Usage (40%)**: Lower usage = higher score
- **Circuit Health (30%)**: Healthy databases preferred  
- **Connection Stability (15%)**: Based on success/failure ratio
- **Current DB Bonus (15%)**: Avoid unnecessary switching

### 🛡️ Circuit Breaker System

**How It Works:**
- **CLOSED** → Normal operation (healthy)
- **OPEN** → Reject requests (5-minute timeout after 5 failures)
- **HALF_OPEN** → Test recovery (limited requests)

### 🚨 Emergency Handling

When all databases reach capacity, the system:
1. Uses the least full database as emergency fallback
2. Logs critical alerts for admin action
3. Continues operation while alerting admins to add more databases

## 🔧 Advanced Configuration

### Bot Settings Management
The bot includes a comprehensive settings management system accessible via `/bsetting` (primary admin only):

- **Dynamic Configuration**: Change bot settings without restarting
- **Category Organization**: Settings grouped by category  
- **Live Updates**: Most settings apply immediately (some require restart)
- **Protected Settings**: Critical settings require manual environment variable changes
- **Session Management**: Automatic timeout and cleanup for editing sessions
- **Input Validation**: Real-time validation and formatting support

### Enhanced Auto-Delete System

The bot features an advanced auto-delete system with comprehensive customization:

**Key Features:**
- **Customizable Messages**: Use HTML templates with placeholders like `{content_type}` and `{minutes}`
- **Smart Scheduling**: Proper task management with automatic cleanup
- **Cross-Handler Support**: Works across search, file store, requests, and filter responses
- **Session Tracking**: Uses WeakSet for efficient memory management
- **Error Handling**: Graceful failure handling with debug logging

**Template Customization:**
```bash
# Custom auto-delete message with HTML formatting
AUTO_DELETE_MESSAGE='⏱ <b>Auto-Delete Notice</b>\n\nThis {content_type} will be <u>automatically deleted</u> after <b>{minutes} minutes</b>'

# Available placeholders:
# {content_type} - Type of content (file, message, etc.)
# {minutes} - Number of minutes until deletion
```

**Configuration Options:**
- `MESSAGE_DELETE_SECONDS` - Time in seconds before deletion
- `AUTO_DELETE_MESSAGE` - Custom message template with HTML support
- Automatic task cleanup prevents memory leaks

### Performance Optimization

#### uvloop Integration (Linux/macOS)
The bot automatically uses uvloop when available for 2-4x performance improvement:
```bash
# Install uvloop
pip install uvloop

# The bot will automatically detect and use it
```

#### Database Indexes
The bot automatically creates optimized indexes:
- Text search index on `file_name` and `caption`
- Compound index on `file_type` and `indexed_at`
- Unique index on `file_hash` for duplicate detection
- Index on `file_ref` for fast lookups
- Indexes are created on ALL databases in multi-database setup

#### MongoDB Optimization
```javascript
// Increase connection pool size
maxPoolSize: 200  // With uvloop
maxPoolSize: 100  // Without uvloop

// Enable compression
compressors: ['zlib']

// For large datasets, consider sharding
sh.enableSharding("telegram_media_bot")
```

#### Redis Optimization
```conf
# Increase max memory
maxmemory 2gb

# Set eviction policy
maxmemory-policy allkeys-lru

# Enable persistence
save 900 1
save 300 10
```

### Scaling for High Load

1. **Horizontal Scaling**
   - Run multiple bot instances
   - Use a load balancer for webhooks
   - All instances share MongoDB and Redis

2. **Multi-Database Scaling** 🚀
   - **Smart Database Selection**: Intelligent load balancing based on usage, health, and performance
   - **Circuit Breaker Protection**: Automatic fault tolerance with 5-failure threshold
   - **Real-time Optimization**: 30-second stats cache vs 5-minute for critical operations
   - **Thread-safe Switching**: Race condition protection with async locks
   - **Emergency Handling**: Graceful degradation when all databases reach capacity
   - **Cross-database Search**: Proper pagination and sorting across all databases
   - **Auto-recovery**: Databases automatically recover when they come back online
   - Enable sharding for very large datasets
   - Use read preference for search queries
   - Monitor database usage with `/dbstats` and `/dbinfo` commands

3. **Caching Strategy**
   - Increase cache TTL for stable data
   - Use Redis Cluster for distributed caching
   - Implement cache warming for popular searches

## 🚀 Deployment Options

### VPS Deployment
```bash
# Using systemd service
sudo nano /etc/systemd/system/mediabot.service

# Add service configuration
[Unit]
Description=Telegram Media Bot
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/bot
ExecStart=/usr/bin/python3 /path/to/bot/bot.py
Restart=always
Environment="USE_UVLOOP=1"

[Install]
WantedBy=multi-user.target

# Enable and start service
sudo systemctl enable mediabot
sudo systemctl start mediabot
```

### Heroku Deployment
```bash
# Create Procfile
echo "worker: python bot.py" > Procfile

# Create runtime.txt
echo "python-3.11.0" > runtime.txt

# Deploy
heroku create your-app-name
heroku config:set $(cat .env | xargs)
git push heroku main
```

### Railway Deployment
[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/48ph1A?referralCode=ZaL8lf)

#### Follow the below steps
##### Step 1
![Step 1](Railway_deployment_steps/1.png)
##### Step 2
![Step 2](Railway_deployment_steps/2.png)
##### Step 3
![Step 3](Railway_deployment_steps/3.png)
##### Step 4
![Step 4](Railway_deployment_steps/4.png)
##### Step 5
![Step 5](Railway_deployment_steps/5.png)
##### Step 6
![Step 6](Railway_deployment_steps/6.png)
##### Step 7
![Step 7](Railway_deployment_steps/7.png)
##### Step 8
![Step 8](Railway_deployment_steps/8.png)
##### Step 9
![Step 9](Railway_deployment_steps/9.png)
##### Step 10
![Step 10](Railway_deployment_steps/10.png)
##### Step 11
![Step 11](Railway_deployment_steps/11.png)
##### Step 12
![Step 12](Railway_deployment_steps/12.png)
##### Step 13
![Step 13](Railway_deployment_steps/13.png)
##### Step 14
![Step 14](Railway_deployment_steps/14.png)
##### Step 15
![Step 15](Railway_deployment_steps/15.png)
##### Step 16
![Step 16](Railway_deployment_steps/16.png)
##### Step 17
![Step 17](Railway_deployment_steps/17.png)

## 🔒 Security Best Practices

1. **Environment Variables**
   - Never commit `.env` file
   - Use secrets management in production
   - Rotate tokens regularly

2. **Database Security**
   - Use authentication for MongoDB
   - Enable SSL/TLS connections
   - Regular backups

3. **Auto-Update Security** 🆕
   - Only use HTTPS repository URLs from trusted platforms
   - Verify repository ownership before setting UPDATE_REPO
   - Enable backups (BACKUP_ON_UPDATE=true) for rollback capability
   - Test updates in staging environment first
   - Monitor update logs for suspicious activity

4. **Shell Command Security** 🆕
   - Shell access is restricted to the primary admin (first in ADMINS list)
   - Dangerous commands are automatically detected and blocked
   - All commands are logged with execution details
   - Use with extreme caution in production environments
   - Consider disabling in high-security environments

5. **Docker Security**
   - Container runs as non-root user
   - Minimal attack surface with slim base image
   - Persistent volumes for data safety
   - Network isolation with bridge networking
   - Health checks for container monitoring

6. **Rate Limiting**
   - Configure appropriate limits
   - Monitor for abuse patterns
   - Implement IP-based limiting if needed

7. **Access Control**
   - Limit admin commands
   - Validate all user inputs
   - Use force subscription wisely
   - Regular access audit and cleanup

## 📊 Monitoring & Maintenance

### Health Check
- Access `http://your-server:8000/health` for status
- Access `http://your-server:8000/metrics` for performance metrics
- Monitor bot uptime
- Set up alerts for failures

### Cache Monitoring
Use the cache management commands to:
- Monitor cache hit rates and memory usage
- Identify and clean duplicate entries
- Analyze cache usage patterns
- Optimize cache TTL values

### Performance Monitoring
- Use `/performance` command to view real-time metrics
- Monitor event loop type (uvloop vs asyncio)
- Track memory usage and CPU utilization
- Monitor pending tasks and file descriptors

### Regular Maintenance
- Clean up old files: `/deleteall` with date filters
- Monitor database size with `/dbstats` and `/dbinfo`
- Switch databases when needed: `/dbswitch <number>`
- Update dependencies regularly
- Check logs for errors
- Clear expired cache entries (automatic with Redis TTL)
- Review and optimize bot settings via `/bsetting`
- Verify file integrity with `/verify`

### Backup Strategy
```bash
# MongoDB backup
mongodump --uri="your-connection-string" --out=backup/

# Export bot settings
# Use /bsetting menu to export settings

# Restore
mongorestore --uri="your-connection-string" backup/
```

## 🆕 Recent Updates & New Features

### ✨ Latest Major Additions
- **💡 Smart Recommendations**: Personalized file and search recommendations based on user behavior, search history, and trending content
- **📊 Search History & Keywords**: Track user and global search patterns with keyboard shortcuts for quick access
- **🔍 Fuzzy Matching & Typo Tolerance**: Advanced typo-tolerant search with "Did you mean?" suggestions using rapidfuzz library
- **🛡️ Comprehensive Rate Limiting**: Rate limiting for search (30/min), file requests (10/min), inline queries (50/min), and broadcasts (1/hour)
- **📡 Enhanced Broadcasting System**: HTML formatting, message preview, confirmation buttons, progress tracking, and emergency stop functionality
- **🔄 Enterprise Auto-Update System**: Comprehensive auto-update with security validation, backup system, and rollback capabilities
- **🐚 Secure Shell Command**: Owner-only shell access with dangerous command detection and security checks
- **🐳 Enhanced Docker Support**: Auto-update support, persistent volumes, security hardening, and optimized Redis configuration
- **🛡️ Advanced Security**: Repository URL validation, branch validation, Python syntax checking, and non-root Docker containers
- **📦 Improved Startup System**: Comprehensive startup script with health checks, environment detection, and auto-update integration
- **🗃️ Enterprise Multi-Database**: Smart selection, circuit breaker protection, and auto-recovery
- **⏱ Advanced Auto-Delete**: Customizable HTML templates, smart scheduling, and cross-handler support
- **🎯 Smart File Emojis**: File-type specific emojis for better visual identification  
- **📊 Database Management**: Complete admin tools for monitoring, switching, and health checking
- **⚙️ Dynamic Settings**: Comprehensive `/bsetting` system with live configuration changes

### 🚀 Phase 4-7 Enhancements (Latest)
- **🛡️ Unified Error Handling**: Structured error response schema with correlation IDs for complete request tracing
- **📊 Advanced Type Safety**: Comprehensive type hints across all handlers and strict mypy configuration
- **🔧 Enhanced Tooling**: Ruff linting with security, naming, and simplification rules for code quality
- **⚡ Performance Caching**: LRU/TTL cache implementation with metrics tracking and automatic cleanup
- **📈 Cache Analytics**: Real-time hit/miss ratios, eviction tracking, and performance optimization
- **🎯 Smart Validation**: Extended input validation for user IDs, pagination, file types with detailed error reporting
- **🔐 Permission Guards**: Reusable guard functions for admin/premium/ban checks with precedence rules
- **🧪 Comprehensive Testing**: Full test coverage for FloodWait handling, premium gating, HTML parsing, and database operations
- **📚 Enhanced Documentation**: Complete admin guide with troubleshooting, best practices, and operational procedures

### 🔧 Command Improvements
All commands now automatically appear in Telegram's command menu:
- Added smart recommendations command (`/recommendations`) with personalized file and search suggestions
- Added search history commands (`/my_keywords`, `/popular_keywords`) with keyboard shortcuts
- Added secure shell command (`/shell`) with owner-only access and security checks
- Added database management commands (`/dbstats`, `/dbinfo`, `/dbswitch`)
- Added missing filter command aliases (`/filter`, `/viewfilters`, `/delf`, `/delallf`)
- Added admin commands (`/verify`, `/cancel`)
- Enhanced command validation and input sanitization
- Commands are properly scoped (all users, groups, admins, primary admin)

### 🐛 Critical Bug Fixes & Improvements
- **Daily Counter Reset**: Fixed issue where bot restart would reset all users' daily download counts
- **Auto-Delete Consistency**: Fixed inline mode auto-delete messages that never actually deleted files
- **File Emoji Detection**: Fixed emoji detection for sanitized filenames (files without dots)
- **Type Annotations**: Fixed various type errors and warnings throughout the codebase
- **Session Management**: Enhanced session handling with proper cleanup and timeout management
- **Handler Management**: Centralized task and handler lifecycle management
- **Memory Optimization**: WeakSet tracking for auto-delete tasks prevents memory leaks

### ⚡ Performance & Stability Enhancements
- **Circuit Breaker Pattern**: Database fault tolerance with automatic recovery
- **Thread-Safe Operations**: Race condition protection for critical operations  
- **Smart Cache Management**: Different TTL values for critical vs regular operations
- **Background Task Management**: Proper lifecycle handling for all background tasks
- **Enhanced Error Handling**: Graceful degradation and comprehensive logging

## 🎯 Feature Details

### Auto-Delete System
- **Smart Scheduling**: Messages automatically delete after configured time with proper task management  
- **Customizable Templates**: HTML-formatted messages with placeholders for content type and duration
- **Cross-Handler Support**: Works across search results, file sends, requests, and filter responses
- **Memory Efficient**: WeakSet tracking prevents memory leaks from completed tasks
- **Consistent Behavior**: Fixed inline mode issues where messages showed delete notifications but never deleted
- **Error Resilient**: Graceful handling of deletion failures with debug logging
- **Configuration**: Set via `MESSAGE_DELETE_SECONDS` and customize via `AUTO_DELETE_MESSAGE`

### Multi-Database System
- **Automatic Scaling**: Add multiple MongoDB databases as your collection grows
- **Size Limits**: Set per-database size limits (e.g., 0.5GB per database)
- **Auto-Switching**: Automatically switch to new database when current one reaches limit
- **Unified Search**: Search across all databases simultaneously
- **Backward Compatibility**: Existing single-database setups continue to work
- **Database Management**: Monitor, switch, and manage databases via admin commands

#### Setting Up Multi-Database
```bash
# Single database (existing setup)
DATABASE_URI=mongodb://localhost:27017
DATABASE_NAME=PIRO
COLLECTION_NAME=FILES

# Multi-database (new feature)
DATABASE_URI=mongodb://localhost:27017  # Primary database (still required)
DATABASE_NAME=PIRO  # Primary database name
DATABASE_URIS=mongodb://localhost:27017,mongodb://localhost:27018,mongodb://localhost:27019
DATABASE_NAMES=PIRO_DB1,PIRO_DB2,PIRO_DB3
DATABASE_SIZE_LIMIT_GB=0.5
DATABASE_AUTO_SWITCH=true

# Circuit breaker configuration (optional)
DATABASE_MAX_FAILURES=5
DATABASE_RECOVERY_TIMEOUT=300
DATABASE_HALF_OPEN_CALLS=3
```

### Duplicate Detection
- Advanced hash-based duplicate detection
- Prevents storing same file multiple times
- Automatically updates file references
- Saves storage space
- Works across all databases in multi-database setup

### Request System (#request)
- Users can request content in support group
- Automatic search for requested content
- Admin notification system
- Request status tracking

### Connection Management
- Connect private chat to groups
- Manage filters privately
- Multiple group connections
- Auto-cleanup of invalid connections

### Processing & Performance Configuration
The bot includes advanced processing limits for optimal performance:

**Dynamic Batch Sizing:**
- Automatically adjusts batch sizes based on queue load
- High load (>500): 50 messages per batch
- Medium load (>200): 30 messages per batch
- Low load (≤200): 20 messages per batch

**Queue Management:**
- Maximum message queue size: 1000
- Overflow queue size: 500
- Configurable wait times based on load

**Batch Link Limits:**
- Maximum 10,000 messages per batch link
- Automatic queue management and overflow handling
- Configurable inter-message delays

All processing limits can be configured via environment variables (see Configuration Guide).

**Configuration Variables:**
- `PROCESSING_BATCH_SIZE_HIGH_LOAD` - Batch size for high load scenarios
- `PROCESSING_BATCH_SIZE_MEDIUM_LOAD` - Batch size for medium load scenarios
- `PROCESSING_BATCH_SIZE_LOW_LOAD` - Batch size for low load scenarios
- `PROCESSING_QUEUE_HIGH_THRESHOLD` - Queue threshold for high load detection
- `PROCESSING_QUEUE_MEDIUM_THRESHOLD` - Queue threshold for medium load detection
- `PROCESSING_MAX_BATCH_MESSAGES` - Maximum messages per batch link
- `PROCESSING_MESSAGE_QUEUE_SIZE` - Maximum message queue size
- `PROCESSING_OVERFLOW_QUEUE_SIZE` - Maximum overflow queue size
- `PROCESSING_INTER_MESSAGE_DELAY` - Delay between processing messages
- `PROCESSING_BATCH_WAIT_TIME_HIGH/MEDIUM/LOW` - Wait times based on load

### Smart Recommendations System
- **Personalized Recommendations**: Get file and search suggestions based on your search history and behavior
- **Similar Searches**: Discover related queries based on co-occurrence patterns and fuzzy matching
- **Based on History**: See files you might like based on your past searches with actual file names displayed
- **Trending Content**: Discover popular files from global search trends with file names
- **Clickable Results**: All recommendations are clickable - search queries and files with proper buttons
- **Real-time Updates**: Recommendations update as you search and interact with files
- **Caching**: Recommendations are cached for 10 minutes for fast access
- **Display Format**: Shows actual file names with emojis and search queries in a user-friendly format

### Search History & Keywords
- **User Search History**: Track your personal search patterns and frequently used keywords
- **Global Popular Searches**: See what's trending across all users
- **Keyboard Shortcuts**: Access your most searched keywords via ReplyKeyboardMarkup
- **Quick Access**: Click any keyword to instantly search again
- **Privacy**: Your search history is stored securely in Redis with configurable TTL

### Fuzzy Matching & Typo Tolerance
- **Typo-Tolerant Search**: Automatically handles common typos (e.g., "fevr" → "fever", "thus" → "this")
- **"Did you mean?" Suggestions**: When no results found, bot suggests similar queries with clickable buttons
- **rapidfuzz Integration**: High-performance fuzzy matching library for accurate suggestions
- **Filter Matching**: Fuzzy matching also works for filter commands (add, delete, match)
- **Regex Patterns**: Typo-tolerant regex patterns for database queries
- **Smart Thresholds**: Configurable similarity thresholds for different use cases

### Rate Limiting System
- **Search Rate Limiting**: 30 searches per minute per user
- **File Request Rate Limiting**: 10 file requests per minute per user
- **Inline Query Rate Limiting**: 50 inline queries per minute per user
- **Broadcast Rate Limiting**: 1 broadcast per hour per admin
- **Cooldown System**: Automatic cooldown periods (60 seconds) when limits are exceeded
- **Redis-Based**: Atomic rate limiting using Redis for distributed systems
- **Graceful Handling**: User-friendly error messages with remaining time display
- **Automatic Expiration**: Rate limit counters automatically expire after time window
- **Thread-Safe**: Prevents race conditions with atomic Redis operations

**Rate Limit Configuration:**
- All rate limits are configured in `core/utils/rate_limiter.py`
- Time windows and cooldown periods are customizable
- Rate limits are enforced at the service level for consistency

## 🤝 Contributing

We welcome contributions! Please follow these steps:

1. Fork the repository
2. Create feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

### Development Guidelines
- Follow PEP 8 style guide
- Add tests for new features
- Update documentation
- Use meaningful commit messages
- Test with uvloop enabled and disabled

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [Pyrogram](https://github.com/pyrogram/pyrogram) - Telegram MTProto API wrapper
- [Motor](https://github.com/mongodb/motor) - Async MongoDB driver
- [Redis](https://redis.io/) - In-memory data structure store
- [uvloop](https://github.com/MagicStack/uvloop) - Ultra fast asyncio event loop
- All contributors and users of this bot

## 📞 Support

- 📧 Email: rumalg123@gmail.com
- 💬 Telegram: [@gunaya001](https://t.me/gunaya001)
- 🐛 Issues: [GitHub Issues](https://github.com/rumalg123/Advanced-File-Filter-Bot/issues)

---

Made with ❤️ by [Rumal Gunawardana](https://github.com/rumalg123)