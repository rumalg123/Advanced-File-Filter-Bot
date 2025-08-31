# Multi-Database System Guide 🚀

This comprehensive guide explains the enterprise-grade multi-database system for automatic scaling, fault tolerance, and intelligent load balancing in your Telegram Media Bot.

## 📋 Overview

The multi-database system provides:
- **🎯 Smart Database Selection**: AI-powered load balancing based on usage, health, and performance
- **🛡️ Circuit Breaker Protection**: Automatic fault tolerance with 5-failure threshold and auto-recovery
- **⚡ Real-time Optimization**: 30-second cache vs 5-minute for critical switching decisions
- **🔒 Thread-safe Operations**: Race condition protection with async locks
- **🚨 Emergency Handling**: Graceful degradation when all databases reach capacity
- **🔍 Cross-database Search**: Proper pagination and sorting across all databases
- **♻️ Auto-recovery**: Failed databases automatically recover when they come back online

## ⚙️ Configuration

### Environment Variables

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

### MongoDB Atlas Free Tier Setup (Cost: $0)

Use multiple MongoDB Atlas free clusters (512MB each) for unlimited storage:

```bash
# Example: 3 free clusters = ~1.5GB total storage
DATABASE_URIS=mongodb+srv://user1:pass1@cluster1.mongodb.net,mongodb+srv://user2:pass2@cluster2.mongodb.net,mongodb+srv://user3:pass3@cluster3.mongodb.net
DATABASE_NAMES=MediaBot_Main,MediaBot_Backup,MediaBot_Archive
DATABASE_SIZE_LIMIT_GB=0.45  # Stay under 512MB limit with buffer
DATABASE_AUTO_SWITCH=True
```

## 🎮 Admin Commands

### 📊 Database Statistics
```
/dbstats
```
**Example Output:**
```
📊 Database Statistics

Database 1 (MAIN_DB) - Primary ✅
├─ Size: 0.45GB / 0.5GB (90%)
├─ Files: 12,450
├─ Circuit: CLOSED (0 failures)
└─ Status: Active

Database 2 (BACKUP_DB) - Secondary ✅  
├─ Size: 0.23GB / 0.5GB (46%)
├─ Files: 6,780
├─ Circuit: CLOSED (0 failures)
└─ Status: Active

Database 3 (ARCHIVE_DB) - Backup ✅
├─ Size: 0.00GB / 0.5GB (0%)
├─ Files: 0
├─ Circuit: CLOSED (0 failures)
└─ Status: Active

🎯 Current Write DB: Database 2 (Smart Selection Active)
🛡️ Circuit Breakers: All Healthy
⚡ Real-time Stats: Enabled (30s cache)
```

### 🔍 Database Information
```
/dbinfo
```
Shows technical details:
- Connection health and response times
- Circuit breaker states and failure counts
- Database indexes and optimization status
- Performance metrics and connection pool usage

### 🔄 Manual Database Switching
```
/dbswitch <number>
```
**Examples:**
- `/dbswitch 1` - Switch to first database
- `/dbswitch 3` - Switch to third database

**Note**: Manual switching temporarily overrides smart selection

## 🧠 Smart Database Selection Algorithm

### Multi-Factor Scoring System
The system evaluates databases using weighted factors:

```
🎯 Scoring Factors (Total: 100%):
├─ Storage Usage (40%): Lower usage = higher score
├─ Circuit Health (30%): Healthy databases preferred  
├─ Connection Stability (15%): Based on success/failure ratio
└─ Current DB Bonus (15%): Avoid unnecessary switching
```

### Example Decision Process:
```
🧠 Smart database selection - evaluating databases:
  DB1 (MAIN_DB): Score=0.247 Usage=456MB(91.2%) Circuit=CLOSED Failures=0
  DB2 (BACKUP_DB): Score=0.920 Usage=123MB(24.6%) Circuit=CLOSED Failures=0
  DB3 (PROBLEM_DB): Score=0.000 Usage=445MB(89.0%) Circuit=OPEN Failures=5

🎯 Smart switch: DB1 -> DB2 (MAIN_DB -> BACKUP_DB) - Score improved: 0.920

Decision: Choose DB2 (highest score, low usage, healthy)
```

## 🛡️ Circuit Breaker System

### How It Works
```
🔴 CLOSED → Normal operation (healthy)
    ↓ (5 consecutive failures)
🟡 OPEN → Reject requests (5-minute timeout)  
    ↓ (timeout expired)
🟢 HALF_OPEN → Test recovery (limited requests)
    ↓ (success) OR (failure)
🔴 CLOSED   🟡 OPEN
```

### Configuration
```bash
# Circuit breaker settings (with defaults)
DATABASE_MAX_FAILURES=5        # Failures before opening circuit
DATABASE_RECOVERY_TIMEOUT=300  # Seconds before testing recovery
DATABASE_HALF_OPEN_CALLS=3     # Max calls in HALF_OPEN state
```

### Example Circuit Breaker Events:
```log
2025-01-15 10:30:45 - Database BACKUP_DB failure 3/5: Connection timeout
2025-01-15 10:31:12 - Database BACKUP_DB failure 5/5: Connection refused
2025-01-15 10:31:12 - 🔴 Circuit breaker OPENED for database BACKUP_DB after 5 failures
2025-01-15 10:36:12 - Circuit breaker for BACKUP_DB moved to HALF_OPEN (testing recovery)
2025-01-15 10:36:15 - Circuit breaker for BACKUP_DB CLOSED (recovery successful)
```

## ⚡ Performance Features

### Real-time Stats Updates
- **Write operations**: Force fresh stats (0-second cache)
- **Read operations**: 30-second cache vs 5-minute default
- **Smart switching**: Always uses real-time data for decisions

### Thread-safe Operations
```python
# All database switching operations protected by async locks
async with self._switch_lock:
    # Thread-safe database selection and switching
    optimal_db = await get_optimal_write_database()
```

### Cross-database Search Optimization
```python
# FIXED: Proper pagination across databases
1. Get ALL matching results from each database
2. Combine and sort ALL results together
3. THEN apply skip/limit to final sorted results

# Before: Wrong results due to per-database pagination
# After: Correct cross-database result ordering
```

## 🚨 Emergency Handling

When all databases reach capacity:

```log
🚨 CRITICAL: All databases at capacity! Implementing emergency measures...

Emergency fallback: Using least full database 2 (BACKUP_DB) - 0.48GB/0.5GB (96%)

ADMIN ACTION REQUIRED:
1. Add more databases to DATABASE_URIS
2. Increase DATABASE_SIZE_LIMIT_GB if under MongoDB limits  
3. Consider database cleanup/archiving
4. Monitor storage usage closely
```

## 📊 Monitoring & Analytics

### Database Health Dashboard
Access via `/dbstats` shows:
- **Real-time usage**: Storage and file counts
- **Circuit breaker status**: Health of each database
- **Performance metrics**: Response times and success rates
- **Smart selection**: Current optimization decisions

### Performance Monitoring
```bash
# Monitor via /performance command
🚀 Performance Metrics:
├─ Event Loop: uvloop (2.4x faster than asyncio)
├─ Database Connections: 200 (with uvloop) / 100 (without)
├─ Redis Connections: 40 (with uvloop) / 20 (without)
├─ Circuit Breakers: All Healthy (0 open circuits)
└─ Smart Selection: Active (DB2 selected, score: 0.920)
```

## 🔧 Migration from Single Database

### Seamless Migration Process
1. **Existing setup continues working** - No downtime
2. **Add multi-database configuration**:
   ```bash
   # Keep existing single database config
   DATABASE_URI=mongodb://localhost:27017
   DATABASE_NAME=PIRO
   
   # Add multi-database config
   DATABASE_URIS=mongodb://localhost:27017,mongodb://new-cluster:27017
   DATABASE_NAMES=PIRO,PIRO_NEW
   DATABASE_SIZE_LIMIT_GB=2.0
   DATABASE_AUTO_SWITCH=True
   ```
3. **New files automatically use multi-database system**
4. **Existing files remain accessible and searchable**

## 💡 Best Practices

### MongoDB Atlas Free Tier Optimization
```bash
# Optimal configuration for free tier (512MB limit)
DATABASE_SIZE_LIMIT_GB=0.45    # Buffer for indexes and metadata
DATABASE_AUTO_SWITCH=True      # Automatic switching when full

# Multiple free clusters strategy
DATABASE_URIS=mongodb+srv://...cluster1...,mongodb+srv://...cluster2...,mongodb+srv://...cluster3...
```

### Performance Optimization
- **Use uvloop on Linux** for 2-4x performance boost
- **Enable connection pooling**: 200 connections with uvloop
- **Monitor circuit breakers**: Check `/dbstats` regularly
- **Real-time decision making**: System uses fresh stats for switching

### Security Best Practices
- **Separate credentials** for each database cluster
- **Network isolation** where possible
- **Regular credential rotation**
- **Monitor connection attempts** in logs

## 🛠️ Troubleshooting Guide

### Circuit Breaker Issues
```bash
# Check circuit breaker status
/dbstats

# If database shows "Circuit: OPEN"
1. Check database connectivity
2. Wait 5 minutes for auto-recovery
3. Monitor logs for specific error messages
4. Use /dbswitch to temporarily use different database
```

### Performance Issues
```bash
# Identify slow databases
/dbinfo  # Check response times

# Force fresh stats update
/dbstats  # Automatically uses real-time stats

# Monitor smart selection decisions
# Check logs for "🧠 Smart database selection" entries
```

### Storage Issues
```bash
# Check current usage
/dbstats

# Emergency: All databases full
1. Increase DATABASE_SIZE_LIMIT_GB if possible
2. Add more databases to DATABASE_URIS
3. Clean up old files: /deleteall <criteria>
4. Consider archiving strategy
```

## 📈 Scaling Examples

### Small Scale (3 Free Atlas Clusters)
```bash
DATABASE_URIS=cluster1,cluster2,cluster3
DATABASE_NAMES=Bot_Main,Bot_Backup,Bot_Archive
DATABASE_SIZE_LIMIT_GB=0.45
# Total: ~1.35GB storage, Cost: $0
```

### Medium Scale (Mixed Setup)
```bash
DATABASE_URIS=local_mongodb,atlas_cluster1,atlas_cluster2,atlas_cluster3
DATABASE_NAMES=Local_Fast,Cloud_Main,Cloud_Backup,Cloud_Archive
DATABASE_SIZE_LIMIT_GB=2.0
# Total: ~8GB storage, Cost: $0-50/month
```

### Large Scale (Production)
```bash
DATABASE_URIS=mongodb+srv://prod1,mongodb+srv://prod2,mongodb+srv://prod3,mongodb+srv://prod4
DATABASE_NAMES=Prod_Q1_2024,Prod_Q2_2024,Prod_Q3_2024,Prod_Q4_2024
DATABASE_SIZE_LIMIT_GB=10.0
# Total: ~40GB storage, Cost: $200-400/month
```

## 🚀 Advanced Features

### Automatic Recovery
- **Failed databases** automatically marked inactive
- **5-minute recovery window** before testing
- **Gradual recovery** via HALF_OPEN state
- **Automatic reactivation** when healthy

### Load Balancing Algorithm
- **Multi-factor analysis**: Usage, health, stability, switching cost
- **Proactive switching**: Triggers at 85% capacity
- **Emergency handling**: Graceful degradation under failure
- **Real-time optimization**: Always uses fresh database stats

### Cross-Database Operations
- **Unified search**: All databases queried simultaneously
- **Proper pagination**: Results sorted before pagination
- **Duplicate prevention**: Global uniqueness across all databases
- **Consistent indexing**: Indexes created on all databases

## 🎯 Key Benefits Summary

### Enterprise-Grade Features
- ✅ **Zero-cost scaling** with MongoDB Atlas free tier
- ✅ **Automatic fault tolerance** with circuit breaker pattern
- ✅ **Intelligent load balancing** with multi-factor scoring
- ✅ **Thread-safe operations** with race condition protection
- ✅ **Real-time optimization** with smart cache management
- ✅ **Graceful degradation** under failure conditions
- ✅ **Auto-recovery capabilities** when databases come online

### Production Ready
- ✅ **Comprehensive monitoring** with admin commands
- ✅ **Detailed logging** for troubleshooting and analytics
- ✅ **Backward compatibility** with existing single-database setups
- ✅ **Seamless migration** without downtime
- ✅ **Emergency handling** when all databases reach capacity
- ✅ **Cross-database consistency** with duplicate prevention

This enterprise-grade multi-database system provides **unlimited scaling**, **automatic fault tolerance**, and **intelligent optimization** while maintaining **zero-cost scaling** with MongoDB Atlas free tier clusters.