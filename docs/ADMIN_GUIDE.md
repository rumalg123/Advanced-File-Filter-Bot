# 📋 Admin Guide - Telegram Media Search Bot

This comprehensive guide covers all administrative features, system monitoring, and troubleshooting for bot administrators.

## 🚀 Quick Start for Admins

### Essential Commands
```bash
/start - Bot introduction and help
/stats - Comprehensive bot statistics  
/broadcast - Send messages to all users
/bsetting - Bot settings management
/users - User management interface
/channels - Channel management
/shell - Execute system commands (owner only)
```

---

## 🔧 System Administration

### Bot Settings Management (`/bsetting`)

The bot includes a comprehensive settings system accessible via `/bsetting` command:

#### Core Settings
- **Force Subscription**: Require users to join specific channels
- **Premium System**: Enable/disable premium features and daily limits
- **Auto-Delete**: Configure automatic message deletion
- **Request System**: Manage content request functionality
- **File Limits**: Set daily file limits for free users

#### Message Templates
- **Start Message**: Customize the welcome message (HTML supported)
- **Auto-Delete Message**: Custom deletion notification templates
- **Force Sub Message**: Subscription requirement messages

#### Advanced Configuration
- **Cache Settings**: Configure Redis TTL values for different data types
- **Rate Limiting**: Set request limits per user/time period
- **Database Preferences**: Multi-database routing and limits

### Statistics and Monitoring (`/stats`)

#### System Metrics
```
📊 Bot Statistics:
- Total Users: 12,345
- Premium Users: 1,234 (10%)
- Total Files: 1,234,567
- Database Size: 2.5 GB
```

#### Cache Performance
```
💾 Cache Performance:
- User Cache: 85% hit rate
- Premium Cache: 92% hit rate  
- Channel Cache: 78% hit rate
- Link Cache: 81% hit rate
```

#### Database Health
```
🗃️ Database Status:
- Active Connections: 25/100
- Query Response Time: 45ms avg
- Index Efficiency: 94%
- Storage Usage: 75% (2.5GB/3.3GB)
```

---

## 👥 User Management

### User Commands (`/users`)

#### Ban Management
```bash
# Ban user with reason
/ban 123456789 Spamming channels

# Unban user
/unban 123456789

# View ban details
/userinfo 123456789
```

#### Premium Management
```bash
# Add premium status
/addpremium 123456789

# Remove premium status  
/rempremium 123456789

# Bulk premium operations
/bulkpremium @username1 @username2 @username3
```

#### User Analytics
- **Registration Trends**: New users per day/week/month
- **Activity Patterns**: Most active users and usage times
- **Geographic Distribution**: User locations (if available)
- **Premium Conversion**: Free to premium conversion rates

---

## 📡 Broadcasting System

### Enhanced Broadcasting Features

#### HTML Formatting Support
```html
<b>Important Update!</b>
<i>New features available:</i>
<code>Enhanced search</code>
<a href="https://example.com">Learn More</a>
```

#### Broadcast Controls
- **Preview Mode**: See exactly how messages will appear
- **Confirmation Dialog**: Prevent accidental broadcasts
- **Progress Tracking**: Real-time delivery statistics
- **Emergency Stop**: Cancel broadcast mid-delivery

#### Broadcast Analytics
```
📊 Broadcast Statistics:
- Messages Sent: 10,234
- Delivery Rate: 96.5%
- Failed Deliveries: 356
- Average Delivery Time: 2.3s
```

---

## 🗃️ Database Management

### Multi-Database Architecture

The bot supports multiple MongoDB databases with automatic scaling:

#### Database Selection Strategy
1. **Size-based routing**: Automatically switch when database reaches limit
2. **Performance-based**: Route based on response times
3. **Manual override**: Admin can force specific database usage

#### Database Monitoring
```bash
/dbstats - View all database statistics
/dbswitch - Switch to different database
/dbmaintenance - Run maintenance tasks
```

### Index Management

#### Critical Indexes for Performance
```javascript
// File search performance
db.media_files.createIndex({"file_name": "text"})

// User queries optimization  
db.media_files.createIndex({"user_id": 1})

// Message reference lookups
db.media_files.createIndex({"chat_id": 1, "message_id": 1})

// Premium status checks
db.users.createIndex({"user_id": 1, "is_premium": 1})
```

---

## 🔍 Channel Management

### Auto-Indexing Configuration (`/channels`)

#### Channel Operations
```bash
# Add channel for auto-indexing
/addchannel -1001234567890

# Remove channel
/remchannel -1001234567890

# Toggle channel indexing
/togglechannel -1001234567890

# View channel statistics
/channelstats -1001234567890
```

#### Indexing Performance
- **Files per Hour**: Average indexing speed
- **Duplicate Detection**: Efficiency of duplicate filtering
- **Error Rates**: Failed indexing attempts
- **Storage Impact**: Storage used per channel

---

## ⚡ Performance Optimization

### Caching Strategy

#### Cache Layers
1. **User Cache**: User profiles and preferences (5 min TTL)
2. **Premium Cache**: Premium status checks (10 min TTL)
3. **Channel Cache**: Channel metadata (30 min TTL)
4. **Link Cache**: Generated file links (15 min TTL)

#### Cache Management
```bash
# View cache statistics
/cachestats

# Clear specific cache
/clearcache user_cache

# Optimize cache performance
/optimizecache
```

### Rate Limiting

#### Multi-tier Rate Limiting
```yaml
Global Limits:
  - API Calls: 10 concurrent max
  - Per Chat: 3 concurrent max
  
User Limits:
  - Free Users: 50 files/day
  - Premium Users: Unlimited
  - Search Queries: 100/hour
```

---

## 🛠️ Troubleshooting

### Common Issues

#### High Memory Usage
```bash
# Check memory usage
/system memory

# Clear caches
/clearcache all

# Restart services
/restart
```

#### Database Performance Issues
```bash
# Check slow queries
/dbslow

# Rebuild indexes
/reindex

# Optimize database
/dboptimize
```

#### Broadcasting Problems
```bash
# Check failed deliveries
/broadcast status

# Retry failed broadcasts
/broadcast retry

# View broadcast logs
/logs broadcast
```

### Error Monitoring

#### Structured Error Logging
```json
{
  "event": "error",
  "error_code": "FLOOD_WAIT_EXCEEDED", 
  "correlation_id": "req_123456",
  "user_id": 123456789,
  "details": {
    "retry_after": 60,
    "attempt": 3
  }
}
```

#### Error Response Schema
```json
{
  "ok": false,
  "code": "PREMIUM_REQUIRED",
  "message": "This content requires premium membership",
  "correlation_id": "req_789012",
  "details": {
    "user_id": 123456789,
    "required_premium": true
  }
}
```

---

## 🔐 Security

### Access Controls

#### Admin Levels
1. **Owner**: Full system access including shell commands
2. **Admin**: Bot management and user operations
3. **Moderator**: Limited user management

#### Security Features
- **Correlation IDs**: Track all user interactions
- **Audit Logging**: Complete admin action history
- **Rate Limiting**: Prevent abuse and spam
- **Input Validation**: Comprehensive input sanitization

### Secure Shell Access

```bash
# Execute system commands (owner only)
/shell ls -la

# View system resources
/shell top -n 1

# Check disk usage
/shell df -h
```

---

## 📊 Analytics and Reporting

### Usage Analytics

#### Daily Reports
```
📈 Daily Usage Report:
- New Users: 234
- Files Shared: 5,678  
- Searches Performed: 12,345
- Premium Conversions: 12
```

#### Weekly Trends
- **User Growth**: Registration patterns
- **Content Popularity**: Most requested files
- **Geographic Insights**: User distribution
- **Performance Metrics**: System response times

### Export Functions

#### Data Export
```bash
# Export user statistics
/export users --format csv --period 30d

# Export file statistics  
/export files --format json --channel all

# Export system logs
/export logs --level error --period 7d
```

---

## 🚨 Emergency Procedures

### System Recovery

#### Backup Procedures
```bash
# Create system backup
/backup create --type full

# Restore from backup
/backup restore --file backup_20240101.tar.gz

# Verify backup integrity
/backup verify --file backup_20240101.tar.gz
```

#### Emergency Shutdown
```bash
# Graceful shutdown
/shutdown --grace-period 60

# Force shutdown
/shutdown --force

# Restart with safe mode
/restart --safe-mode
```

### Incident Response

1. **Identify Issue**: Use monitoring tools and error logs
2. **Assess Impact**: Check affected user count and services
3. **Implement Fix**: Apply temporary or permanent solutions
4. **Monitor Recovery**: Ensure system stability
5. **Post-Incident**: Document lessons learned

---

## 📚 Best Practices

### Daily Operations
- [ ] Review error logs and system alerts
- [ ] Monitor cache performance and hit rates
- [ ] Check database performance metrics
- [ ] Verify backup completion
- [ ] Review user activity for anomalies

### Weekly Tasks
- [ ] Analyze usage trends and patterns
- [ ] Review and optimize slow queries
- [ ] Update channel indexing performance
- [ ] Check system resource usage
- [ ] Plan capacity scaling if needed

### Monthly Reviews
- [ ] Security audit and access review
- [ ] Performance optimization analysis
- [ ] Database maintenance and cleanup
- [ ] Update documentation and procedures
- [ ] Review and adjust rate limiting rules

---

## 📞 Support and Resources

### Getting Help
- **Documentation**: Check this guide and README.md
- **Error Logs**: Review system logs for specific issues
- **Community**: Join the developer support channels
- **GitHub Issues**: Report bugs and feature requests

### Useful Resources
- [PyroFork Documentation](https://pyrofork.wulan17.dev/)
- [MongoDB Performance Best Practices](https://docs.mongodb.com/manual/administration/production-checklist-development/)
- [Redis Configuration Guide](https://redis.io/topics/admin)

---

*This guide is updated regularly. Last updated: Phase 7 Implementation*