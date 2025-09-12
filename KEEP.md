# Code Retention Documentation

This file documents code that appears unused but is intentionally kept for backward compatibility, framework requirements, or future use.

## aiohttp Handler Parameters

**Files**: `bot.py` (lines 987, 996)
**Reason**: `request` parameter is required by aiohttp framework even if not used in handler body
**Keep Until**: Framework requirement continues

## PyroFork Handler Parameters  

**Files**: Various handler files
**Reason**: Handler methods require `client` and `message` parameters per PyroFork framework
**Keep Until**: Framework requirement continues

## Framework Integration Points

**Files**: Various
**Reason**: Some methods and parameters are used by frameworks via introspection or are part of API contracts
**Keep Until**: Framework dependencies removed

## Vulture Whitelist

Use `vulture_whitelist.py` to suppress false positives for:
- Framework-required parameters
- Dataclass fields accessed indirectly
- Methods called via introspection
- Context manager protocol methods

## Dead Code Removal History

**Phase 12 (Latest)**:
- Removed `find_by_ref_id()` from `core/database/base.py` - duplicate of `find_by_id()`
- Removed unused import `cache_user_data` from `repositories/user.py`  
- Removed unused import `with_flood_protection` from `core/services/filestore.py`
- Fixed unused parameter `max_tokens` in `core/utils/rate_limiter.py`
- Prefixed intentionally unused `operation_name` with underscore in `core/database/multi_pool.py`

**Validation**: All removed code confirmed unused via grep and cross-reference checking