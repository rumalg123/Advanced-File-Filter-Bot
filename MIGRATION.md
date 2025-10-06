# Migration Guide: Premium Batch Links

This guide covers migrating to the new premium batch links feature.

## What's New

### Premium-Only Batch Links
- New commands: `/batch_premium`, `/pbatch_premium` (aliases: `/bprem`, `/pbprem`)
- Links that require premium membership to access
- Commands only work when global premium is enabled (`DISABLE_PREMIUM=false`)
- Protected content support with `protect_content=true`

## Database Changes

### New Collection: `batch_links`
The system automatically creates a new MongoDB collection to store premium batch links:

```javascript
{
  "_id": "BL-abc123def456",
  "source_chat_id": -1001234567890,
  "from_msg_id": 100,
  "to_msg_id": 200,
  "protected": true,
  "premium_only": true,  
  "created_by": 123456789,
  "created_at": "2025-01-12T10:30:00Z"
}
```

### Indexes Created
- `created_by_1_created_at_-1` - For user batch link queries
- `premium_only_1` - For premium filtering

## Code Changes

### New Dependencies
- Repository: `BatchLinkRepository`
- Enhanced: `FileStoreService` with premium batch support
- Enhanced: Deep link handler with `PBLINK-` prefix support

### Backward Compatibility
- All existing `/batch` and `/pbatch` commands continue to work unchanged
- Existing `DSTORE-` links remain fully functional
- No breaking changes to existing functionality

## Configuration

### No New Environment Variables Required
The premium batch links feature works with existing configuration:

- Requires `DISABLE_PREMIUM=false` for premium batch commands to work
- Premium batch links respect global premium settings
- When premium is disabled globally, premium batch commands are not available
- No additional configuration needed

### Access Control Precedence
1. **Global premium disabled** (`DISABLE_PREMIUM=true`) → Premium batch commands unavailable
2. **Premium batch link** (`premium_only=true`) → Requires premium membership (when global premium is enabled)
3. **Global premium enabled** → Requires premium for all batch access
4. **No restrictions** → Open access (when global premium is disabled)

## Deployment Steps

### 1. Database Migration
No manual migration needed - indexes are created automatically on startup.

### 2. Update Code
```bash
git checkout feature/premium-batch-links
# The feature is fully backward compatible
```

### 3. Restart Bot
The bot will automatically:
- Initialize the new `BatchLinkRepository`
- Create required database indexes
- Register new command handlers
- Update command menus

### 4. Verify Installation
Check that new commands appear in the bot menu:
- Premium users should see all new premium batch commands
- Commands should work for creating premium-only links

## Usage Examples

### Creating Premium Batch Links
**Note:** Premium batch commands only work when global premium is enabled (`DISABLE_PREMIUM=false`)

```bash
# Premium-only batch (admins can create, only premium users can access)
/batch_premium https://t.me/channel/100 https://t.me/channel/200

# Premium-only protected batch (non-forwardable)
/pbatch_premium https://t.me/channel/100 https://t.me/channel/200

# Short aliases
/bprem https://t.me/channel/100 https://t.me/channel/200
/pbprem https://t.me/channel/100 https://t.me/channel/200
```

### Link Format
Premium batch links use the new `PBLINK-` prefix:
```
https://t.me/yourbotusername?start=PBLINK-abc123def456
```

## Testing

### Manual Testing Scenarios
1. **Premium User Access**: Premium user should access all link types
2. **Non-Premium User**: Should be denied access to premium-only links
3. **Global Premium Disabled**: Premium-only links should still work for premium users
4. **Protected Content**: Protected batch links should be non-forwardable

### Automated Tests
Run the test suite:
```bash
python -m pytest tests/test_premium_batch_links.py -v
```

## Troubleshooting

### Common Issues

#### Premium Links Not Working
- Verify `BatchLinkRepository` is initialized in `FileStoreService`
- Check database connection and indexes
- Ensure `PBLINK-` handler is registered in deep link handler

#### Commands Not Appearing
- Restart the bot to refresh command menus
- Check admin permissions for command registration
- Verify handlers are properly registered

#### Database Errors
- Ensure MongoDB connection is stable
- Check that bot has write permissions to create collections
- Verify sufficient disk space for new collection

### Rollback Plan
If issues arise, you can safely rollback:

```bash
git checkout main
# Restart the bot
```

The `batch_links` collection can be dropped if needed:
```javascript
db.batch_links.drop()
```

## Support

For issues related to premium batch links:
1. Check bot logs for error messages
2. Verify database connectivity and permissions
3. Test with different user permission levels
4. Report issues with detailed logs and reproduction steps

## Future Enhancements

Planned improvements:
- Batch link analytics and usage statistics
- Expiration dates for premium links
- Bulk batch link management commands
- Integration with payment systems for automatic premium status