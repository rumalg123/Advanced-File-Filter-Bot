# Multi-Database Feature Guide

## Overview

The Advanced File Filter Bot now supports **multiple database connections** for automatic scaling and storage management. When one database approaches its storage limit, the bot automatically switches to the next database for new file storage while continuing to search across all databases.

## Key Features

✅ **Automatic Database Switching** - Bot switches to next database when current one reaches size limit  
✅ **Duplicate Detection** - Checks for duplicates across ALL databases before adding files  
✅ **Multi-Database Search** - Searches all databases simultaneously for comprehensive results  
✅ **Backward Compatibility** - Existing single-database setups continue to work without changes  
✅ **Admin Management** - Commands to monitor and manage multiple databases  

## Configuration

### Environment Variables

Add these variables to your `.env` file for multi-database support:

```env
# Primary database (keep existing)
DATABASE_URI=mongodb+srv://user:pass@cluster1.mongodb.net
DATABASE_NAME=PIRO

# Additional databases (comma-separated)
DATABASE_URIS=mongodb+srv://user:pass@cluster1.mongodb.net,mongodb+srv://user:pass@cluster2.mongodb.net,mongodb+srv://user:pass@cluster3.mongodb.net

# Database names for each URI (optional)
DATABASE_NAMES=PIRO_DB1,PIRO_DB2,PIRO_DB3

# Size limit before switching databases (in GB)
DATABASE_SIZE_LIMIT_GB=0.5

# Enable automatic switching (recommended)
DATABASE_AUTO_SWITCH=True
```

### Single Database Mode (Default)

If you don't add `DATABASE_URIS`, the bot works exactly as before:

```env
DATABASE_URI=mongodb://localhost:27017
DATABASE_NAME=PIRO
```

## Admin Commands

### Database Statistics
```
/dbstats
```
Shows storage usage, file counts, and status for all databases.

### Database Information  
```
/dbinfo
```
Displays detailed configuration and health information.

### Switch Write Database
```
/dbswitch <database_number>
```
Manually switch to a specific database for new files.
Example: `/dbswitch 2`

## How It Works

### File Storage Strategy
1. **New files** are saved to the current "write database"
2. When a database reaches the size limit, bot switches to next available database
3. **Search operations** query ALL databases simultaneously
4. **Duplicate detection** checks across ALL databases

### Database Selection Logic
- **Primary database** (from `DATABASE_URI`) is used first
- When it reaches `DATABASE_SIZE_LIMIT_GB`, switches to next in `DATABASE_URIS`
- If `DATABASE_AUTO_SWITCH=False`, manual switching via `/dbswitch` required

### Example Scenario
```
Database 1: 0.45GB / 0.5GB (90% - will switch soon)
Database 2: 0.23GB / 0.5GB (46% - available)  
Database 3: 0.00GB / 0.5GB (0% - empty)
```

When Database 1 hits 0.5GB, new files automatically go to Database 2.

## Migration Guide

### For Existing Setups
**✅ No action required!** Your current setup continues working unchanged.

### To Enable Multi-Database
1. Add `DATABASE_URIS` with additional MongoDB connection strings
2. Optionally add `DATABASE_NAMES` for custom database names
3. Set `DATABASE_SIZE_LIMIT_GB` (default: 0.5GB)
4. Restart the bot

### Example Migration
```env
# Before (single database)
DATABASE_URI=mongodb://localhost:27017
DATABASE_NAME=PIRO

# After (multi-database)  
DATABASE_URI=mongodb://localhost:27017
DATABASE_NAME=PIRO
DATABASE_URIS=mongodb://localhost:27017,mongodb://new-server:27017
DATABASE_NAMES=PIRO,PIRO_BACKUP
DATABASE_SIZE_LIMIT_GB=0.5
```

## Benefits

### Storage Scaling
- **Free MongoDB Atlas**: 512MB limit per cluster
- **Multiple clusters**: 512MB × N clusters = more storage
- **Automatic switching**: No manual intervention required

### Performance
- **Concurrent searches**: All databases queried simultaneously  
- **Load distribution**: Reads distributed across multiple servers
- **Redundancy**: Files accessible even if one database is down

### Cost Efficiency
- Use multiple **free MongoDB Atlas clusters**
- Scale storage without paid plans
- Pay-per-use pricing across multiple accounts

## Monitoring

The bot provides comprehensive monitoring:

- **Real-time statistics** via `/dbstats`
- **Automatic alerts** when databases reach capacity
- **Health monitoring** with automatic failover
- **Usage tracking** per database

## Troubleshooting

### Common Issues

**Q: Bot says "Multi-database mode not enabled"**  
A: Add `DATABASE_URIS` to your `.env` file with additional MongoDB URIs.

**Q: Database switching not working**  
A: Check `DATABASE_AUTO_SWITCH=True` and ensure databases are accessible.

**Q: Duplicate files across databases**  
A: This shouldn't happen - the bot checks ALL databases for duplicates. If it does, report as a bug.

**Q: Search results incomplete**  
A: Verify all databases in `DATABASE_URIS` are accessible and contain indexed files.

### Database Connection Issues

If a database becomes unavailable:
1. Bot marks it as inactive
2. Continues operating with remaining databases  
3. Logs warnings in bot logs
4. Use `/dbstats` to check database status

## Best Practices

### Database Setup
- Use **similar database configurations** across all clusters
- Ensure **network connectivity** from your bot server to all databases
- Set **appropriate size limits** based on your storage plan

### Monitoring
- Check `/dbstats` regularly to monitor usage
- Set up alerts when databases reach 80% capacity
- Plan for additional databases before current ones fill

### Backup Strategy  
- Multi-database provides redundancy, but doesn't replace backups
- Consider regular exports using `mongodump`
- Test database recovery procedures

---

**Need help?** Join our [support group](https://t.me/your_support_group) or open an issue on [GitHub](https://github.com/rumalg123/Advanced-File-Filter-Bot/issues).