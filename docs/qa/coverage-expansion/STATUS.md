# Coverage expansion and remaining gates

This is the active continuation of the 2026-10-29 QA report. The operator has
confirmed that all MongoDB URIs and channel/group destinations in `.env` are
QA fixtures and authorized their mutation for testing. Messaging stays confined
to the supplied accounts and QA destinations, because copied databases may
contain unrelated user identities.

## Measurement

Coverage now includes `bot`, `config`, `core`, `handlers`, `repositories`, and
`scripts`, with branch measurement enabled. The expanded baseline is 470 passing
tests, 16,322 executable statements, and 44% combined statement/branch coverage.
The earlier 48.05% line measurement had a smaller source denominator. Neither
measurement excludes uncovered application files to improve the percentage.
Live execution is instrumented and will be combined with automated coverage.
The 100% target is not yet reached.

## Verified fixes in this continuation

| Finding | Status | Evidence |
|---|---|---|
| Failed/cancelled Mongo initialization retained a dead client; multi-DB startup could retain and later accept an incomplete topology. | Passed QA | Four reproductions failed before remediation. Failed clients and partial topology are rolled back; retry initializes every source. Twelve focused recovery/multi-DB tests passed. |

## Work still in progress

- Instrumented live coverage of the supplied QA bot, accounts and existing chats.
- High-gap settings, administration, search, repositories and failure branches.
- PH-006 representative query performance and PH-028 authoritative ownership.
- Current operator docs, passed-status reconciliation and removal of obsolete
  candidate notes after their remaining items are covered.

Completed historical reports retain their timestamps; operational instructions
that are still needed are not treated as obsolete merely because a bug is fixed.

- **Passed QA:** admin/owner/private/auth-user permission decorators now use
  plain-text callback alerts. Four regressions reproduced literal HTML before
  the fix; 31 authorization/formatting tests pass. Database callbacks were
  already correctly admin-protected; the added tests preserve that behavior.

- **Passed automated QA:** settings View/Edit/Back/Close callbacks acknowledge
  Telegram before performing slow work. Four pre-fix failures reproduced the
  missing answers; eight focused navigation/formatting tests pass. Live sweep
  also observed the View callback timeout before this fix.

- **Passed QA:** generic repository updates now treat matched no-op writes as
  successful and return an actual boolean for upserts, including an inserted
  identity of zero. Real-Mongo CRUD/cache/aggregation/connection/filter contracts
  and existing regression suites passed (76 focused cases).

- **Passed QA:** premium entitlement now ends at the exact expiry instant,
  consistent with zero remaining days and the documented future-expiry policy.
  Validation/permissions/premium/access boundary suites pass; 49 new validation
  cases cover public inputs and remote permission outcomes.

- **Passed QA:** settings writes now reject malformed integers/booleans,
  non-finite floats and unsafe numeric bounds instead of silently persisting
  zero/false. Legacy invalid stored values fall back without rewriting records;
  imports count only acknowledged writes. Nineteen new pre-fix failures were
  reproduced; 60 focused settings/config/access cases pass.
- **Live passed:** all 61 settings details across eight pages rendered through
  the real bot after callback-ack remediation. Edit/cancel and mutations are
  being exercised separately using actual current keyboard buttons.
