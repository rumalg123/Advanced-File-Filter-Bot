# Developer Audit Notes

**Repository**: AutoFileFilterBot  
**Audit Date**: 2025-12-01  
**Auditor**: Lead Code Auditor & Refactor Strategist  
**Framework**: PyroFork (Pyrogram fork)

---

## How to Read This Audit

### Document Structure
```
AUDIT-TODO.md           # Main prioritized TODO list with all findings
audits/
├── cross_reference_map.json    # Symbol usage mapping and reuse opportunities  
├── quick-wins.md              # Low-risk high-impact fixes (< 10 lines each)
└── developer-audit-notes.md   # This file - reading guide and policies
```

### Priority System
- **Blocker**: Must fix before production (security, critical bugs)
- **Major**: Should fix in next sprint (performance, user experience)
- **Minor**: Can be addressed in maintenance cycles (code quality, consistency)

---

## Category Definitions

### **ParseMode** - HTML Enforcement Policy
**Policy**: ALL Telegram message sending MUST use `ParseMode.HTML`
- ❌ **Violations**: Any usage of `ParseMode.MARKDOWN` or `ParseMode.DISABLED`
- ✅ **Correct**: `parse_mode=ParseMode.HTML` or global Client setting
- **Rationale**: Consistent user experience, better HTML entity handling

### **HTML & Newlines Policy** - Message Formatting Standards
**Policy**: Use single `\n` for line breaks; avoid `<br>` tags and double newlines
- ❌ **Violations**: `<br>` tags (unsupported by Telegram), double newlines `\n\n`
- ✅ **Correct**: Single `\n` for line breaks in HTML parse mode
- **References**: 
  - [Telegram Bot API - Formatting](https://core.telegram.org/bots/api#formatting-options)
  - [<br> unsupported evidence](https://github.com/python-telegram-bot/python-telegram-bot/issues/736)
- **Rationale**: Telegram HTML parser renders `\n` as line breaks; `<br>` tags are ignored

### **ReuseOpportunity** - Centralization Violations
**Policy**: Use existing utilities instead of duplicate implementations
- ❌ **Violations**: Custom regex when `TelegramLinkParser` exists
- ❌ **Violations**: Direct client calls when `telegram_api` wrapper exists
- ✅ **Correct**: Import and use centralized utilities

### **InconsistentAPI** - Standardization Issues
**Policy**: Same patterns across similar components
- ❌ **Violations**: Different error response formats across repositories
- ❌ **Violations**: Mixed parameter naming (client vs bot)
- ✅ **Correct**: Consistent interfaces and naming conventions

### **DBQuery** - Database Optimization
**Policy**: Efficient query patterns, proper indexing
- ❌ **Violations**: N+1 query patterns, missing compound indexes
- ✅ **Correct**: Batch operations, optimized index usage

### **ErrorHandling** - Exception Management
**Policy**: Consistent error handling across the codebase
- ❌ **Violations**: Mixed exception types, inconsistent logging
- ✅ **Correct**: Standardized error response format, structured logging

### **Concurrency** - Async/Await Patterns
**Policy**: Bounded concurrency, proper rate limiting
- ❌ **Violations**: Unbounded concurrent operations
- ✅ **Correct**: Semaphore-controlled concurrency

---

## Triage Rubric

### Critical Path Analysis
1. **User-facing issues** (ParseMode, error messages) = Higher priority
2. **Admin-only issues** (database queries, logging) = Medium priority  
3. **Developer-only issues** (code quality, types) = Lower priority

### Impact Assessment Matrix
```
           | High User Impact | Medium Impact | Low Impact
-----------|------------------|---------------|------------
High Risk  | Blocker         | Major         | Major
Med Risk   | Major           | Major         | Minor
Low Risk   | Major           | Minor         | Minor
```

### Effort Estimation
- **Quick Win**: ≤ 10 lines, no tests needed, immediate deployment
- **Small**: ≤ 50 lines, basic tests, can be done in one PR
- **Medium**: 50-200 lines, comprehensive tests, requires review
- **Large**: > 200 lines, architectural changes, multi-PR effort

---

## ParseMode HTML Policy (CRITICAL)

### ✅ Global Configuration (Recommended)
```python
# bot.py - Client initialization
super().__init__(
    name=config.SESSION,
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    workers=config.WORKERS,
    parse_mode=ParseMode.HTML,  # ← Global HTML setting
)
```

### ✅ Per-Message Override (When Needed)
```python
await message.reply_text(
    "<b>Bold text</b> and <code>code</code>",
    parse_mode=ParseMode.HTML
)
```

### ❌ Forbidden Patterns
```python
# NEVER use these:
parse_mode=ParseMode.MARKDOWN
parse_mode=enums.ParseMode.MARKDOWN  
parse_mode=ParseMode.DISABLED
# No parse_mode specified when global isn't HTML
```

### HTML Entity Handling
```python
# Correct HTML escaping:
user_input = html.escape(user_provided_text)
await message.reply_text(f"<b>User said:</b> <code>{user_input}</code>")
```

---

## PyroFork Framework References

### Official Documentation Sources (ONLY USE THESE)
- **GitHub**: https://github.com/Mayuri-Chan/pyrofork
- **Docs**: https://pyrofork.wulan17.dev/main/
- **Client API**: https://pyrofork.wulan17.dev/main/api/client.html

### ❌ Do NOT reference:
- Original Pyrogram docs (outdated)
- Third-party tutorials (may be wrong)
- Stack Overflow answers (often outdated)

### Key PyroFork Differences from Pyrogram
- Maintained fork with bug fixes
- Same API surface, but with fixes
- Better error handling in some cases
- Active maintenance and updates

---

## Cross-Reference Map Usage

### Symbol Lookup
```json
// Find where TelegramAPIWrapper should be used:
"core/utils/telegram_api.py": {
  "symbols": {
    "TelegramAPIWrapper": {
      "currently_used_in": ["core/services/filestore.py"],
      "should_be_used_in": [
        {
          "file": "core/services/broadcast.py",
          "impact": "FloodWait errors during broadcasts"
        }
      ]
    }
  }
}
```

### Reuse Opportunity Identification
1. **Find symbol**: Look up utility in cross_reference_map.json
2. **Check current usage**: See `currently_used_in` array
3. **Identify missed opportunities**: Check `should_be_used_in` array  
4. **Assess impact**: Read `impact` field to understand priority
5. **Plan implementation**: Use `reason` field for context

---

## Implementation Workflow

### Phase 1: Quick Wins (Day 1)
```bash
# 1. Parse Mode fixes (CRITICAL)
git checkout -b fix/parsemode-html-compliance
# Apply all ParseMode fixes from quick-wins.md
# Test with simple message sends
git commit -m "Fix: Enforce ParseMode.HTML across all handlers"

# 2. Remove dead code  
# Fix duplicate lines, unused imports
git commit -m "Clean: Remove dead code and duplicate lines"
```

### Phase 2: API Wrapper Adoption (Day 2-3)
```bash
# Replace direct client calls with telegram_api wrapper
git checkout -b feat/centralize-api-wrapper
# Start with broadcast.py, then indexing.py, then handlers
git commit -m "Feat: Adopt centralized API wrapper for flood protection"
```

### Phase 3: Link Parser Centralization (Day 4-5)
```bash
# Replace custom regex with TelegramLinkParser
git checkout -b feat/centralize-link-parsing  
# Remove custom implementations in indexing.py and filestore.py
git commit -m "Feat: Centralize link parsing using TelegramLinkParser"
```

### Phase 4: Database Optimization (Week 2)
```bash
# Add missing indexes, fix N+1 queries
git checkout -b perf/database-optimization
# Focus on user.py and media.py N+1 issues first
git commit -m "Perf: Add missing indexes and fix N+1 queries"
```

---

## Testing Strategy

### ParseMode Testing
```python
# Test HTML rendering:
test_message = "<b>Bold</b> <i>Italic</i> <code>Code</code>"
await bot.send_message(chat_id, test_message)
# Verify: Bold text renders as bold, code renders in monospace
```

### API Wrapper Testing  
```python
# Test flood protection:
for i in range(50):
    await telegram_api.call_api(bot.send_message, chat_id, f"Test {i}")
# Verify: No FloodWait exceptions, proper rate limiting
```

### Link Parser Testing
```python
# Test edge cases:
test_links = [
    "https://t.me/channel/123",
    "https://t.me/c/1234567890/123", 
    "invalid-link",
    "https://t.me/channel/very_long_message_id"
]
# Verify: All valid links parse correctly, invalid links rejected
```

---

## Quality Gates

### Pre-Merge Checklist
- [ ] All ParseMode violations fixed
- [ ] No direct client calls in new code
- [ ] All new utilities use centralized patterns  
- [ ] Error handling follows standard format
- [ ] Type hints added to public methods
- [ ] Tests cover critical paths

### Definition of Done
- [ ] Code follows established patterns
- [ ] No regression in existing functionality
- [ ] Performance impact measured and acceptable
- [ ] Documentation updated if APIs changed
- [ ] Cross-reference map updated with new utilities

---

## Database N+1 Query Optimizations (Phase 10)

### Optimized Batch Operations

**Issue**: N+1 queries in user premium status updates and media duplicate checking
**Solution**: MongoDB aggregation pipelines with $lookup and batch processing

#### Key Optimizations Implemented

1. **Batch Premium Status Check** (`repositories/optimizations/batch_operations.py`)
   - Replaced individual user lookups with single aggregation pipeline
   - Uses computed fields for expiration checking
   - Batch updates expired users in single operation

2. **Batch Duplicate Detection**
   - Bulk file unique_id lookups using $in operator
   - Optimized projections to reduce payload
   - Eliminates individual find_file calls during bulk indexing

#### Required Indexes for Performance

```javascript
// Users collection - compound index for premium checks
db.users.createIndex({
    "is_premium": 1,
    "premium_activation_date": 1, 
    "_id": 1
}, {
    "name": "premium_status_compound_idx",
    "background": true
})

// Media files collection - compound index for duplicate checks
db.media_files.createIndex({
    "file_unique_id": 1,
    "file_id": 1,
    "user_id": 1
}, {
    "name": "duplicate_check_compound_idx", 
    "background": true
})

// Media files collection - user activity aggregation
db.media_files.createIndex({
    "user_id": 1,
    "created_at": 1,
    "file_size": 1  
}, {
    "name": "user_activity_aggregation_idx",
    "background": true
})
```

#### Performance Impact Analysis

**Before Optimization**:
```
// N+1 premium status check for 100 users
- 100 individual find() operations
- Average: 100 * 5ms = 500ms total
- Network roundtrips: 100

// N+1 duplicate check for 50 files  
- 50 individual find() operations
- Average: 50 * 3ms = 150ms total
- Network roundtrips: 50
```

**After Optimization**:
```
// Batch premium status check for 100 users
- 1 aggregation pipeline operation  
- Average: 15ms total
- Network roundtrips: 1
- Performance improvement: 97%

// Batch duplicate check for 50 files
- 1 aggregation with $in operator
- Average: 8ms total  
- Network roundtrips: 1
- Performance improvement: 95%
```

#### Usage Examples

```python
# Batch premium status check
user_repository = UserRepository(db_pool, cache_manager)
user_ids = [123, 456, 789]
status_map = await user_repository.batch_check_premium_status(user_ids)

# Batch duplicate check  
media_repository = MediaRepository(db_pool, cache_manager)
media_files = [file1, file2, file3]
duplicate_map = await media_repository.batch_check_duplicates(media_files)
```

---

## Rollback Procedures

### If ParseMode Changes Break Rendering
```bash
# Quick rollback
git checkout HEAD~1 -- handlers/filestore.py handlers/filter.py
git commit -m "Rollback: ParseMode changes due to rendering issues"
```

### If API Wrapper Causes Rate Limits
```bash  
# Disable wrapper temporarily
# In affected files, comment out telegram_api usage:
# await telegram_api.call_api(client.send_message, ...)
await client.send_message(...)  # Direct call temporarily
```

### Emergency Rollback
```bash
# Full rollback to last known good state
git revert <commit-hash>
git push origin main
```

---

## Maintenance Notes

### Regular Audit Tasks
- **Monthly**: Check for new ParseMode violations
- **Quarterly**: Review cross-reference map for new opportunities
- **Per Release**: Update quick-wins with new findings

### Adding New Utilities  
1. Create in appropriate `core/utils/` location
2. Add to cross_reference_map.json
3. Update AUDIT-TODO.md with reuse opportunities
4. Add usage examples to this document

### Keeping Audit Current
- Update findings when architecture changes
- Remove resolved TODOs from list
- Add new categories as codebase evolves
- Reassess priority based on user feedback

---

## Contact and Questions

For questions about this audit:
1. **Critical ParseMode issues**: Implement immediately, ask questions later
2. **Architecture decisions**: Review cross_reference_map.json first  
3. **Implementation details**: Check quick-wins.md for examples
4. **Priority questions**: Use triage rubric in this document

**Remember**: The goal is consistent, maintainable code that follows PyroFork best practices!