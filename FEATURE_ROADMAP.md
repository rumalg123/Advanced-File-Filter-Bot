# Feature Implementation and Live-Rollout Register

This document is the source of truth for the additive feature program started on
2026-07-18. Code, tests, rollout decisions, and status changes must reference a
feature ID below. Multilingual search is explicitly out of scope.

Status values: `Planned`, `In progress`, `Implemented (off)`, `Enabled`,
`Blocked`.

## Live-safety contract

1. New behavior is guarded by a dedicated feature flag that defaults to `false`.
2. Existing commands, callback payloads, cache keys, and MongoDB documents remain
   backward compatible.
3. New persistence is additive. Existing collections are not rewritten in place;
   indexes are created lazily and idempotently.
4. Optional fields are read with safe defaults so old documents remain valid.
5. Indexing and file-delivery hooks fail open: a feature failure is logged but
   cannot prevent indexing, search results, or file delivery.
6. User mutations are idempotent where Telegram retries are possible.
7. Every feature must have regression tests for both enabled and disabled states
   before it may be marked `Implemented (off)`.
8. A feature may be marked `Enabled` only after its flag is deliberately enabled
   in deployment and a live smoke test succeeds.
9. Rollback is performed by disabling the flag; no destructive data migration is
   required.

## Feature register

| ID | Status | Feature | Flag | Acceptance criteria |
|---|---|---|---|---|
| FEAT-001 | Implemented (off) | Saved searches and new-file alerts | `FEATURE_SAVED_SEARCH_ALERTS` | Users can save, list, pause/resume, and delete searches; newly indexed matching files produce deduplicated notifications without blocking indexing. |
| FEAT-002 | Implemented (off) | Favorites and named collections | `FEATURE_FAVORITES` | Users can add/remove files, create collections, list contents, and delete a collection; missing/deleted media is skipped safely. |
| FEAT-003 | Implemented (off) | Advanced search filters | `FEATURE_ADVANCED_SEARCH` | Search accepts validated type, year, language, quality, season, episode, and size constraints while an unqualified query retains current behavior. |
| FEAT-004 | Implemented (off) | Recommendation feedback | `FEATURE_RECOMMENDATION_FEEDBACK` | "More like this" and "Not interested" feedback changes ranking, invalidates the user cache, and never attributes feedback to the wrong file. |
| FEAT-005 | Implemented (off) | File reporting and health workflow | `FEATURE_FILE_REPORTS` | Users can report broken, incorrect, duplicate, or poor-quality files; repeat reports are deduplicated and admins can list/resolve them. |
| FEAT-006 | Implemented (off) | Search autocomplete | `FEATURE_SEARCH_AUTOCOMPLETE` | Inline/private suggestions use valid indexed/search-history candidates, exclude the exact query, enforce ownership, and stay within Telegram callback limits. |
| FEAT-007 | Implemented (off) | Duplicate-file grouping | `FEATURE_DUPLICATE_GROUPING` | Search can group likely variants by canonical title and expose quality variants without hiding files when metadata is incomplete. |
| FEAT-008 | Implemented (off) | User request tracking | `FEATURE_REQUEST_TRACKING` | Users can view their requests and statuses, duplicate requests are detected, and completion/rejection transitions are persisted and notified idempotently. |
| FEAT-009 | Implemented (off) | Recently viewed/downloaded history | `FEATURE_RECENT_FILES` | Successful deliveries append bounded history; users can list and clear it; failed deliveries never appear. |
| FEAT-010 | Implemented (off) | Recommendation explanations | `FEATURE_RECOMMENDATION_EXPLANATIONS` | Recommendation results include a safe reason such as search history, related file, or trending without exposing another user's behavior. |
| FEAT-011 | Implemented (off) | Admin content dashboard | `FEATURE_CONTENT_DASHBOARD` | Admins can view currently unresolved zero-result searches, popular searches, report counts, request demand, and index/file-health summaries; successful/later-indexed matches self-heal through bounded current-search validation. |

## Delivery order

1. Add flags, shared persistence models/repositories, indexes, cache keys, and
   callback-safe identifiers.
2. Implement user-owned data features: FEAT-002 and FEAT-009.
3. Implement feedback and explanations: FEAT-004 and FEAT-010.
4. Implement saved-search notifications: FEAT-001.
5. Implement reports and request tracking: FEAT-005 and FEAT-008.
6. Implement advanced search, autocomplete, and duplicate grouping: FEAT-003,
   FEAT-006, and FEAT-007.
7. Implement the aggregate admin dashboard: FEAT-011.
8. Run the full regression suite, import/compile checks, disabled-state tests,
   and update this register.

## Commands and syntax

| Feature | User/admin entry points |
|---|---|
| Saved searches | `/save_search <query>`, `/saved_searches` |
| Favorites | Reply to a delivered file with `/favorite [collection]`; `/unfavorite`, `/favorites [collection]`, `/collections`, `/collection_create`, `/collection_delete` |
| Advanced search | `title type:video year:2025 quality:1080p maxsize:2GB`; `/search_help` |
| Recommendation feedback | Buttons attached to successfully delivered files |
| File reports | Report button on delivered/failed files; admin `/file_reports`, `/resolve_report` |
| Autocomplete | `/suggest <partial title>` |
| Duplicate grouping | Automatic result presentation when enabled |
| Request tracking | `/myrequests`; existing admin request buttons persist status |
| Recent files | `/recent`, `/clear_recent` |
| Recommendation explanations | Automatic text in `/recommendations` when enabled |
| Content dashboard | Admin `/content_dashboard` |

## Production rollout procedure

1. Deploy with every `FEATURE_*` value left `false`; run `/start`, a normal
   search, pagination, one file delivery, and one existing request as smoke tests.
2. Enable one flag through `/bsetting` (or set it in `bot_settings`) and restart
   the process. Environment values initialize new settings only when that key is
   not already present in the database.
3. Run the feature's command/callback smoke test and watch error/rate-limit logs.
4. Continue with the next flag only after the current feature is stable.
5. To roll back, set that flag to `false` and restart. Additive user data remains
   stored and becomes available again if the feature is re-enabled.

## Verification log

- 2026-07-18: Register created. All new flags are required to default off because
  the working tree is deployed directly to a live system.
- 2026-07-18: FEAT-001 through FEAT-011 implemented as additive, default-off
  features. Multilingual search was not implemented, as required.
- 2026-07-18: Added 15 rollout/regression tests covering disabled behavior,
  enabled registration, persistence ownership, deduplication, callback safety,
  advanced filters, recommendations, request transitions, and bounded dashboard
  aggregation. Full suite result: 44 passed.
- 2026-07-18: Verification passed for Python compilation, targeted full Ruff
  checks on new modules, repository-wide undefined-name checks, dependency
  consistency (`pip check`), import smoke coverage, and `git diff --check`.
- 2026-07-18: No feature is marked `Enabled`. A deployment smoke test is still
  required before enabling each flag individually in production.
