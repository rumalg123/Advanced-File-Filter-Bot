# Real-Time Interactive UX Consistency

This document is the source of truth for interactive messages whose displayed
state can become stale after a user action. It supplements the feature-specific
CRUD documents: persistence remains authoritative, while Telegram messages are
views that must be refreshed after successful mutations.

Implementation status: verified on 2026-07-18 with 86 passing tests.

## Core rule

For every callback mutation, use this sequence:

1. Validate the clicking user and the callback target.
2. Persist the mutation through the existing owner-scoped repository method.
3. Re-read the affected state when a menu represents more than one record.
4. Edit the same Telegram message (text and/or keyboard) to show current state.
5. Acknowledge the callback exactly once.

Do not leave a successful action represented by an old button, delete a useful
management menu merely because one row changed, or create detached confirmation
messages when the originating menu itself can show the confirmation.

## UX state matrix

| Surface | Mutation | Required live result |
|---|---|---|
| Collection list | Clear/delete/cancel | Use the same message for confirmation, then re-render all existing collection buttons and counts from MongoDB. |
| Collection picker | Add/remove file | Keep the picker open and switch that collection between `➕` and `✅`; allow several memberships to be changed in one visit. |
| Delivered-file favorites | Favorite/remove | Mark Favorite as selected after add and restore the normal action after removal. |
| Delivered-file recommendations | More/less/reset | Mark the active signal, clear the other marker, and restore both actions on reset. |
| Delivered-file report | Choose reason | Open reasons in the existing keyboard and replace them with a submitted/subscribed marker after selection. |
| Saved searches | Pause/resume/delete | Re-read and edit the same saved-search menu, including text status, button action, and row removal. |
| Favorites/recent/preferences lists | Remove/reset row | Remove only the affected row; delete the transient list only when no rows remain. |

## Compatibility and safety

- Feature flags remain authoritative; disabled features register no new flow.
- Existing callback formats stay valid. New collection removal and picker-close
  callbacks use the existing compact file identifier and eight-character token.
- Every collection query remains scoped by both `user_id` and collection token.
- Callback data must stay within Telegram's 64-byte UTF-8 limit.
- Edits are best-effort after persistence. If Telegram rejects an edit (for
  example, an expired message), the mutation remains valid and the callback
  alert still tells the user what happened.
- Existing `MESSAGE_DELETE_SECONDS` scheduling is retained. Editing a message
  does not create another cleanup task.
- Direct commands create a fresh snapshot; they cannot safely locate and edit
  arbitrary older command messages. Interactive callback menus are refreshed.
- No migration, cache flush, or destructive database rewrite is required.

## Findings

| ID | Finding | Resolution |
|---|---|---|
| UX-001 | Collection clear/delete confirmations were detached replies, leaving the original list stale. | Edit the list into confirmation and re-render it after confirm/cancel. |
| UX-002 | Collection picker deleted itself after add and did not expose existing membership or removal. | Render membership markers and add/remove toggles in place. |
| UX-003 | Favorite and recommendation actions persisted state but kept unselected labels. | Update action labels on the delivered file keyboard. |
| UX-004 | Saved-search pause/resume/delete deleted the entire management message. | Re-fetch and re-render the same menu. |
| UX-005 | Report reasons were sent as an extra message and selection left no status on the file. | Reuse the original keyboard and replace reasons with a report-state marker. |
| UX-006 | Collection cancel handling was duplicated and both branches discarded context. | Keep one callback branch and restore the live collection list. |

## Acceptance checks

- Deleting collection B from a menu containing A, B, and C leaves the same
  message showing only A and C.
- Clearing a collection immediately changes its displayed count to zero.
- A picker shows `✅` for current memberships and toggles add/remove without
  closing.
- Favorite, More like this, Not interested, and report state are visible on the
  message where the action occurred.
- Saved-search status and rows update without reopening `/saved_searches`.
- Stale, missing, and cross-user callback targets do not mutate data.
- Regression tests cover live rendering, callback acknowledgements, callback
  size, cleanup behavior, and existing removal flows.

## Verified existing live-update flows

The audit also inspected adjacent callback-driven state. Connection
activation/deactivation/deletion re-renders the current connection view, request
resolution replaces the admin action keyboard with its terminal status, bot
setting boolean/default mutations re-open current setting details, and existing
favorites/recent/recommendation-list removals remove only their affected rows.
These paths already follow the core rule and were intentionally left unchanged.
