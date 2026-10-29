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

- **PH-006 candidate implementation passed local QA:** optional, default-off
  versioned word candidates preserve the existing final matcher. Eight complete
  result-set comparisons on 96,913 records matched, with representative title
  queries improving from 2.7–4.4s to 1–46ms. Metadata-only paths retain legacy
  performance. Bounded backfill, edit invalidation and older-image rollback are
  documented in `docs/INDEXED_MEDIA_SEARCH.md`. Remote p95 remains unmeasured.
- **Live settings edit passed:** invalid integer rejected without persistence,
  valid edit saved, cancel cleared the pending edit; all eleven pre-existing
  optional feature flags were enabled through real current keyboard buttons.

- **PH-028 implementation complete; local acceptance passed:** immutable
  majority-acknowledged coordinator reservations enforce cross-namespace alias
  uniqueness and owner-only CRUD, with stopped-writer activation, source bindings
  and explicit crash recovery. The 37 registry/operator cases achieve **100%
  line and branch coverage for those two modules**; 49 focused multi-DB/recovery
  cases pass. This does not imply whole-bot 100% coverage or a production rollout.
- **Remote activation passed:** all 96,908 records across the three authorized
  disposable MongoDB sources were inventoried without conflicts and adopted.
  Full remote race/restart/update/delete checks are being replayed after fixing
  a private harness-only async count error. Test bot writers remain stopped.
- **Current expanded automated baseline:** 16,829 statements, 52.03% line
  coverage and 48.47% combined statement/branch coverage before the final added
  ownership failure-path tests. Root operator modules were requested but not
  imported, so the next whole-tree measurement must include them explicitly.

- **Passed QA:** distributed batch delivery lookups now return a complete,
  unambiguous mapping or raise `SearchBackendUnavailableError`; they no longer
  convert source failures into partial `None` results or cache partial rows.
  Registry mode resolves authoritative owners even when a positive cache entry
  exists. Three behavioral regressions reproduced before remediation; 82 focused
  batch/ownership/search cases pass. Duplicate-input and genuine-missing-file
  behavior remains covered.

- **Updater recovery passed:** two pre-fix regressions reproduced overwriting
  same-second backup directories and continuing after a failed backup copy.
  Recovery points now have unique names; incomplete backups abort before clone
  or application. Operator scripts participate in backup/apply/restore. Thirty-
  three tests use temporary installations, including real file restoration;
  no updater was run against this server installation.

- **Legacy metadata migration passed:** twelve pre-fix failures reproduced
  invalid bounds, naive timestamps and overwriting/counting stale concurrent
  edits. The migration now validates bounds, writes explicit UTC, uses optimistic
  source/metadata selectors and reports actual modifications. All thirteen new
  tests pass on disposable local MongoDB, including dry-run and global multi-DB
  limits. The canonical quality migration remains a distinct contract.

- **Source pairing passed:** two regressions reproduced URI-only deduplication
  dropping a distinct database on the same deployment and assigning the wrong
  name after a repeated primary. Bot and metadata-tool topology now normalize
  pairs together, preserve fallback names and reject excess names. Sixty-two
  focused configuration/migration/recovery/ownership cases pass.
- **Remote search acceptance passed:** backfilled all 96,908 cloned media
  documents with no truncation. Five queries, five repetitions per strategy,
  returned identical complete ID sets. Indexed median times were 59–137ms versus
  3.35–5.32s legacy; all five EXPLAIN plans used `media_search_terms_v1` and
  completed successfully. These are remote QA medians/maxima, not production p95.
- **Remote ownership acceptance passed:** 100 simultaneous creators produced
  exactly one document; restart lookup, owner-outage fail-closed, owner update and
  deletion passed across all three disposable remote sources. Synthetic data was
  removed; immutable reservations remain by design.
- **Live multi-source passed so far:** manually switching to each secondary,
  indexing distinct harmless private uploads, generating links and normal-user
  delivery succeeded. All eleven optional feature flows were replayed; favorites,
  collections and dashboard now read across the activated topology. `/verify`
  again reported 100/100. This score measures manager alignment, not code coverage.

- **Batch outage UX passed:** two pre-fix handler failures reproduced an
  unhandled backend error. Deep-link batches now edit the progress response to
  a safe retry message and refund all definitely unsent quota; favorites/recent
  lists report temporary unavailability instead of missing content. Focused
  quota, feature and multi-source delivery suites pass.
- **Live dedicated channel passed:** because the supplied shared channel also
  has the DELETE_CHANNEL role, a temporary isolated channel was created for
  automatic indexing. Its distinct document was persisted, found and delivered
  to the normal account. The real Send All callback delivered all three test
  documents across the secondary sources. Temporary chat cleanup is tracked.

- **Distributed sort-memory correction passed locally:** live remote `540p`
  search failed with MongoDB code 292 (32 MB blocking-sort limit). Reproduced
  under a restored 64 KB limit on disposable localhost MongoDB with disk spill
  disabled. Per-source `limit(skip + limit)` now bounds server top-K sorting;
  51 multi-source/ownership/batch cases pass, including exact deep-page results.
  Remote first/next/previous-page replay is in progress.
