# Premium Duration and Quota Consistency

This document is the source of truth for premium duration, expiry, remaining-day,
and daily-quota displays. Stored user dates are authoritative for an existing
grant; configuration values are defaults for future grants and plan advertising.

Current status: **QA passed, 2026-10-30** — 1,199 automated tests and 17 live
premium/quota checks. See the [bounded QA record](../qa/coverage-expansion/STATUS.md#bounded-qa-round-9--premium-grants-removal-expiry-and-quotas-2026-10-30).
The earlier 2026-07-18 acceptance used 104 tests and remains historical.

## Data ownership rules

- `PREMIUM_DURATION_DAYS` is the default for a future `/addpremium user_id`
  grant. Changing it must never rewrite an existing user's activation or expiry.
- `/addpremium user_id Nd` overrides only that grant and stores
  `premium_expiry_date = activation + N days`.
- The handler passes the effective default or override explicitly so persisted
  expiry, admin output, user notification, and log text use one value.
- Active/expired state and remaining days come only from the stored
  `premium_expiry_date`, never from the current configured default.
- `/plans` may advertise the configured **default duration**, but the user's
  status must show their stored expiry and derived remaining days.
- `NON_PREMIUM_DAILY_LIMIT` is the current limit. A stored retrieval count is
  today's usage only when `last_retrieval_date` is today; displayed remaining
  quota is never negative.
- Database-backed settings require the existing restart flow. On restart, new
  repositories receive the new defaults; existing user expiry dates remain
  untouched.

## Findings

| ID | Finding | Resolution |
|---|---|---|
| PRM-001 | Remaining days used `timedelta.days`, flooring partial days and showing 99 immediately after a 100-day grant. | Round positive remaining time up to the next whole day. |
| PRM-002 | Optimized batch premium checks separately floored remaining days. | Use the same ceiling rule in batch status output. |
| PRM-003 | A positive cached status message could cross a remaining-day boundary while retaining the old count. | Bound cache TTL by the next displayed-day transition and actual expiry. |
| PRM-004 | Single-user checks required an activation date while optimized checks relied on expiry, causing legacy-record drift. | Make stored expiry authoritative; expire only missing/expired expiry records. |
| PRM-005 | `/plans` labelled the current config as `Duration`, which could look like an override user's duration. | Label it `Default duration` and show stored expiry under active status. |
| PRM-006 | `/plans` could show yesterday's counter or a negative remaining count after the daily limit changed. | Reset display usage by date and clamp remaining quota to zero. |
| PRM-007 | Premium user statistics counted the stored flag until hourly cleanup, even after expiry. | Count only future normalized expiry dates, use a versioned cache key, and expire that cache at the nearest active expiry. |
| PRM-008 | Invalid default durations such as zero could be stored through settings or loaded from environment. | Enforce `1..36500` in Pydantic configuration and database-setting writes. |
| PRM-009 | Some quota-reservation paths trusted the raw premium flag after access checks. | Derive quota exemption from both the flag and a future stored expiry. |
| PRM-010 | At the exact expiry instant, entitlement returned true while remaining days returned zero. | Passed QA: entitlement now requires a strictly future expiry; exact-boundary, timezone and access regressions pass. |
| PRM-011 / BUG-101 | Stale profiles block valid changes or overwrite active grants, expired flags block renewal, and concurrent grants all succeed. | Use authoritative reads and a guarded MongoDB write; allow expired grants to be replaced, preserve active grants and return persisted dates. |
| PRM-012 / BUG-102 | Cleanup can revoke a fresh grant, reset consumed quota through the single-user path, or abort all work on one malformed legacy date. | Recheck normalized expiry at the write, preserve quota and safely process raw cleanup IDs/dates. |
| PRM-013 / BUG-103 / CACHE-025 | Rounded/stale/malformed decision-cache entries can contradict current entitlement. | Validate tuple shape and compare the cached decision with the passed user's current flag/expiry before returning it. |

## Acceptance checks

- A new 100-day override displays 100 days and its exact stored UTC expiry.
- Changing `PREMIUM_DURATION_DAYS` changes future default grants and plan text,
  but not any stored `premium_expiry_date`.
- A future expiry with no legacy activation date remains valid.
- Missing or expired expiry dates revoke the premium flag through the existing
  repository update path.
- Single and optimized batch checks use the same remaining-day rule.
- Yesterday's retrieval count displays as zero today, and lowering a daily limit
  never displays negative remaining quota.
- Premium aggregate counts exclude expired flags without waiting for cleanup.
- Invalid configured premium durations are rejected before persistence.
- An expired or missing expiry never bypasses quota merely because the stored
  premium flag is stale.

## Expiration and mutation behavior

An active grant is a flag plus a strictly future stored expiry. An expired raw
flag can receive a new grant; a repeated grant for an active subscriber leaves
their expiry unchanged. Mutations read MongoDB without the profile cache and
recheck eligibility in the write, so concurrent grants cannot overwrite one
another. User/log notifications follow persistence; notification failure does
not roll back the saved change.

Automatic expiry never resets consumed free-download quota, and its guarded
write cannot revoke a newly granted future expiry. Explicit administrative
removal retains the existing zero-count reset policy. Missing/malformed expiry
is inactive; batch cleanup safely normalizes legacy ISO strings and BSON dates
without skipping other subscribers. Current passed flag/expiry overrides a
contradictory cached status. Admin/owner access exemptions are unchanged.

Live acceptance used a disposable three-file daily limit, seven-day default,
two-day override and a local grant shortened to twelve seconds for wall-clock
expiry. Tests used both quota-ledger modes, concurrent reservations, partial
refunds and controlled UTC-day rollover. No system clock, production limits,
remote Atlas records or database schema were changed. Whole-bot 100% coverage,
production load and full hourly scheduling remain outside this bounded round.
