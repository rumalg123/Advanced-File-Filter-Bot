# Cache Correctness Audit and Remediation Register

This document is the source of truth for the whole-system cache audit started on
2026-07-18. Every cache-related runtime change and regression test must reference
an issue ID below. The audit covers Redis access, serialization, key generation,
TTLs, repository caches, sessions, rate limits, invalidation, monitoring, and
MongoDB/cache boundaries.

Status values: `Confirmed`, `Fixing`, `Fixed`, `Deferred`, `Blocked`.

## Live-safety contract

1. MongoDB remains authoritative; a cache failure must not turn a successful
   database read into invalid data.
2. Existing Redis keys remain readable where their stored shape is valid.
3. Corrupt or obsolete cache entries are discarded and rebuilt from MongoDB.
4. Fixes must not flush the complete Redis database or delete unrelated keys.
5. Existing TTL-managed sessions are allowed to expire naturally.
6. Invalidation must favor correctness over preserving a stale cache hit.
7. Administrative cleanup may delete only entries proven stale; intentional
   identifier aliases are not duplicates.
8. Changes must be covered with focused regression tests and the full suite must
   pass before an item is marked `Fixed`.

## Issue register

| ID | Severity | Status | Area | Confirmed defect and acceptance criteria |
|---|---|---|---|---|
| CACHE-001 | High | Fixed | Search sessions | Daily/startup maintenance deletes every `search_results_*` key even though each session has a one-hour TTL, expiring live pagination/send-all buttons early. Stop bulk deletion and rely on per-key TTLs. |
| CACHE-002 | High | Fixed | Search invalidation | The process-wide five-second invalidation throttle drops media changes that occur inside the cooldown, allowing versioned search results to omit new/updated files until TTL expiry. Every committed media mutation must advance the version. |
| CACHE-003 | High | Fixed | Media mutations | Single-database creates do not invalidate search results, updates do not invalidate search results in either database mode, and creates leave file statistics stale. Make mutation invalidation consistent across modes. |
| CACHE-004 | High | Fixed | Connections | `connections:<user>` alternates between a complete entity and `{'active_group': ...}`; repository reads can receive the wrong schema and fail. Store one stable schema per key and self-heal legacy partial entries. |
| CACHE-005 | High | Fixed | Filters | Deleting all filters clears only the list key, leaving individual `filter:<group>:<text>` entries able to answer deleted filters. Clear the group entry prefix as well as its list. |
| CACHE-006 | Medium | Fixed | User statistics | User creation, premium/ban changes, expiry batches, and retrieval activity can leave `user_stats` stale. Invalidate the aggregate only after relevant successful writes. |
| CACHE-007 | High | Fixed | Premium expiry | The optimized batch premium-expiry path updates MongoDB without clearing user objects or `premium_status` decisions. Invalidate both per-user keys and aggregate statistics. |
| CACHE-008 | Medium | Fixed | Invalidation coverage | “All user cache” omits premium decisions, histories, recommendation state, and last-search keys; subscription patterns do not match the keys actually generated. Align generated keys and invalidation patterns. |
| CACHE-009 | High | Fixed | Sessions | Cancelling an old session unconditionally deletes the user pointer, even if it now points to a newer session. Delete the pointer only when it still owns the cancelled session ID. |
| CACHE-010 | High | Fixed | Rate limiting | `INCR` and first-use `EXPIRE` are separate operations; a crash between them leaves a permanent counter. Add an atomic increment-with-expiry primitive and use it for rate-limit windows. |
| CACHE-011 | Medium | Fixed | Redis lifecycle | A failed initial `PING` leaves a non-null client on the manager, so a retry can skip reconnection. Roll back failed initialization and close the incomplete client. |
| CACHE-012 | Medium | Fixed | Pattern deletion | `delete_pattern` collects every matching key in memory before deleting batches. Stream `SCAN` results into bounded batches. |
| CACHE-013 | Medium | Fixed | Serialization | Explicit compressed serialization hints create `cc` prefixes instead of `cj`/`cm`/`cp`, making the values unreadable. Encode the underlying method consistently. |
| CACHE-014 | High | Fixed | Serialization | Unsupported values silently fall back to a string representation, changing cached data types and allowing repository schema failures. Refuse the cache write so callers fall through to authoritative storage; preserve the premium tuple contract on cache hits. |
| CACHE-015 | Medium | Fixed | Monitoring | Cache analysis does not await `MEMORY USAGE`, assumes Redis database 0, and its media lookup strips the required key prefix. Await commands, report the selected database, and read full keys. |
| CACHE-016 | High | Fixed | Admin cleanup | Valid media identifiers are intentionally cached as aliases, but `/cache_cleanup` treats alias groups as duplicates and can delete working lookup paths. Report aliases separately and delete only keys not represented by the cached media identifiers. |
| CACHE-017 | High | Fixed | Bot settings | Settings upserts include immutable `_id` inside `$set`, which can prevent the database write and therefore prevent correct cache invalidation. Keep `_id` in the selector/insert identity only. |
| CACHE-018 | Medium | Fixed | TTL configuration | `CACHE_TIME` is exposed as a setting but is not loaded into `BotConfig` or used by search-result caching. Apply a validated value to the shared search-result TTL at startup. |
| CACHE-019 | Low | Fixed | Falsey cache values | Empty cached lists are treated as misses for channels and filters, causing repeated MongoDB work. Distinguish a cached empty value from a missing key. |
| CACHE-020 | Medium | Fixed | Error semantics | Invalidation helpers report success even when `CacheManager.delete` reports failure, and non-positive TTLs can accidentally become persistent writes. Propagate operation results and reject invalid expiring writes. |
| CACHE-021 | Medium | Fixed | Version recovery | A malformed search-version value can break all searches instead of being discarded. Validate and self-heal the version key. |
| CACHE-022 | Low | Fixed | Channel projection | Indexed-count updates invalidate the entity key but not the cached active-channel projection, so callers can see old channel metadata. Invalidate the projection after a successful count update. |
| CACHE-023 | Medium | Fixed | Session identity | Default session IDs use one-second timestamps, allowing two same-user/same-type creations in one second to reuse a cache identity. Generate collision-resistant IDs so ownership checks remain meaningful. |

## Remediation order

1. Fix cache primitives and serialization: CACHE-010 through CACHE-014,
   CACHE-020, and CACHE-021.
2. Fix key ownership and invalidation: CACHE-002, CACHE-004, CACHE-005,
   CACHE-008, and CACHE-009.
3. Fix repository mutation drift: CACHE-003, CACHE-006, CACHE-007,
   CACHE-017, CACHE-018, CACHE-019, and CACHE-022.
4. Fix lifecycle and operational tooling: CACHE-001, CACHE-011, CACHE-012,
   CACHE-015, and CACHE-016.
5. Run focused tests, the complete regression suite, compilation, linting,
   dependency checks, and update every status and verification result here.

## Verification log

- 2026-07-18: Audit register created before runtime remediation. No broad Redis
  flush or destructive MongoDB migration is authorized or required.
- 2026-07-18: CACHE-001 through CACHE-023 fixed without flushing Redis or
  migrating MongoDB. Compatible cache entries continue to be used; incompatible
  entity shapes are evicted individually and rebuilt from MongoDB.
- 2026-07-18: Added 21 focused cache regression tests. Full suite result:
  65 passed.
- 2026-07-18: Python compilation, repository-wide undefined-name linting,
  dependency consistency (`pip check`), and `git diff --check` passed. The cache
  test module also passes the repository's complete Ruff rules.

## Deployment notes

1. Restart the bot normally; do not run `FLUSHDB` or `FLUSHALL`.
2. Existing search and entity keys may remain until their normal TTL, but every
   changed media record now advances the search version immediately.
3. Legacy partial connection entries self-heal on first access and are rebuilt
   from MongoDB.
4. `CACHE_TIME` now controls search-result cache TTL after restart. Invalid or
   non-positive values fall back to 300 seconds.
5. `/cache_cleanup confirm` now removes only provably stale media aliases and
   preserves file ID, unique ID, and file-reference lookup keys.
6. After deployment, smoke-test one search with pagination/send-all, a filter,
   a connected group, a premium check, `/cache_stats`, and `/cache_analyze`.
