# 🔧 Configuration Guide

This document describes all available configuration options for the Telegram Media Search Bot using the centralized Pydantic Settings system.

## 📋 Quick Start

1. Copy `.env.example` to `.env`
2. Fill in required values (marked with ⚠️)
3. Customize optional settings as needed
4. Run the bot with `python bot.py`

## 🗂️ Configuration Structure

The configuration is organized into logical sections using Pydantic Settings:

### 📡 Telegram Configuration (`TelegramConfig`)

Required Telegram API credentials and session settings.

| Variable | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `API_ID` | int | ⚠️ Yes | 0 | Telegram API ID from my.telegram.org |
| `API_HASH` | str | ⚠️ Yes | '' | Telegram API hash from my.telegram.org |
| `BOT_TOKEN` | str | ⚠️ Yes | '' | Bot token from @BotFather |
| `SESSION` | str | No | 'Media_search' | Session name for the bot |

### 🗃️ Database Configuration (`DatabaseConfig`)

MongoDB connection and multi-database settings.

| Variable | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `DATABASE_URI` | str | ⚠️ Yes | '' | Primary MongoDB connection URI |
| `DATABASE_NAME` | str | No | 'PIRO' | Primary database name |
| `COLLECTION_NAME` | str | No | 'FILES' | Collection name for media files |
| `DATABASE_SIZE_LIMIT_GB` ✏️ | float | No | 0.5 | Database size limit in GB |
| `DATABASE_AUTO_SWITCH` ✏️ | bool | No | true | Enable automatic database switching |
| `DATABASE_URIS` | str | No | '' | Additional database URIs (comma-separated) |
| `DATABASE_NAMES` | str | No | '' | Additional database names (comma-separated) |
| `DATABASE_MAX_FAILURES` ✏️ | int | No | 5 | Max failures before circuit breaker opens |
| `DATABASE_RECOVERY_TIMEOUT` ✏️ | int | No | 300 | Recovery timeout in seconds |
| `DATABASE_HALF_OPEN_CALLS` ✏️ | int | No | 3 | Max calls in half-open state |

✏️ = Can be changed via bot `/settings` command

### 🔴 Redis Configuration (`RedisConfig`)

Redis cache configuration.

| Variable | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `REDIS_URI` | str | ⚠️ Yes | '' | Redis connection URI |

### 🖥️ Server Configuration (`ServerConfig`)

Web server and worker settings.

| Variable | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `PORT` | int | No | 8000 | Server port (1-65535) |
| `WORKERS` | int | No | 50 | Number of workers |

### 🎛️ Feature Configuration (`FeatureConfig`)

Feature toggles and limits.

| Variable | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `USE_CAPTION_FILTER` | bool | No | true | Enable caption filtering |
| `DISABLE_PREMIUM` | bool | No | true | Disable premium features |
| `DISABLE_FILTER` | bool | No | false | Disable filtering entirely |
| `PUBLIC_FILE_STORE` | bool | No | false | Enable public file store |
| `KEEP_ORIGINAL_CAPTION` | bool | No | true | Keep original file captions |
| `USE_ORIGINAL_CAPTION_FOR_BATCH` | bool | No | true | Use original captions in batch mode |
| `PREMIUM_DURATION_DAYS` | int | No | 30 | Premium subscription duration in days |
| `NON_PREMIUM_DAILY_LIMIT` | int | No | 10 | Daily file limit for free users |
| `PREMIUM_PRICE` | string | No | $1 | Premium subscription price with currency (e.g., $1, LKR 450, INR 450) |
| `MESSAGE_DELETE_SECONDS` | int | No | 300 | Auto-delete timeout in seconds |
| `MAX_BTN_SIZE` | int | No | 12 | Maximum button size |
| `REQUEST_PER_DAY` | int | No | 3 | Requests per day limit |
| `REQUEST_WARNING_LIMIT` | int | No | 5 | Warning limit for requests |

### 📢 Channel Configuration (`ChannelConfig`)

Channel and group IDs and authentication.

| Variable | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `LOG_CHANNEL` | int | No | 0 | Log channel ID |
| `INDEX_REQ_CHANNEL` | int | No | 0 | Index request channel ID (uses LOG_CHANNEL if 0) |
| `FILE_STORE_CHANNEL` | str | No | '' | File store channel |
| `DELETE_CHANNEL` | int | No | None | Delete channel ID |
| `REQ_CHANNEL` | int | No | 0 | Request channel ID (uses LOG_CHANNEL if 0) |
| `SUPPORT_GROUP_ID` | int | No | None | Support group ID |
| `AUTH_CHANNEL` | str | No | None | Auth channel |
| `AUTH_GROUPS` | str | No | '' | Auth groups (comma-separated) |
| `AUTH_USERS` | str | No | '' | Auth users (comma-separated) |
| `ADMINS` | str | No | '' | Admin user IDs (comma-separated) |
| `CHANNELS` | str | No | '0' | Channel IDs (comma-separated) |
| `PICS` | str | No | '' | Picture URLs (comma-separated) |

### 💬 Message Configuration (`MessageConfig`)

Message templates and content customization.

| Variable | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `CUSTOM_FILE_CAPTION` | str | No | '' | Custom file caption template |
| `BATCH_FILE_CAPTION` | str | No | '' | Batch file caption template |
| `AUTO_DELETE_MESSAGE` | str | No | Default template | Auto-delete message template |
| `START_MESSAGE` | str | No | Default template | Start command message template |
| `SUPPORT_GROUP_URL` | str | No | '' | Support group URL |
| `SUPPORT_GROUP_NAME` | str | No | 'Support Group' | Support group name |
| `PAYMENT_LINK` | str | No | Default link | Payment link |

### 🔄 Update Configuration (`UpdateConfig`)

Auto-update system settings.

| Variable | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `UPDATE_REPO` | str | No | GitHub repo URL | Update repository URL |
| `UPDATE_BRANCH` | str | No | 'main' | Update branch |

### ⚡ Concurrency Configuration

Optional concurrency limits for performance tuning.

| Variable | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `CONCURRENCY_TELEGRAM_SEND` | int | No | 10 | Max concurrent Telegram send operations |
| `CONCURRENCY_TELEGRAM_FETCH` | int | No | 15 | Max concurrent Telegram fetch operations |
| `CONCURRENCY_DATABASE_WRITE` | int | No | 20 | Max concurrent database write operations |
| `CONCURRENCY_DATABASE_READ` | int | No | 30 | Max concurrent database read operations |
| `CONCURRENCY_FILE_PROCESSING` | int | No | 5 | Max concurrent file processing operations |
| `CONCURRENCY_BROADCAST` | int | No | 3 | Max concurrent broadcast operations |
| `CONCURRENCY_INDEXING` | int | No | 8 | Max concurrent indexing operations |

## 🔧 Usage Examples

### Basic Configuration Access

```python
from config import settings

# Access nested configuration
api_id = settings.telegram.api_id
database_uri = settings.database.uri
redis_uri = settings.redis.uri

# Feature flags
if settings.features.disable_premium:
    # Premium features disabled
    pass

# Parsed lists
admin_ids = settings.channels.get_admin_list()
channel_ids = settings.channels.get_channel_list()
```

### Environment Detection

```python
from config import settings

if settings.is_development:
    # Development-specific code
    pass

if settings.is_docker:
    # Docker-specific configuration
    pass

if settings.is_kubernetes:
    # Kubernetes-specific configuration
    pass
```

### Configuration Validation

```python
from config import settings

# Validate all configuration sections
errors = settings.validate_all()
if errors:
    for error in errors:
        print(f"Config error: {error}")
    exit(1)
```

## 📝 Template Placeholders

Some configuration values support template placeholders:

### Auto-Delete Message Template
- `{content_type}` - Type of content (file, photo, etc.)
- `{minutes}` - Minutes until deletion

### Custom Caption Templates  
- `{filename}` - Original filename
- `{size}` - Formatted file size

## 🛠️ Advanced Configuration

### Environment Overrides

Any setting can be overridden with environment variables:

```bash
# Override specific settings
export DATABASE_NAME="production_db"
export CONCURRENCY_TELEGRAM_SEND=15
export FEATURES__DISABLE_PREMIUM=false  # Note: double underscore for nested
```

### Configuration Files

Settings are loaded in this order (later sources override earlier):
1. Default values in code
2. `.env` file
3. Environment variables
4. Command-line arguments (if implemented)

### Validation

The configuration system automatically validates:
- Required fields are present
- Numeric ranges are valid
- URLs are properly formatted
- Lists parse correctly

## 🚨 Security Notes

- Never commit `.env` files with production credentials
- Use strong, unique API tokens and database passwords
- Restrict database and Redis access by IP when possible
- Use HTTPS URIs for production databases
- Rotate credentials regularly

## 🔍 Troubleshooting

### Common Issues

**"API_ID is required" Error:**
- Check that `API_ID` is set in `.env`
- Ensure the value is a valid integer

**"DATABASE_URI is required" Error:**
- Verify `DATABASE_URI` is set in `.env`
- Test the connection string manually

**Configuration Not Loading:**
- Check `.env` file exists in project root
- Verify file permissions allow reading
- Check for syntax errors in `.env`

### Debug Configuration

```python
from config import settings
import json

# Print current configuration (masks sensitive values)
config_dict = settings.dict()
# Remove sensitive keys for logging
sensitive_keys = ['api_hash', 'bot_token', 'database_uri', 'redis_uri']
for key in sensitive_keys:
    if key in config_dict:
        config_dict[key] = "***MASKED***"

print(json.dumps(config_dict, indent=2))
```

---

*Last updated: Phase 13 Implementation*