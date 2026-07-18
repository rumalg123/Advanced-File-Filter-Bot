# Collection and User-Feature CRUD Lifecycle

This document is the source of truth for user-managed collection CRUD and the
related optional-feature CRUD audit. All mutations are scoped by the clicking or
commanding Telegram user, and all feature flags remain authoritative.

Implementation status: verified on 2026-07-18 with 84 passing tests.

## CRUD coverage matrix

| Feature | Create | Read | Update | Delete | Decision |
|---|---|---|---|---|---|
| Named collections | `/collection_create` or first add | `/collections`, `/favorites` | Rename, clear, add/remove members | Delete with confirmation | Implement full command and callback management. |
| Saved searches | `/save_search` | `/saved_searches`, Run button | Pause/resume | Delete | Already complete; add Run for a direct read/use path. |
| Recent files | Automatic successful delivery | `/recent` | Automatic recency refresh | Remove one or `/clear_recent` | Add per-file removal. |
| Recommendation feedback | More/less button | `/recommendation_preferences` | More/less replaces prior signal | Reset one | Add user-visible read and reset actions. |
| File reports | Report action | Admin report queue | Resolve/merge lifecycle | Retained | Do not hard-delete operational audit records. |
| Content requests | Request submission | `/myrequests` | Admin status transitions | Retained | Do not hard-delete request/audit history. |
| Search analytics | Automatic | Dashboard | Automatic counters | Retention policy | Internal aggregate; no user CRUD surface. |

## Collection behavior

- `/collections` renders user-owned collection rows with Open, Clear, and Delete
  actions.
- Clear and Delete callbacks require an explicit confirmation.
- `/collection_rename "Old name" "New name"` renames in place while preserving
  membership and the collection's stable callback token.
- `/collection_clear collection name` removes every member but keeps the
  collection.
- `/collection_delete collection name` remains an explicit command deletion.
- Delivered files expose an Add to Collection action. It opens a transient picker
  containing only the clicking user's collections.
- Picker callbacks carry a stable eight-character collection token rather than a
  name or full document ID, keeping callback data below Telegram's 64-byte limit.
- Collection lookup always includes `user_id`; a callback token can never access
  another user's collection.
- Collections contain at most 100 distinct files. Duplicate adds are idempotent
  and reported separately from a full collection.
- Favorites and named-collection views expose per-file removal and update the
  rendered menu immediately after successful removal.

## Other user-managed data

- Recent-file menus expose Remove actions for individual history entries.
- Recommendation feedback menus resolve filenames, show each More/less signal,
  and expose Reset actions. Delivered file controls also expose Reset.
- Resetting recommendation feedback invalidates the user's cached personalized
  recommendations.
- Saved-search rows include a Run action using the existing user-owned search
  reference and pagination flow.

## Safety and compatibility

- Existing collection documents without `callback_token` remain addressable via
  the deterministic token already embedded in their `_id` and are backfilled on
  normal reads/writes.
- Renames do not change `_id`, so existing callbacks remain valid. Collection
  creation first checks normalized names so renamed documents are not duplicated.
- Destructive callback operations use confirmations; stale callbacks return a
  not-found alert without touching other data.
- Interactive menus follow `MESSAGE_DELETE_SECONDS`; `0` preserves persistent
  behavior.
- No destructive migration, Redis flush, or MongoDB rewrite is required.

## Acceptance checks

- A user can create, list/open, rename, clear, and delete a collection.
- A delivered file can be added to any owned collection and removed from its
  collection view.
- Cross-user collection tokens cannot read or mutate another user's collection.
- Recent history supports per-file and full deletion.
- Recommendation feedback supports list, replace, and per-file reset.
- Existing saved searches can be run directly and retain pause/resume/delete.
- Callback data stays within 64 bytes, transient menus are scheduled for cleanup,
  and all full-suite validation checks pass.
