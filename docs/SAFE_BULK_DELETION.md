# PH-007: Safe keyword deletion

**Status:** draft implementation; not deployed or merged. Production database remains unchanged.

## Operator behavior

The old /deleteall method loaded all matching documents and built an unbounded
DeleteOne operation list. Its boolean bulk-write wrapper could conceal partial
errors and it reported the number of files *found* rather than the number
actually deleted. A 60-second confirmation held only a keyword and was not
bound to a specific count or single-use token.

The delete-channel automatic queue also no longer drops requests when full; it waits for a free slot. This protects in-process delivery only; a process crash can still lose pending in-memory delete requests.\n\nThe new /deleteall flow is deliberately stricter:

1. An authorized admin enters /deleteall followed by at least three keyword
   characters.
2. Read-only preview counts **exact** MongoDB matches and displays up to five
   escaped file names. No deletion occurs during preview.
3. If more than 1000 matches are found, the request is **rejected**. Use a
   narrower keyword. The bot cannot be instructed to delete an arbitrary number
   of files in one confirmation.
4. A short-lived Redis record stores {keyword, count, token} for 90 seconds.
   The confirmation callback includes the requesting admin ID and random
   token; it is valid only for an admin with the matching ID.
5. Confirmation atomically consumes the Redis record. Replayed, duplicated,
   expired, replaced or non-admin callbacks never trigger deletion.
6. MongoDB recounts matches immediately before the first delete. Any count
   mismatch aborts **without deleting anything**.
7. Files are loaded with a small identifier-only projection and a limit of 100.
   They are deleted using a bounded `_id` set; **no full-match materialization**.
   Repeated reads use no skip/offset because deletes shift offsets.
8. After every committed batch, individual file/media caches are invalidated
   and the search-cache version is incremented, so interrupted work does not
   leave old versioned search results valid.
9. Stop/error/cancellation is recorded, and acknowledged deleted count is
   reported in the Telegram UI and audit log. An interrupted run is resumed
   manually by **running a new preview**, not by blindly replaying a cached
   request.

A delete operation removes only indexed MongoDB records, **not files hosted in
the source Telegram channel**.

## Database and cache compatibility

**No existing MongoDB collection, index, field, media ID, schema or records
are changed by deploying this code.** The code does not create a new collection,
run migrations, backfill media or flush Redis.

The only new Redis value format is the temporary 90-second `deleteall_pending`
confirmation record. Old pending confirmations from the previous version will
be rejected as stale and naturally expire. No active file delivery sessions
are cleared.

## Safety limits and constraints

- The keyword must be at least 3 characters. Unsafe empty-match predicates
  are rejected.
- At most **1000 matches** are accepted per confirmation.
- Batches contain no more than **100 records**.
- Multi-database bulk deletion is explicitly disabled until distributed
  deletion/consistency rules are designed (PH-025 through PH-028). Production
  currently uses only one database.
- Confirmation is bound to the exact previewed number of matches. It is not
  a transaction: concurrent media inserts/deletes could still change the
  matching set during execution. The operation reports such detected changes
  rather than claiming full success.
- Telegram audit output contains the administrator ID, keyword digest,
  preview count, acknowledged deleted count and completion state. Raw keywords
  are not written to the logger; an audit log channel is optional.
- If a MongoDB command succeeds at the server but its acknowledgment is lost
  to a network failure, the number reported may be a **lower bound**. Always
  re-preview remaining matches and consult MongoDB counts after interruptions.
- Cache invalidation failures produce an explicit partial-progress outcome,
  and require checking Redis before retrying. Media-specific invalidation
  failures may be indistinguishable from keys that were never cached; they
  are best effort, while search generation invalidation is mandatory.
- This is a **destructive** operation. MongoDB restore or Telegram history
  reindexing is needed to restore deleted index records. Running /deleteall
  again is not a rollback. The application code can be rolled back separately
  without restoring MongoDB.
- The current manual replay procedure is designed for one active bot instance.
  If you add replicas, add a distributed deletion lock and cross-replica audit
  coordination before using this operation concurrently.

## Staging verification

- [ ] Full Python pytest suite and code compilation pass on GitHub Actions.
- [ ] Real localhost-only MongoDB integration test demonstrates bounded
      batches, accurate deleted_count and unrelated-record preservation.
- [ ] Confirm admin-only command and callback protection, token expiry,
      stale preview count, replay prevention and HTML escaping.
- [ ] Simulate MongoDB failure after one batch; confirm partial count, retry
      preview, and no broad unintended deletion.
- [ ] Simulate cache-generation invalidation failure and cancellation.
- [ ] Verify Telegram audit logging and response formatting with real clients.
- [ ] Confirm legitimate existing file buttons and search sessions remain intact.
- [ ] Practice database restore/reindex from a safe backup before enabling
      destructive bulk commands in a production release.

## Source files

- `core/services`bulk_delete_policy.py/: limits and typed outcomes.
- `core/services`bulk_media_deletion.py/: bounded batch processor.
- `repositories/media.py`: preview and execution API.
- `handlers/delete.py`: restricted two-step Telegram confirmation.
- `tests/test_safe_bulk_deletion.py`: unit and callback tests.
- `tests/test_safe_bulk_deletion_mongo.py`: ephemeral local MongoDB test.

See [MongoDB PyMongo bulk write documentation](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/crud/bulk-write/)
for the motivation to bound write requests and accurately report operation
results. This implementation uses `delete_many` with bounded `_id` sets.
