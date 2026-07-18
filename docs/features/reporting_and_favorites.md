# File Reporting, Favorites, and Transient-Message Lifecycle

This document is the source of truth for the file-reporting and favorites
lifecycle. Changes must preserve the normal search and file-delivery flows and
remain inert when their feature flags are disabled.

Implementation status: verified on 2026-07-18 with 86 passing tests.

## Required behavior

### File reports

- An open issue is unique by `file_unique_id` and reason, not by reporter.
- The first reporter creates the issue. Later users reporting the same open
  issue are subscribed to it instead of creating duplicate reports.
- A user already subscribed to an issue receives an "already reported" alert
  and is not added twice.
- Every newly created issue and newly subscribed reporter is sent to
  `LOG_CHANNEL` when configured. The log includes report ID, filename, file ID,
  reason, reporter identity, and reporter count.
- Report records preserve the filename. Admin `/file_reports` output resolves a
  filename from the media repository for legacy records that do not have one.
- Resolving an issue notifies every subscribed reporter exactly once per
  resolution attempt. Legacy records fall back to their original `user_id`.
- Before sending a resolution message, the bot performs a Telegram user/chat
  access check. Blocked, deleted, or inaccessible users are skipped safely and
  reported in the admin result instead of failing the resolution.
- Notification outcomes are stored on the report for operational auditing.
- Report reasons replace the Report row on the delivered-file keyboard when
  possible. Selection replaces the reasons with a submitted, subscribed, or
  already-reported marker and retains a Report another issue action.
- A fallback reason message is used only if Telegram cannot edit the originating
  keyboard; it follows `MESSAGE_DELETE_SECONDS`.

### Favorites

- Delivered files expose both add-to-favorites and remove-from-favorites
  actions when `FEATURE_FAVORITES` is enabled.
- A successful Favorite action changes its delivered-file label to
  `✅ Favorited`; removal restores the normal label.
- `/favorites` file rows expose a remove action. Named collections use a compact
  callback when it fits Telegram's 64-byte callback limit; `/unfavorite`
  remains the fallback for long collection names.
- A successful removal updates the favorites menu row immediately.
- Favorites/recent-file menus and the files delivered from them follow
  `MESSAGE_DELETE_SECONDS`. Existing file-delivery cleanup remains authoritative
  for the delivered media.

### Other transient menus

- Saved-search action menus, autocomplete suggestion menus, and post-search
  recommendation menus follow `MESSAGE_DELETE_SECONDS` so they do not outlive
  the search context that created them.
- A zero delete interval preserves the current persistent-message behavior.

## Compatibility rules

- Existing reports containing only `user_id` remain readable and notify that
  user on resolution.
- Existing open report IDs remain valid for `/resolve_report`.
- New report IDs are deterministic for a file/reason pair, preventing concurrent
  duplicate creation without requiring a destructive database migration.
- Existing feature flags and callback prefixes remain valid.
- Report logging and user notification failures never roll back file delivery or
  make reporting unavailable.

## Acceptance checks

- Two different users reporting the same file and reason produce one open report
  with both user IDs.
- Resolving that report attempts notification for both users and safely skips a
  blocked user.
- Admin and log-channel report text contains the filename and file ID.
- Favorite add/remove callbacks affect only the clicking user's default
  collection; collection-menu removal uses the collection named by that menu.
- Report, favorites, saved-search, autocomplete, and recommendation menus are
  scheduled for cleanup only when `MESSAGE_DELETE_SECONDS > 0`.
- The full regression suite, compilation, undefined-name lint, dependency check,
  and whitespace validation pass before deployment.
