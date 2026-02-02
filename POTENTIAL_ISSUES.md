# Potential Issues Found

## 1. Missing `# noqa` comments for `create_background_task`

**Location:** `handlers/channel.py:58`
- Same issue as `bot.py:846` - linter warning about coroutine not awaited
- **Fix:** Add `# noqa` comment

## 2. Direct `asyncio.create_task` calls without proper tracking

These tasks are created directly and might not be tracked for cleanup:

### Auto-delete tasks (should use handler manager):
- `handlers/commands_handlers/user.py:590, 601` - Recommendations auto-delete
- `handlers/deeplink.py:161, 224, 231, 321, 339, 385, 392, 470, 486, 552, 559` - Multiple auto-delete tasks
- `core/services/filestore.py:584, 643, 723` - Auto-delete tasks
- `handlers/commands_handlers/bot_settings.py:573` - Auto-delete task

**Issue:** These should use `handler_manager.create_auto_delete_task()` or handler's `_schedule_auto_delete()` method for proper tracking and cleanup.

### Background tasks:
- `core/services/search_results.py:197` - Recommendations task
- `handlers/commands_handlers/admin.py:229` - Broadcast task (this one is tracked in `self.broadcast_task`)

**Issue:** Background tasks should use `handler_manager.create_background_task()` for proper tracking.

## 3. Missing error handling in task callbacks

**Location:** Multiple places where tasks are created
- Tasks might fail silently if exceptions aren't caught
- **Recommendation:** Add error handling in task callbacks or wrap coroutines with error handlers

## 4. Potential race conditions

**Location:** `handlers/channel.py:63-77`
- Tasks are created in `_create_background_tasks()` which is called in `__init__`
- If `handler_manager` is not ready, tasks might fail
- **Status:** Already has error handling (checks if task is None)

## 5. Task cleanup during shutdown

**Location:** Various handlers
- Some tasks created with direct `asyncio.create_task()` might not be cancelled during shutdown
- **Recommendation:** Ensure all tasks go through handler manager for proper cleanup

## Priority Fixes:

1. **High Priority:**
   - Add `# noqa` to `handlers/channel.py:58`
   - Convert direct `asyncio.create_task()` calls for auto-delete to use handler manager methods

2. **Medium Priority:**
   - Add error handling to background tasks
   - Ensure all tasks are tracked for cleanup

3. **Low Priority:**
   - Review task lifecycle management
   - Add monitoring for untracked tasks
