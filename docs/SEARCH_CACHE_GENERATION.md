# PH-011: Search-cache generation consistency and bounded retry

**Status:** implementation on Draft PR #4. Not merged or deployed.
**Data compatibility:** no existing MongoDB records, collections, indexes or
schema changes. Existing Redis search keys and Telegram buttons remain in the
same format, and there is no Redis FLUSH/SCAN/delete migration.

## Root causes addressed

1. **Missing cache generation could fall back to `v1`.** In single-Redis
   mode, an evicted/expired/deleted version key meant the bot could reuse
   old search pages with `:v1`. The previous first invalidation ran INCR
   twice to reach `v2` and used a one-year key expiry. In split-state mode,
   a malicious/broken value could be deleted with a separate command,
   racing a concurrent initializer.
2. **Version read and result read were separate operations.** An index
   update could invalidate a generation while the bot was reading an old
   cached page. The previous code returned that page without rechecking.
3. **MongoDB count, sorted fetch and Redis SET were separated by awaits.**
   An index change between these steps could produce a known-stale
   response. The cached entry was typically under an obsolete version,
   but the active request would still return old data.

## Implementation

- The search generation remains at `cache:search:version`, preserving the
  current key schema and old raw integer counters. All new missing-key
  generations use unpredictable positive 60-bit seeds; **never plain 1**.
- New Redis Lua scripts ensure generation initialization/validation and
  increment with **single atomic server operations**. Malformed counters
  fail closed rather than being deleted and recreated during concurrent
  traffic. Existing one-year TTLs are removed with `PERSIST` as part of
  the atomic operation; **the single-Redis allkeys-lru policy can still
  evict the key**, but the next initialization uses a fresh random seed.
- Server-side Lua scripts compare integer strings without converting them
  to floating-point Lua numbers, avoiding precision loss for ~60-bit
  counters. Redis `INCR` performs the exact signed 64-bit update.
- In PH-003 split mode, only the **protected state Redis** owns the
  counter; versioned search pages remain on the disposable instance.
- `MediaRepository.search_files` rechecks generation after cached reads,
  after MongoDB count/page queries and after cache writes. A changed
  generation means **discard and retry**, capped at three attempts. A
  fourth concurrent invalidation does not loop forever; after three
  invalidated attempts the bot reports a retryable error rather than
  returning a result it knows to be stale.
- Version-read errors propagate as a typed search outage; they cannot
  silently initialize a cache entry under `v1`. There is no global Redis
  flush and no immediate deletion of old search pages: old generations
  expire naturally under the existing TTLs.

### Consistency guarantees and limits

The check detects mutations **when the repository write path increments
the generation**. It does not create a distributed transaction spanning
MongoDB and Redis. Writes performed directly in MongoDB (out-of-band
imports, an external admin, or a failed/skipped invalidation) can still
escape detection. Multiple MongoDB reads in one search are also not
snapshot-isolated. A mutation after the final version check and before
Telegram delivery is inherently outside this guarantee.

Without protected Redis (PH-003 remains opt-in), an allkeys-lru eviction
may discard the counter, but random reinitialization avoids predictable
key reuse. If a client loses connection to Redis, a failed generation
read prevents a search result from being presented as authoritative.
This is an availability-versus-correctness choice.

## CI tests

- `tests/test_search_cache_generation_races.py` simulates invalidations
  during MongoDB queries, cache hits, cache writes and repeated updates.
- `tests/test_atomic_search_generation_redis.py` uses **two localhost-only
  ephemeral Redis instances** in CI, tests 100 concurrent atomic
  increments, key expiry removal, malformed counters, key reset, routing
  to protected Redis and stale-page avoidance without `FLUSHDB`.
- Existing PH-002/003/006 search and cache tests now use the atomic API
  and explicitly expect malformed counters to **fail closed**.
- Other MongoDB, Redis, bot, authorization and deletion regression tests
  remain part of the same full Python CI suite.

## Deployment and rollback

1. **Do not deploy this branch automatically.** Confirm full pytest,
   container-preflight and local Redis integration pass for the exact
   reviewed commit.
2. On **staging**, search the full Doctor X filename and a rare
   nonexistent title; confirm repeat search hits cache and that indexing
   a matching episode invalidates the page. Verify pagination and
   callbacks work.
3. In staging Redis, simulate a missing generation key while leaving
   cached pages. Confirm the next search uses a new generation and reads
   current MongoDB truth. Check no unrelated sessions/keys are deleted.
4. Under load, test an indexing burst during active searches; verify
   search retries are bounded and eventual consistency recovers after
   writes stop.
5. Verify Redis outage and restart recoveries, especially when PH-003
   protected state is enabled or disabled. Protect and back up state
   as appropriate; do not run `FLUSHDB` against live Redis.
6. Verify existing generation keys may have their TTL removed at first
   access; this is intentional and adds one persistent small counter.
7. For rollback, return to the previous reviewed image only after
   checking behavior: the prior code can reintroduce `v1` reuse and
   stale in-flight cache hits. It is preferable to fix the new issue
   and retain generation-safe semantics.

## Sources

- [Redis Lua atomic execution](https://redis.io/docs/latest/develop/programmability/eval-intro/)
- [Redis SET semantics](https://redis.io/docs/latest/commands/set/)
- [Redis INCR semantics](https://redis.io/docs/latest/commands/incr/)

**Verified in CI:** [run 40803258303](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40803258303) passed full pytest, live Redis integration, compile/lint and Docker preflight.\n\n**Remaining acceptance:** real Telegram staging behavior,
controlled Redis restart/race drills, and operator approval. This phase
does not claim true snapshot isolation or cover PH-027 multi-DB partial
failures.
