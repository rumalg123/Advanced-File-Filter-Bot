# Bug Audit and Fix Register

> Current continuation: [QA evidence and remaining gates](docs/qa/coverage-expansion/STATUS.md). Earlier dated test counts below are historical; source defaults and production rollout status remain separate from QA enablement.

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
| BUG-006 | High | Fixed | Packaging | `pyproject.toml` installs Pyrofork while `requirements.txt` installs unpinned Wzgram Git HEAD; platform markers also disagree. | Both manifests install `wzgram` from PyPI using consistent platform markers; latest published releases are requested by the operator (2026-10-29). |
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
| BUG-034 | High | Fixed | Cache observability | `/cache_analyze` calls scalar `GET` on sorted-set recommendation and history keys, flooding logs with `WRONGTYPE` errors and potentially scanning the entire Redis database for a small serialization sample. | Monitoring checks Redis types, reads only serialized strings, uses a type-safe size fallback, and enforces a bounded examination limit without mutating live keys. |
| BUG-035 | Medium | Fixed | Performance command | `PerformanceMonitor` returns canonical `process_memory_rss_mb` and `process_cpu_percent` fields, but `/performance` still indexes removed `memory_mb` and `cpu_percent` aliases and fails with `KeyError`. | The command consumes canonical process metrics with backward-compatible fallback values and renders successfully when aliases are absent. |
| BUG-036 | Low | Fixed | Recommendation formatting | The recommended-files heading contains a double-decoded UTF-8 book emoji and displays `ðŸ“š` to Telegram users. | The source contains the intended `📚` character and a rendered-message regression rejects the mojibake sequence. |
| BUG-037 | High | Fixed | Content dashboard | Zero-result demand is incremented when result delivery fails rather than when MongoDB has no matches, and is never resolved after a successful search or later indexing, so valid titles remain indefinitely in the dashboard. | Analytics use authoritative access/search totals, successful matches remove stale demand, and the bounded dashboard pass revalidates and cleans existing rows against current MongoDB search behavior. |
| BUG-038 | High | Fixed | Handler lifecycle | Command and database handlers bypass `HandlerManager`, dispatcher groups are discarded, managed cleanup marks handlers removed without removing them, and `/verify` can still report 100/100 while listing issues. | Every top-level handler has managed cleanup and shutdown signaling; registration/removal preserves dispatcher groups; shutdown removes tracked handlers; the verifier recognizes the complete configured handler set and any warning or issue lowers its score. |
| BUG-039 | Medium | Fixed | Command routing | Search excludes a hard-coded command list, so newer commands such as `/verify` also run as file searches and send a false no-results response. | Text beginning with `/` never reaches file search, including bot-qualified and future command names; ordinary text search remains unchanged. |
| BUG-040 | Medium | Fixed | Transient command messages | Core user responses such as `/start`, `/help`, and `/stats`, plus several user feature-command confirmations, bypass `MESSAGE_DELETE_SECONDS` and leave stale menus in private chats. | User-facing informational responses and feature confirmations use one task-managed cleanup path, respect the current configured delay, and remain persistent when the delay is `0`; admin diagnostics and deep-link subscription gates are not shortened. |
| BUG-041 | High | Fixed | Owner shell | Synchronous process waits block the bot; command/output HTML is interpreted; failed or concurrent file output can leak/collide. | Async children keep unrelated work responsive; timeout/cancel terminates the owned process group; output is literal; unique files are removed on write/upload failure. Nine process/authorization cases pass. |
| BUG-042 | High | Fixed | Multi-source search | Broad/deep distributed sorts exceed MongoDB memory; earlier rows cross the network before a last-page callback can answer. | Bound each server top K, use the optional stable sort index for deep pages, and skip only mathematically guaranteed prefixes. Real page 3,657 returns in about 1.15s with exact file order. |
| BUG-043 | High | Fixed | Callback outage UX | Pagination can wait through long database retries until Telegram expires its answer; settings page acknowledgment follows slow rendering. | Page reads have an eight-second deadline with a safe retry alert and no partial publication; settings navigation answers before rendering. Real secondary-partition alert returned in 8.047s and recovered. |
| BUG-044 | High | Fixed | Search-token backfill | Ordinary array equality can accept an old array inside a concurrently nested source, storing incomplete tokens and hiding a legacy match. | Exact expression/literal snapshot equality skips concurrent changes; real-Mongo legacy/indexed equivalence is preserved. |
| BUG-045 | High | Fixed | Topology configuration | URI-only deduplication drops distinct databases on one deployment and can shift the following database's name. | Normalize URI/name pairs together, deduplicate exact pairs only, retain documented fallback names and reject excess names. |
| BUG-046 | High | Fixed | Connection recovery | Failed/canceled clients and partially initialized multi-source topology survive into a later startup attempt. | Roll back client/topology publication and close every opened pool before retry. Failure and cancellation regressions pass. |
| BUG-047 | Medium | Fixed | Repository writes | Matched no-op updates report failure and upsert success can return an identity rather than a boolean. | Matched records/upserted identities return an actual success boolean, including identity zero; real-Mongo CRUD contracts pass. |
| BUG-048 | Medium | Fixed | Settings validation | Malformed numeric/boolean edits silently coerce to zero/false and unsafe bounds can persist. | Reject malformed/non-finite/out-of-range writes; invalid legacy values fall back without rewriting records; imports count acknowledged writes. |
| BUG-049 | Medium | Fixed | Update recovery | Same-second backups overwrite a recovery point; failed backup copies do not stop update application. | Unique complete backups are required before clone/apply; operator scripts participate in backup/restore; temporary-installation recovery tests pass. |
| BUG-050 | Medium | Fixed | Legacy migration | Unsafe batch/limit inputs, naive timestamps and stale optimistic writes misreport or overwrite metadata. | Validate bounds, write UTC, preserve concurrent source/metadata changes and count actual modifications; dry-run/global multi-source limits pass. |
| BUG-051 | Medium | Fixed | Premium expiry | Entitlement remains valid at the exact expiry instant despite zero remaining time. | Only a future expiry grants entitlement; boundary and access contracts pass. |
| BUG-052 | Medium | Fixed | Batch delivery | A failed source can become a partial missing-file mapping, and duplicate owners silently overwrite a batch result. | Complete-or-error batches use authoritative owners where enabled, reject ambiguity, avoid partial cache entries, show retry UX and refund unsent quota. |
| BUG-053 | Medium | Fixed | Settings edit lifecycle | Failed input deletion misreports a persisted save; older completion can clear a newer edit; cancellation leaves captured sessions pending. | Confirm successful writes independently of optional message cleanup; fence cancellation to the captured session and await cleanup during shutdown. Behavioral and real-Redis tests passed. |
| BUG-054 | Medium | Fixed | Edit expiry | UI advertises 60 seconds but stored edits live 300 seconds and accept the exact expiry boundary. | Session TTL matches the UI and expires at the deadline; real-Redis pointer/TTL contracts passed. |
| BUG-055 | High | Fixed | Media references | Empty wzgram file references collide in the sparse unique index and silently discard later media. | Generate a stable fallback only at writes; real codec and MongoDB tests preserve legacy null reads and caller values. |
| BUG-056 | High | Fixed | Media aliases | A colliding alias can be reported as a harmless duplicate or return another canonical identity. | Different canonical identities return an explicit conflict; real-Mongo sparse-index/cross-namespace regressions passed. |
| BUG-057 | High | Fixed | Ownership activation | A one-source activation writes permanent bindings although the bot cannot start that configuration. | Reject before binding/index writes; read-only one-source inventory remains allowed. Library and CLI regressions passed. |
| BUG-058 | Medium | Fixed | Settings retries | Selecting the already-saved boolean or reset value reports MESSAGE_NOT_MODIFIED as failure. | Treat unchanged detail rendering as successful; both callback regressions and real repeated-boolean edits passed. |
| BUG-059 | High | Fixed | Redis deployment | Default protected-state Redis answers local health probes but denies the bot's separate container, preventing split-mode startup. | Permit connections on the private, unpublished Compose state network; retain optional ACL authentication. A real separate-container regression fails before the fix and passes afterward; CI runs it. |
| BUG-060 | High | Fixed | Database capacity | Write-source selection counts document bytes but ignores index bytes, so it can keep selecting a source whose logical storage budget is exhausted. | Include MongoDB `indexSize` with `dataSize`; exact-limit, index-only and real-Mongo index-growth regressions switch to the available source. Provider/cluster headroom still needs monitoring. |
| BUG-061 | High | Fixed | Docker startup | Every startup upgrades packages despite disabled auto-update, changing tested dependencies or failing without package-index access. | Use Dockerfile-installed packages during Docker setup; successful/unavailable installer regressions and an offline image setup check prevent runtime installation. Explicit code-update flows remain separately controlled. |
| BUG-062 | High | Fixed | Update and restart | `/restart` runs Git in an image without a valid checkout, failing with exit 128. The initial fix also incorrectly removed the command's code-update behavior. | Restore update-before-restart using the validated backup/temporary-clone updater and the configured upstream branch. Preserve secrets and mutable data, install changed requirements, record the applied revision, cancel restart on failure, and gracefully stop through wzgram so Compose restarts the updated container. Real Git branch/update/failure tests and real wzgram shutdown cover this contract. Commit `ffd9d63` is superseded. |
| BUG-063 | Medium | Fixed | Durable indexing notifications | Durable channel indexing completes jobs but bypasses the memory worker's `LOG_CHANNEL` summary. | Share the summary sender and notify after acknowledging a newly indexed durable job. Duplicate replays and lost leases stay quiet. Notification failure is logged and never requeues indexed media or repeats saved-search fan-out. Summaries are best-effort; completed historical jobs are not replayed. |
| BUG-064 | High | Fixed | Maintenance scan limits | The ownership CLI accepts/defaults to ten million records while its library rejects values above one million; the backfill regression still treats an intentionally supported limit as invalid. | Share the ten-million maximum between CLI/library/backfill, align ownership defaults, retain the one-million backfill default, validate integer bounds and update boundary regressions. Real-Mongo CLI activation/inventory pass with the new default. |
| BUG-065 | Medium | Fixed | Operator diagnostics | Ownership and backfill CLI errors interpolate raw exception text that may expose connection strings, credentials or media values. | Keep exception type and numeric MongoDB code; omit arbitrary message/detail payloads. Authentication, connection and duplicate-key regressions confirm diagnostic categories without credentials. |
| BUG-066 | Medium | Fixed | Inline search | Access-check failures escape before the search error handler, and slow checks/searches can outlive the inline response window. An expired error reply can also escape dispatch. | Bound the entire inline operation to eight seconds, cancel slow work and attempt a safe retry answer; contain expired/error answers. Existing access gates, personal results and page offsets remain covered. |
| BUG-067 | Medium | Fixed | Search captions | User queries are interpolated directly into HTML captions, interpreting valid tags or rejecting unsupported tags instead of displaying the query literally. | Escape query text in the shared initial/pagination caption formatter. Private and group captions preserve literal markup and ampersands; group ownership, sessions, error paths and cleanup remain covered. |
| BUG-068 | Medium | Fixed | Send All ownership | The private callback handler checks the button owner but does not independently check the cached search owner. A handler-level forged-owner fixture can enter delivery with another user's session. | Check cached ownership before reservation or delivery, matching the deep-link path; a forged-owner regression denies the request without sends or quota writes. |
| BUG-069 | Medium | Fixed | Send All captions | Cached queries are interpolated into HTML progress/completion messages, so literal tags can break the transfer setup or be interpreted as formatting. | Escape the query once for every Send All status; a literal-tag/ampersand regression verifies both progress and completion while files still send. |
| BUG-070 | Medium | Fixed | Bulk delivery settlement | Send All marks definitely unsent/cancelled work as uncertain and can count a successful delivery again as failed when recent-history storage fails. | Use shared exception-safe delivery progress for setup, lookup, send and cancellation. Charge confirmed sends, distinguish unknown in-flight sends from unsent work, and isolate optional recent-history failures. Six new settlement/counter cases and existing setup regressions pass. |
| BUG-071 | High | Fixed | Ordinary batch bounds | Batch creation accepts reversed, zero and oversized message ranges; encoded DSTORE links bypass bounds and accept invalid modes or a zero chat. | Validate inclusive ranges against the existing configured maximum before Telegram/access/quota work at both entry points. Preserve legacy single-message batches and three-field payloads; reject invalid chat/mode/base64. No configured limit is reduced. |
| BUG-072 | Low | Fixed | Settings labels | Indexed media search has no display-name mapping, so `/bsetting` shows the uppercase environment key. | Display `Indexed Search` in the settings menu and detail view, consistently with the other feature controls; the stored key and behavior stay unchanged. |
| BUG-073 | Medium | Fixed | Favorites cleanup | `/unfavorite` refuses to remove stored membership after the catalogue file has been deleted, leaving stale favorites behind. | Remove by the supplied unique ID when media is absent, for both typed commands and replies. Adding unavailable media still fails. Three focused cases pass. |

## Group search follow-up, 2026-10-30

BUG-067 escapes user text in the shared search caption formatter. **Eight
focused cases pass**, including private/group literal-query captions, group
scope and original-user ownership, empty/denied/unavailable paths, custom-filter
fallback, callback size limits, session ownership and result-only auto-deletion.
This changes presentation only; search matching still receives the original
sanitized query.

## Inline search follow-up, 2026-10-30

BUG-066 has **20 passing focused cases** covering normal/admin access,
subscription exemptions, ban/premium/rate gates, empty and failed searches,
personal result caching, page offsets, access-check exceptions, expired answers
and cancellation of slow access/search work. The deadline covers checks before
the previous inner search handler. Timeout responses attempt an uncached retry
answer; Telegram may already have expired a query, in which case the dispatcher
contains that error.

## Operator follow-up, 2026-10-30

BUG-064 (`147917e`) and BUG-065 (`ca3ae8a`) resolve the two failures recorded
below. The increased limits are preserved: ownership inventory/activation
default and maximum 10,000,000 per source; token backfill default 1,000,000,
maximum 10,000,000. The complete source suite now passes **878 tests, zero
failures/errors/skips**, with 22 existing warnings. Full compilation,
undefined-name lint and whitespace checks pass. Large bounds are exercised
using small fixtures; this is not a ten-million-record performance benchmark.

## Notification follow-up, 2026-10-30

BUG-063 has 13 passing new regressions, including two real-Mongo job-completion
cases. All 33 notification/indexing/saved-alert tests pass in the full run.
The full branch run reports **842 passed, 2 failed**, with 22 existing warnings.
The two failures concern the recent operator-script changes, outside this fix:
the backfill bounds test retains its old one-million limit, and the ownership
CLI emits raw exception text that its privacy regression rejects. Those changes
are preserved for a separate follow-up. The raised ownership CLI default also
exceeds the existing library's one-million inventory/activation bound and needs
alignment before using the new default. No production service was accessed.

## Current QA, 2026-10-30

The latest bounded round passed **927 tests with zero failures or skips** and
live Send All/batch checks on wzgram 3.1.5. Source-matched coverage is
**69.82% lines, 56.00% branches, 66.38% combined**. The
[current QA report](docs/qa/coverage-expansion/STATUS.md) records this round's
scope, configuration, cleanup and earlier feature/multidatabase evidence.
Whole-bot 100% coverage and production operational gates remain open. Earlier
dated counts remain historical; feature source defaults remain off.

## Verification log

- 2026-10-29 live timer QA: a four-second search timer was described as
  "0 minutes". Search captions now display exact minutes/seconds and singular
  units; zero continues to suppress the notice. Duration regressions cover
  sub-minute, minute and mixed intervals. No storage changes.

- 2026-10-29 live QA: a private indexing link produced both its indexing
  confirmation and a false file-search no-results response. Indexing input now
  raises `StopPropagation` after its own response; valid and inaccessible-channel
  regressions ensure the later search group cannot consume it again. No schema
  changes; rollback is a code revert.

- 2026-10-29 live QA: `/add_channel` raised `AttributeError` because managed
  startup never populated the bot's public handler references. All configured
  handler aliases now point to the same instances owned by `HandlerManager`.
  Added startup regressions with filter support enabled and disabled. No data
  changes; rollback is a code revert.

- 2026-10-29: Operator requested latest published `wzgram` rather than the
  historical Git pin. Both dependency manifests now use `wzgram`. The rebuilt
  Python 3.13 image resolved version 3.1.5; all 456 tests passed with real
  isolated MongoDB/dual Redis, and both supplied newer-format user sessions
  authenticated inside that image. `pip check` and undefined-name lint passed.

- 2026-10-29 QA: real normal-user `/help`, `/stats`, and search failed with
  `PEER_ID_INVALID` / `BUTTON_URL_INVALID` when `AUTH_CHANNEL=0` was loaded
  from stored settings. Database sync bypassed startup normalization and
  re-enabled subscription checks for the string `"0"`. Applied the same parser
  after sync; added zero/empty/None/numeric/username regressions. Repeated live
  commands and search succeeded. Rollback is a code revert, with no schema changes.

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
- 2026-07-19: Fixed BUG-034 and BUG-035 from production observability logs.
  Cache analysis is Redis-type-aware and bounded, while `/performance` consumes
  the current process metric schema. No Redis keys are deleted or migrated.
- 2026-07-19: Fixed BUG-036 and BUG-037. Restored the recommendation heading
  emoji, made zero-result writes depend on authoritative search totals, and added
  a concurrency-bounded dashboard reconciliation that removes historical rows
  once their query matches an indexed file.
- 2026-07-19: Fixed BUG-038. Command and database registrations now participate
  in the shared handler lifecycle, dispatcher groups survive registration and
  removal, and managed shutdown removes rather than merely forgets handlers.
  `/verify` now knows the complete handler set and uses non-saturating scoring.
  All 123 tests, `compileall`, Ruff fatal/undefined-name checks, Markdown fence
  validation, and `git diff --check` passed.
- 2026-07-19: Fixed BUG-039. Replaced the manually synchronized search command
  list with a general command-prefix filter plus an in-handler safety guard, so
  current and future slash commands cannot fall through to file search. All 130
  tests passed.
- 2026-07-19: Fixed BUG-040. Core informational commands and user feature
  confirmations now use shared, manager-tracked auto-deletion based on the live
  `MESSAGE_DELETE_SECONDS` value. Incoming user commands, admin diagnostics, and
  deep-link subscription gates remain untouched. All 136 tests passed.
