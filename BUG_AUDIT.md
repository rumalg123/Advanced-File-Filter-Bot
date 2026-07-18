# Bug Audit and Fix Register

This document is the source of truth for bugs found during the Pyrogram-to-Wzgram
migration audit. Implementation work must reference an ID below, and an item may
be marked `Fixed` only after its acceptance criteria have been verified.

Status values: `Open`, `In progress`, `Fixed`, `Blocked`.

| ID | Severity | Status | Area | Defect | Acceptance criteria |
|---|---|---|---|---|---|
| BUG-001 | High | Fixed | Sessions | The five-minute cleanup deletes every `session:*` key, including live search, index, and batch sessions with longer TTLs. | Cleanup never deletes a live session; Redis TTL remains the expiry mechanism. |
| BUG-002 | High | Fixed | Premium | Premium-status cache entries survive grant, removal, and expiry updates for up to ten minutes. | Every premium mutation invalidates both user and premium-status cache keys. |
| BUG-003 | High | Fixed | Quotas | Single-file access checks and quota increments are separate, so concurrent requests can exceed the limit; failed sends remain charged. | Single-file quota reservation is conditional and atomic, and every unsuccessful delivery releases its reservation. |
| BUG-004 | High | Fixed | Quotas | Bulk-send quota is leaked when callback/status setup fails or the coroutine is cancelled before normal refund logic. | All unsent reservations are released through exception-safe cleanup. |
| BUG-005 | High | Fixed | Premium batches | Premium batch access trusts the raw `is_premium` flag without checking the expiry date. | Premium batch access uses the repository's validated premium status. |
| BUG-006 | High | Fixed | Packaging | `pyproject.toml` installs Pyrofork while `requirements.txt` installs unpinned Wzgram Git HEAD; platform markers also disagree. | Both manifests install the same pinned Wzgram revision and use consistent platform markers. |
| BUG-007 | Medium | Fixed | Requests | Request and warning counters use read-modify-write updates and lose concurrent increments. | Request allowance and warning changes use guarded atomic database operations. |
| BUG-008 | Medium | Fixed | Indexing | `/setskip` is reset to zero when indexing begins. | A configured skip value reaches `iter_messages` and is reset only after the run starts/finishes as intended. |
| BUG-009 | Medium | Fixed | Indexing | Cancelling indexing processes the pending message batch twice. | A pending batch is processed no more than once during cancellation. |
| BUG-010 | Medium | Fixed | Channel indexing | `await Queue.put()` cannot raise `QueueFull`, so the overflow path is unreachable and handlers block. | The handler uses a non-blocking enqueue and the overflow path activates when the main queue is full. |
| BUG-011 | Medium | Fixed | Commands | Bot menus publish `/del` and `/delall`, but filter handlers do not register those commands. | Every published filter command has a matching handler. |
| BUG-012 | Medium | Fixed | Batch links | `expires_at` is stored as a string, so MongoDB TTL expiry does not work; reads also accept expired links. | Expiry is stored as a BSON datetime and expired records are rejected on cache and database reads. |
| BUG-013 | Medium | Fixed | Configuration | Negative Telegram channel IDs are discarded by `get_channel_list()`. | Numeric IDs with a leading minus sign parse successfully. |
| BUG-014 | Medium | Fixed | Deployment | Docker Compose healthcheck always exits successfully without testing the application. | The healthcheck fails when the HTTP health endpoint is unavailable or unhealthy. |
| BUG-015 | Medium | Fixed | Testing | `.gitignore` ignores normal test filenames and the repository contains no regression suite. | Tests under `tests/` are tracked and cover the fixed behaviors. |
| BUG-016 | Medium | Fixed | Recommendations | Per-user recommendations are cached for ten minutes, but new searches and file clicks never invalidate that cache; Refresh returns the same stale result. | Recommendation-affecting events invalidate the user's cached recommendations, and Refresh forces recomputation. |
| BUG-017 | High | Fixed | Recommendations | File buttons contain no originating search reference; click tracking reads the user's mutable `user_last_search` key and can attribute a click from search A to a later search B. | Each click is associated with immutable originating-query context carried by, or resolved from, the clicked result session. |
| BUG-018 | Medium | Fixed | Similar keywords | A private no-result query is inserted into history before fuzzy suggestions are generated, so “Did you mean?” can suggest the identical failed query. | Exact normalized matches are excluded and failed searches do not outrank valid candidates. |
| BUG-019 | Medium | Fixed | Recommendations | Search-sequence tracking is called for group searches only; private searches never populate query co-occurrence data. | Successful private and group searches use the same persisted, time-bounded sequence tracker. |
| BUG-020 | Medium | Fixed | Recommendations | Post-search code calculates `recommended_file_ids`, but `_send_recommendations` ignores them; when only file recommendations exist, no recommendation message is sent. | Recommended file IDs are resolved and displayed, or are not used as a send condition until supported. |
| BUG-021 | Medium | Fixed | Similar filters | Adding a near-duplicate filter builds `warning_msg` but immediately discards it with `pass`, so the administrator sees no warning. | Similar-filter warnings are shown and require an explicit confirmation or documented automatic policy. |
| BUG-022 | Medium | Fixed | Personalization | File clicks increment `rec:user_interactions:{user_id}`, but no recommendation read path consumes that sorted set. | Personalized ranking uses the recorded user interaction profile or stops writing unused interaction data. |
| BUG-023 | Critical | Fixed | Wzgram migration | `MediaSearchBot` assigns the application limiter to `Client.rate_limiter` before the wzgram constructor runs; wzgram replaces it with its transport limiter, which has no `check_rate_limit`, breaking every search and file-access request. | Wzgram retains ownership of `Client.rate_limiter`; all application search, file, inline, and broadcast limits use a separately named Redis-backed limiter, with a constructor regression test. |
| BUG-024 | Medium | Fixed | Telegram formatting | HTML-producing `ErrorMessageFormatter` output is passed to callback alerts and inline switch text, but Telegram never parses markup in those plain-text-only fields, so users see literal tags such as `<b>Success:</b>`. | Every callback/inline answer requests `plain_text=True`, literal HTML is absent from those surfaces, and a repository-wide AST regression test enforces both rules. |
| BUG-025 | Medium | Fixed | Callback handling | Variant headings and pagination indicators are registered with a synchronous lambda that returns `CallbackQuery.answer()` without awaiting it, producing runtime warnings under Wzgram/Pyrogram compatibility dispatch. | Every callback-answer coroutine is awaited, inert callbacks use an async handler, and a repository-wide AST regression test guards the rule. |
| BUG-026 | Medium | Fixed | Search pagination | Variant grouping is applied only by the initial search-result renderer; pagination rebuilds plain file rows, so grouping disappears after moving forward or back. | Initial results and every pagination direction use one shared variant-aware row builder, preserving every file and group heading. |
| BUG-027 | High | Fixed | File reports | Reports are keyed by reporter, contain only a file ID, are not sent to `LOG_CHANNEL`, and resolution neither knows nor notifies all affected users. | One open file/reason issue subscribes every distinct reporter, stores/displays filenames, logs detailed events, safely notifies reachable reporters on resolution, and records notification outcomes. |
| BUG-028 | Medium | Fixed | Transient feature messages | Report reason, favorites, saved-search, autocomplete, and post-search recommendation menus bypass `MESSAGE_DELETE_SECONDS` and remain after their parent results/files disappear. | Every transient feature menu uses the tracked cleanup scheduler when the configured interval is positive; selected report menus are removed immediately. |
| BUG-029 | Medium | Fixed | Collections | Named collections expose create/list/delete commands, but no rename/clear operations or safe in-chat way to open, add, remove, and manage members; full names cannot be combined safely with Telegram callback data. | Collections support owner-scoped create/open/rename/clear/delete and membership controls, destructive callbacks require confirmation, and stable compact tokens keep callbacks within 64 bytes without migrating legacy documents. |
| BUG-030 | Low | Fixed | User feature data | Recent history can only be cleared wholesale, recommendation feedback cannot be listed/reset, and saved searches cannot be run from their management menu. | Recent entries support individual removal, recommendation preferences support list/reset with cache invalidation, and saved-search rows enter the normal owned search flow through a Run action. |
| BUG-031 | High | Fixed | Broadcast recovery | Broadcast pending state is stored before the confirmation preview is accepted; a preview failure consumes the rate limit and leaves every later `/broadcast` stuck, while stop/reset cannot clear the phantom confirmation. | Pending state is published only after a successful preview, preview failure releases the limiter, and both broadcast recovery commands clear pending state safely. |
| BUG-032 | High | Fixed | Broadcast callbacks | The confirmation callback is acknowledged only after delivery to every user, so Telegram can expire the query and make Confirm appear unresponsive during a large broadcast. | Confirm and Cancel are acknowledged before slow work, each callback is answered exactly once, and delivery/status failures still clear active and pending state. |
| BUG-033 | Medium | Fixed | Broadcast formatting | `/broadcast` advertises HTML support but always calls `Message.copy()`, so HTML tags typed into otherwise plain text or media captions are delivered literally. | Existing Telegram entities continue through `Message.copy()`; supported raw HTML text and captions are explicitly parsed during delivery; preview content is safely escaped. |

## Verification log

- 2026-07-18: Baseline `compileall` passed.
- 2026-07-18: Baseline import sweep loaded 41 application modules.
- 2026-07-18: Baseline `pip check` reported no broken installed dependencies.
- 2026-07-18: No source changes existed before remediation began.
- 2026-07-18: Added 19 regression tests covering the fixed session, premium,
  quota, request, indexing, queue, expiry, configuration, command, packaging,
  and healthcheck paths; all tests passed.
- 2026-07-18: Post-fix `compileall`, undefined-name lint, and `pip check` passed.
- 2026-07-18: `pip install --dry-run --no-deps .` successfully built package
  metadata and resolved `auto-file-filter-bot==2.0.0`.
- 2026-07-18: Docker was unavailable locally, so container runtime healthcheck
  execution remains to be exercised in CI/deployment; static regression coverage
  verifies both Docker definitions use a failing HTTP probe.
- 2026-07-18: Recommendation/similar-keyword diagnostic reproduced an identical
  “Did you mean?” suggestion, a stale recommendation after a new file click, and
  a file-only recommendation path that sent zero messages. BUG-016 through
  BUG-022 were added as open findings; no behavioral fixes were made in this pass.
- 2026-07-18: Fixed BUG-016 through BUG-022. Search-result file callbacks now
  carry a compact immutable session reference; successful private and group
  searches share a persisted ten-minute sequence tracker; behavior changes and
  Refresh invalidate personalized caches; click-profile co-occurrence contributes
  to ranking; file-only recommendations resolve to buttons; exact/failed keyword
  suggestions are excluded; and near-duplicate filters are shown and automatically
  rejected under the documented policy.
- 2026-07-18: Added 10 recommendation/similarity regression tests (29 total).
  `python -m pytest -q`, `compileall`, Ruff undefined-name checks, `pip check`,
  and `git diff --check` passed.
- 2026-07-18: Production logs exposed BUG-023. Confirmed wzgram initializes its
  own `Client.rate_limiter`, separated the application limiter as
  `app_rate_limiter`, and added regression coverage that simulates the client
  attribute overwrite.
- 2026-07-18: Verified an unmocked client retains wzgram's transport limiter at
  `Client.rate_limiter` while the application limiter exposes
  `check_rate_limit` at `app_rate_limiter`. All 67 tests, `compileall`, Ruff
  undefined-name checks, `pip check`, and `git diff --check` passed.
- 2026-07-18: Fixed BUG-024 in `/bsetting` and fourteen other callback/inline
  responses. Added formatter, behavioral settings-alert, and repository-wide
  plain-text-surface tests; all 70 tests passed.
- 2026-07-18: Fixed BUG-025 and BUG-026. Replaced the synchronous inert-callback
  lambda with an awaited async handler and centralized variant-aware file-row
  construction so initial, forward, and backward pages render identically.
  Added callback-await and forward/back pagination regressions; all 72 tests,
  `compileall`, Ruff undefined-name checks, and `pip check` passed.
- 2026-07-18: Fixed BUG-027 and BUG-028. File/reason reports now deduplicate
  atomically, subscribe all reporters, coalesce legacy duplicates, retain file
  names, log detailed events, and notify reachable users when resolved. Added
  favorites removal controls and tracked cleanup for report, favorites, recent,
  saved-search, suggestion, and recommendation menus. All 79 tests, `compileall`,
  Ruff undefined-name checks, `pip check`, and `git diff --check` passed.
- 2026-07-18: Fixed BUG-029 and BUG-030. Added stable owner-scoped collection
  tokens, complete collection and membership CRUD, destructive confirmations,
  per-entry recent deletion, recommendation preference list/reset, and saved-
  search Run actions. Updated the README and architecture diagrams; all 84 tests,
  `compileall`, Ruff undefined-name checks, `pip check`, diagram fence checks,
  and `git diff --check` passed.
- 2026-07-18: Fixed BUG-031 through BUG-033. Broadcast preview setup is now
  transactional, confirmation callbacks are acknowledged before delivery,
  stop/reset recover pending confirmations, and delivery supports raw HTML while
  preserving existing Telegram formatting. Added 8 focused regressions; all 112
  tests and Ruff fatal-error checks passed.
