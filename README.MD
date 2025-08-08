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
- **📁 Multiple File Types**: Support for videos, audio, documents, and animations
- **🔄 Auto-Indexing**: Automatically index files from configured channels
- **💎 Premium System**: Tiered access with configurable daily limits for free users
- **🛡️ Rate Limiting**: Prevent spam and ensure quality of service
- **💾 Redis Caching**: Improved performance with distributed caching
- **🚀 uvloop Support**: Enhanced performance on Linux with uvloop event loop

### 🎯 Advanced Features
- **🔗 Connection Management**: Connect groups to manage filters privately
- **🎭 Custom Filters**: Create custom keyword-based auto-replies with buttons and alerts
- **📤 File Store**: Generate shareable and protected links for files
- **📊 Broadcasting**: Send messages to all users efficiently with progress tracking
- **🔐 Force Subscription**: Require users to join channels/groups
- **🗑️ Auto-Delete**: Automatically delete messages after specified time
- **📱 Inline Search**: Search files directly from any chat
- **📝 Content Requests**: Users can request content via #request in support group
- **🔍 Duplicate Detection**: Advanced duplicate detection using file hashes
- **⚙️ Bot Settings**: Comprehensive settings management via commands

### 👨‍💼 Admin Features
- **📈 Detailed Statistics**: User stats, file stats, cache stats, and system metrics
- **🚫 User Management**: Ban/unban users with reasons, add/remove premium
- **📢 Channel Management**: Add/remove/toggle channels for auto-indexing
- **⚙️ Bot Settings**: Manage all bot settings via /bsetting command
- **🔄 Auto-Updates**: Pull updates from upstream repository
- **💾 Cache Management**: Monitor and optimize cache usage
- **⚡ Performance Monitoring**: Real-time performance metrics
- **🖥️ Shell Access**: Execute shell commands (primary admin only)
- **🗑️ File Management**: Delete files from database by ID or keyword

## 📋 Requirements

- Python 3.9 or higher
- MongoDB 5.0 or higher
- Redis 6.0 or higher
- A Telegram Bot Token (from [@BotFather](https://t.me/botfather))
- API ID and Hash (from [telegram.org](https://my.telegram.org))
- Linux OS (recommended for uvloop optimization)

## 🛠️ Installation

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
cp sample.env .env

# Edit .env with your configuration
nano .env  # or use any text editor
```

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
# On Linux (with uvloop optimization)
bash start.sh

# Or directly with Python
python bot.py
```

## 🐳 Docker Deployment

### Using Docker Compose
```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

### Using Dockerfile
```bash
# Build image
docker build -t media-search-bot .

# Run container
docker run -d --name media-bot --env-file .env -p 8000:8000 media-search-bot
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
| `REDIS_URI` | Redis connection string | `redis://localhost:6379` |
| `ADMINS` | Admin user IDs (comma separated) | `123456789,987654321` |
| `LOG_CHANNEL` | Channel for bot logs | `-1001234567890` |

### Feature Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DISABLE_PREMIUM` | Disable premium features | `True` |
| `DISABLE_FILTER` | Disable filter features | `False` |
| `NON_PREMIUM_DAILY_LIMIT` | Daily file limit for free users | `10` |
| `MESSAGE_DELETE_SECONDS` | Auto-delete time in seconds | `300` |
| `USE_CAPTION_FILTER` | Search in file captions | `True` |
| `MAX_BTN_SIZE` | Maximum buttons per page | `10` |
| `PUBLIC_FILE_STORE` | Allow public file store access | `False` |
| `KEEP_ORIGINAL_CAPTION` | Keep original file captions | `True` |

### Optional Features

| Variable | Description | Required |
|----------|-------------|----------|
| `AUTH_CHANNEL` | Force subscription channel | Optional |
| `AUTH_GROUPS` | Force subscription groups | Optional |
| `FILE_STORE_CHANNEL` | Channels for file storage | Optional |
| `SUPPORT_GROUP_ID` | Support group for #request | Optional |
| `INDEX_REQ_CHANNEL` | Channel for index requests | Optional |
| `DELETE_CHANNEL` | Channel for file deletion | Optional |

## 📚 Usage Guide

### 🔹 User Commands

| Command | Description |
|---------|-------------|
| `/start` | Start the bot |
| `/help` | Show help message |
| `/about` | About the bot |
| `/stats` | Bot statistics |
| `/plans` | View premium plans |

### 🔍 Search Features
- **Direct Search**: Just send any text to search for files
- **Inline Search**: Use `@yourbotusername query` in any chat
- **Filter by Type**: Add file type after pipe: `query | video`
- **Send All**: Click "Send All Files" button to receive all search results

### 🔗 Connection Commands (Groups & Private)

| Command | Description |
|---------|-------------|
| `/connect` | Connect to a group |
| `/disconnect` | Disconnect from group |
| `/connections` | View all connections |

### 🎭 Filter Commands (if enabled)

| Command | Description |
|---------|-------------|
| `/add <keyword> <reply>` | Add a filter |
| `/filter <keyword> <reply>` | Alternative to add filter |
| `/filters` | View all filters |
| `/viewfilters` | Alternative to view filters |
| `/delf <keyword>` | Delete a filter |
| `/deletef <keyword>` | Alternative to delete filter |
| `/delallf` | Delete all filters |
| `/deleteallf` | Alternative to delete all |

### 📮 Request Feature
- In support group, use `#request <content_name>` to request content
- Bot will search and show results or forward request to admins
- Admins can mark requests as available, unavailable, uploaded, or rejected

### 👮 Admin Commands

#### User Management
| Command | Description |
|---------|-------------|
| `/users` | Get total users count |
| `/broadcast` | Broadcast message to all users |
| `/ban <user_id> [reason]` | Ban a user with optional reason |
| `/unban <user_id>` | Unban a user |
| `/addpremium <user_id>` | Add premium status |
| `/removepremium <user_id>` | Remove premium status |

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

#### System Commands
| Command | Description |
|---------|-------------|
| `/performance` | View performance metrics |
| `/log` | Get bot log file |
| `/restart` | Restart the bot |

#### Primary Admin Only
| Command | Description |
|---------|-------------|
| `/bsetting` | Open bot settings menu |
| `/shell <command>` | Execute shell command |

### 📤 File Store Commands

| Command | Description | Access |
|---------|-------------|--------|
| `/link` | Get shareable link for file | Admin/Public* |
| `/plink` | Get protected link | Admin/Public* |
| `/batch` | Create batch link for multiple files | Admin/Public* |
| `/pbatch` | Create protected batch link | Admin/Public* |

*Public if `PUBLIC_FILE_STORE=True`

## 🔧 Advanced Configuration

### Bot Settings Management
The bot includes a comprehensive settings management system accessible via `/bsetting` (primary admin only):

- **Dynamic Configuration**: Change bot settings without restarting
- **Category Organization**: Settings grouped by category
- **Live Updates**: Most settings apply immediately (some require restart)
- **Backup/Export**: Export and import settings configurations

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

2. **Database Scaling**
   - Use MongoDB replica sets
   - Enable sharding for very large datasets
   - Use read preference for search queries

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

### Railway/Render Deployment
1. Connect your GitHub repository
2. Add environment variables
3. Deploy with one click

## 🔒 Security Best Practices

1. **Environment Variables**
   - Never commit `.env` file
   - Use secrets management in production
   - Rotate tokens regularly

2. **Database Security**
   - Use authentication for MongoDB
   - Enable SSL/TLS connections
   - Regular backups

3. **Rate Limiting**
   - Configure appropriate limits
   - Monitor for abuse patterns
   - Implement IP-based limiting if needed

4. **Access Control**
   - Limit admin commands
   - Validate all user inputs
   - Use force subscription wisely

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
- Monitor database size
- Update dependencies regularly
- Check logs for errors
- Clear expired cache entries (automatic with Redis TTL)
- Review and optimize bot settings via `/bsetting`

### Backup Strategy
```bash
# MongoDB backup
mongodump --uri="your-connection-string" --out=backup/

# Export bot settings
# Use /bsetting menu to export settings

# Restore
mongorestore --uri="your-connection-string" backup/
```

## 🎯 Feature Details

### Auto-Delete System
- Messages automatically delete after configured time
- Configurable via `MESSAGE_DELETE_SECONDS`
- Applies to search results and file sends
- Helps keep chats clean

### Duplicate Detection
- Advanced hash-based duplicate detection
- Prevents storing same file multiple times
- Automatically updates file references
- Saves storage space

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