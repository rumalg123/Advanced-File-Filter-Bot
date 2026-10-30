# QA evidence and remaining coverage

Latest continuation: [multiple force-subscription channels and limited invites](#feature-round-8--multiple-force-sub-channels-and-limited-invites-2026-10-30),
**1,163 tests passed**, **70.37% lines / 57.32% branches / 67.12% combined**.
Next bounded round: premium grants, removal, expiry and daily quotas.
Configured admin/owner bypasses, public group previews and operator logging are
preserved. Whole-bot 100% remains open. This round is complete; wait for the
operator's next `continue` before starting another feature.

Historical baseline: QA date 2026-10-29, application source `850bc31`.
The operator authorized all supplied MongoDB copies, extra commented sources,
two user sessions and declared QA chats. Original server containers were left
running. No push, merge or production deployment was performed.

## Result

**776 tests passed, zero failed/skipped**, using disposable MongoDB and two
separate Redis instances on the rebuilt wzgram 3.1.5 runtime. The warning audit
identified 22 Redis `setex` deprecation/aiohttp app-key notices; no resource-leak
warning was observed. Compile, undefined-name Ruff, dependency consistency,
production/staging Compose, offline staging identity checks and image-source
hash verification passed. The image runs as a nonroot user.

| Coverage | Lines | Branches | Combined |
|---|---:|---:|---:|
| Automated suite | 54.83% | 40.82% | 51.34% |
| Source-matched automated + live | 67.30% | 52.92% | 63.72% |

The denominator is **17,440 executable statements, 5,784 branches and all 118
tracked application/operator Python files**. Namespace discovery now includes
unimported modules; no uncovered application file was removed to improve the
metric. The earlier 470-test expanded baseline measured 44% combined coverage
across a smaller 16,322-statement source. Whole-bot **100% is not achieved**.
The registry and activation tool individually have **100% line and branch
coverage** (298 statements and 124 branches).

Live coverage is accepted only when a file's SHA256 at process start, process
end and current source all match. Changed-file shards are discarded, rather
than remapped to new line numbers. The [coverage summary](coverage-summary.json)
and [provenance](coverage-provenance.json) record those rules and current gaps.

## Multidatabase acceptance

- **Passed:** complete inventory and activation of 96,908 existing records on
  three independent disposable MongoDB sources, without identity conflicts.
  Later fixture counts differ because live tests add/remove records.
- **Passed:** 100 concurrent remote creators chose one permanent owner and
  produced one physical media record. Restart, uncertain acknowledgment,
  owner/coordinator failure, owner-only update/delete and reingestion passed.
  All aliases share one unique multikey registry index; reservations never
  expire or move. See [ownership evidence](remote-ownership.json).
- **Passed:** actual `/dbswitch` writes on sources 2 and 3, generated links,
  normal-account delivery, dedicated-channel automatic indexing, complete
  distributed search and the real Send All callback. The final replay delivered
  three distinct documents and restored the primary write selection.
- **Passed:** source 3 network partition scoped to the QA Docker network
  namespace. Readiness returned 503 while primary access/liveness stayed
  available. Pagination returned safe retry in **8.047s** and published no
  incomplete page cache. Removing the rules restored readiness and the same
  callback's valid page. Ordinary text search took **49.28s** under existing
  driver retries. See [callback](live-callback-outage.json) and
  [text/readiness](live-secondary-outage.json) evidence.
- **Passed:** activation now rejects one-source writes before permanent bindings
  or index changes. Read-only one-source inventory remains available. Full
  intended membership must be configured before activation.

The [ownership runbook](../../MULTIDB_GLOBAL_IDENTITY.md) documents permanent
bindings, stopped-writer activation, coordinator sizing and offline rollback.
These QA databases now retain their activated registry and optional indexes.
Using them again requires the complete three-source configuration and registry
flag; turning the flag off or omitting a source intentionally fails startup.
Private credentials/configuration remain outside Git.

## Search and pagination acceptance

Optional `FEATURE_INDEXED_MEDIA_SEARCH` retains the legacy final matcher and
uses versioned necessary-word candidates only where safe. Untagged, invalidated
or unknown-version rows retain the legacy path. Edits invalidate token metadata;
bounded optimistic backfill skips changed documents, including nested-array
races. Source defaults remain off.

Complete-result ID equivalence passed on eight local and five remote queries.
Five repetitions per remote query measured median **3.35–5.32s legacy versus
59–137ms indexed**. These are small QA samples, not production percentile/SLO
claims. [Sanitized plans](remote-indexed-search.json) identify query hashes and
indexes without exposing titles or connection details.

Bounded server top-K sorts, the optional stable page index, 64-row merge buffers
and mathematically guaranteed per-source prefix skips fixed real MongoDB sort
memory/callback failures. Remote deep-source offset 36,550 used no blocking
SORT and completed in **0.500s** ([plans](remote-deep-sort-plans.json)). Final
real next/back preserved canonical file order; page **3,657** completed in
**1,154.8ms**. Counts/page reads remain independent rather than a distributed
snapshot. Balanced middle pages can still require substantial residual merging.

## User, admin, feature and cache acceptance

- Both supplied sessions authenticated with wzgram 3.1.5. Existing `pyrogram`
  imports resolve to the same module. Both dependency manifests request `wzgram`
  without a stale version pin. See [image checks](final-preflight.json).
- All eleven roadmap features passed enabled/disabled regressions and real
  command/callback flows: saved searches/alerts, favorites/collections, advanced
  filters, feedback, reports, autocomplete, grouping, requests, recent files,
  recommendations and dashboard. Feature source defaults remain off.
- The final-source UI sweep rendered **62 settings details over eight pages**.
  Invalid integers were rejected, valid edits saved, cancellation cleared the
  captured session, and **13 repeated boolean updates** returned success.
  [UI evidence](live-ui-summary.json) excludes credentials and callback IDs.
- Admin/user permissions, actual ban/unban of only the supplied normal actor,
  subscription/quota paths, channel routing and `/verify` handler alignment
  passed. `/verify`'s 100/100 score describes handler checks, not code coverage.
- Real Redis/local MongoDB contracts cover split operational state, safe
  serialization, generation races, TTLs, saturation, quota day boundaries,
  reservations/refunds, durable job leases/restart and backend failures.
  Harmless owner-shell short/file output passed; unrelated bot work remained
  responsive and owned process/file cleanup passed timeout/cancellation tests.
- Temporary-installation updater backup/restore/CLI tests and bounded metadata
  migration dry-run/apply/concurrent-edit/resource-cleanup tests passed. No
  updater or restart command was executed against the original server services.

## Confirmed fixes committed separately

The continuation fixed failed-pool/topology recovery; callback alert formatting
and acknowledgment; matched no-op CRUD; exact premium expiry; strict settings
parsing; URI/name pairing; complete-or-error batch reads and unsent quota
settlement; unique complete updater backups; bounded optimistic metadata
migration; broad/deep distributed sorts; all-source readiness; exact token
backfill snapshots; and asynchronous owner-shell process/file ownership.

Additional final-source findings are **BUG-053–058** in the
[bug register](../../../BUG_AUDIT.md): persisted settings success despite optional
message deletion failure, captured-session cancellation fencing/awaited cleanup,
60-second exact expiry, unique stable references for empty wzgram references,
canonical/alias conflict classification, unsupported activation rejection and
idempotent settings callback rendering. Each behavioral fix has its own commit
and regression evidence; the final suite includes operator entry-point tests.

The obsolete `POTENTIAL_ISSUES.md` candidate list was removed after its useful
lifecycle findings were fixed and covered. Bug/cache ID registers, historical
reports and operational recovery instructions remain useful and are retained.
Current tracker rows/runbooks distinguish QA passed from merge/rollout status.

## Still open

1. **Whole-bot 100% line/branch coverage.** The committed coverage summary names
   the largest remaining gaps; passing live smoke tests does not prove all error,
   cancellation, platform or alternate-configuration branches.
2. Representative sustained and multi-replica production load, middle-page
   costs, latency tails and agreed SLO/capacity limits. The coordinator must hold
   permanent identity metadata for every source, including deleted files.
3. Cloud/Atlas backup restoration, retention/access review and measured RPO/RTO.
   Local isolated restore tests do not establish cloud recovery readiness.
4. Genuine upstream Telegram FloodWait under real traffic, client-internal retry
   behavior and multi-replica cooldown acceptance. Injected FloodWait tests passed;
   they are not labeled a real Telegram rate-limit incident.
5. Production state migration/cutover, mixed-version exposure checks, optional
   feature/index/registry rollout, remote CI at the final commit and enforced
   branch protections. The operator will review/merge separately.

PH-004 retains the earlier explicit network-isolation decision. Multilingual
search, automatic owner transfer and multi-source keyword bulk deletion remain
outside the implemented contract. No cloud recovery or production gate is
marked passed based only on mocked tests or disposable QA.

## Cleanup

The nine recorded live media fixtures were removed (one was already absent).
Permanent registry reservations remain as designed. The one QA-created channel
was unregistered and deleted; supplied test channels/groups were retained. An
independent namespace check found no remaining network-fault rules, and no
shell-output temporary files remained. Isolated QA containers were stopped and
removed after saving coverage; the two original server containers kept running.
Raw logs, sessions, credentials and database dumps stay outside Git in the
private QA directories. The rebuilt cutover candidate is retained with an archive outside Docker.

## Production-cutover follow-up

This is the QA server; production is elsewhere and currently has one MongoDB.
The operator accepts a fresh Redis reset and plans a second MongoDB later.
The [production runbook](../../PRODUCTION_CUTOVER.md) records targeted reset,
backup requirements, storage headroom and initial two-source activation.

BUG-059 fixed the default state Redis rejecting a separate container despite
passing loopback health probes. The before/after network regression is now in
CI; actual runtime split-cache routing and ACL enforcement passed on separate
containers. BUG-060 fixed write-source statistics ignoring index storage; four
pre-fix failures and five post-fix capacity cases include real MongoDB. Both
fixes are separate commits.

The new image's Python and deployment files match the tested source; all runtime
dependencies match the 776-test runner. Its identity, checks and archive checksum
are in [candidate evidence](cutover-candidate-checks.json). Earlier QA image
availability statements describe their original checkpoint; that image was no
longer available when this follow-up started. The new candidate was rebuilt and
archived independently of Docker. No image was pushed or production deployed.

Current coverage is conservatively source-matched: older live execution of the
changed multi-database module is discarded. Its percentage can therefore decrease
after a fix despite more passing tests. No uncovered file was excluded.

## Supplied production Compose and startup follow-up

The operator supplied the actual two-service production Compose and confirmed
Atlas Free is external. The [exact operator commands](../../PRODUCTION_FROM_EXISTING_COMPOSE.md)
preserve project/data volumes, save the old image/configuration and Atlas dump,
select the hardening branch, reset only the verified Redis volume and perform
health/readiness/smoke checks. These commands were prepared, not run on production.

BUG-061 reproduced two Docker setup failures: attempted package changes with a
successful installer and startup failure when the installer is unavailable.
Docker startup now uses the image dependencies. Both regressions passed, the
full suite passed 776 tests, and the new image passed offline setup plus a default
entrypoint smoke with a stub bot. No Telegram/Atlas activity occurred in that
stub smoke. MongoDB Tools JSON/YAML credentials and isolated dump/restore were
validated on local disposable data using the host UID for private-file access.
The V2 candidate supersedes the earlier candidate and has a separately verified
archive; the earlier artifact is historical. A native production build remains
the default in the exact command guide, avoiding architecture assumptions.

## Update-and-restart correction (BUG-062)

Commit `c4c19b0` restores the intended `/restart` contract: fetch the configured
upstream branch, back up and validate the code, apply it, then restart the bot.
The initial `ffd9d63` change passed 27 focused checks but incorrectly disabled
code updates; its restart-only contract is superseded. The original Git exit-128
failure came from running Git in a source-only image without a valid checkout,
not from using a branch other than main.

The corrected command uses the existing updater's temporary clone, so the image
needs no `.git`. It preserves `.env`, Telegram sessions, logs and data, installs
changed requirements explicitly, saves the fetched revision for startup output,
and cancels the restart on update failure. Overlapping commands cannot start
concurrent updates. Failed application copying attempts to restore the saved
application files. Dependency/environment changes are not reverted by a file
backup; rebuilding the previous image remains the deployment recovery path.

Validation on 2026-10-29:

- **82 focused tests passed** across container restart, secure updater, settings
  callbacks and settings edit lifecycle. Real local Git repositories have
  different main/release commits; tests prove the configured slash-containing
  branch is applied before SIGTERM. Missing branches, invalid Python and failed
  dependency installation cancel restart. Backup recovery, version reporting,
  session/data preservation and concurrent requests pass.
- A child process exercised real wzgram `Client.run()` / idle / stop after a real
  source update. Telegram message objects were test doubles; no live Telegram
  or Atlas connections were made for this correction.
- An isolated Docker probe, with network disabled and `unless-stopped`, applied
  the requested branch, completed client stop, automatically restarted exactly
  once and executed the new `bot.py`. `.env` and session state were preserved.
  Its temporary container was removed; existing services were untouched.
- Changed Python syntax, undefined-name lint and `git diff --check` passed.

The full 776-test/coverage snapshot above remains associated with `850bc31`;
whole-bot coverage was not rerun or claimed as 100% for this focused correction.
Archived candidate images predate this correction: build the current branch.
No production server or production container was accessed from QA.

## Operational flags in /bsetting — completed

Commit `f7bc25e` adds all five previously environment-only rollout flags to
primary-admin settings: canonical metadata, quota delivery ledger, durable
channel indexing, durable saved-search alerts and global media ownership.
Saved values are synchronized into the feature/processing/database consumers
before routing, repositories and workers are initialized. Existing MongoDB
choices override environment initialization; changes take effect after restart.

The Media Owners control is locked unless at least two distinct valid MongoDB
URI/database pairs are configured. URI/name validation defers connections and
SRV DNS; credential/option variants do not count as extra sources. Its recommended
default is false before matching activation is ready and true afterward. Owners
can stage true before stopped-writer activation, but startup still requires all
bindings, canonical/alias indexes and matching ready topology. Bound ownership
cannot be disabled through updates, reset, imports or forged callbacks. Invalid
configuration and activation-read failures lock editing without displaying URIs.

**Validation passed:** full suite **831 passed, 0 failed/errors/skipped** with
local disposable MongoDB and two Redis instances, including 34 new operational
settings cases. A real-Mongo integration saved all five flags, stopped the
initial manager, activated two disposable sources, and verified a new startup
loaded the saved values before attaching owner routing. UI checks cover the
single-source lock, forged callbacks and Telegram callback size limits. Full
Python compilation, undefined-name lint and whitespace checks passed. The 22
existing Redis deprecation/aiohttp warnings remain.

The temporary test services shared a private network namespace with no host
ports and were removed afterward. No production server, Telegram account or
remote Atlas database was accessed for this change. The earlier coverage
percentages remain the historical snapshot; this full regression run did not
remeasure whole-bot coverage. Exposing the controls does not complete outstanding
canonical-metadata, quota reconciliation or durable-queue production drills.

## Durable indexing log-channel summaries — BUG-063 fixed

Commit `ca6eb4e` restores the Auto-Index Batch Summary for durable automatic
channel indexing. A newly inserted file sends one summary after its job is
acknowledged; memory indexing retains its existing per-batch summary. Both paths
share the sender. Disabled log channels, duplicate replays and lost leases do
not announce a new indexed file. A Telegram notification error emits a warning
without requeueing saved media or repeating saved-search work. Delivery remains
best-effort across process cancellation/crash; old completed jobs are not replayed.

Validation on 2026-10-30: six failures reproduced before the fix; all **13 new
notification cases pass**, including real-Mongo acknowledgements with both
successful and failed Telegram test-double sends. All **33 related indexing,
notification and saved-search tests pass**. Changed-source compilation,
undefined-name lint and whitespace checks passed.

Full suite: **842 passed, 2 failed, 0 skipped**, with the 22 existing warnings.
The two failures are in recent operator-script changes already present at
`05dd4de`: the backfill bounds test still rejects a limit now permitted by the
script, and the ownership CLI prints raw exception text that its privacy test
rejects. The new ten-million ownership CLI default also disagrees with the
library's existing one-million inventory/activation bound. These are separate
follow-ups; this notification fix preserves those commits.

Tests used disposable MongoDB and two Redis instances in a private Docker
network namespace without published ports. All owned containers and the network
were removed. No production connection or live Telegram notification was made.
After deployment, verify with a newly indexed file and the configured log
channel. This run did not remeasure whole-bot coverage.

## Maintenance limits and diagnostics — BUG-064 / BUG-065 fixed

The two operator-script follow-ups from the prior run are resolved separately:

- `147917e`: one shared **10,000,000-document** upper bound for ownership
  inventory/activation and search-token backfill. Ownership CLI/library defaults
  now agree at ten million. Backfill retains its one-million default and accepts
  up to ten million explicitly. Integer/type/bounds checks and the formerly
  stale regression are aligned with the operator's increased limits.
- `ca3ae8a`: ownership and backfill errors retain exception type and numeric
  MongoDB code without rendering arbitrary exception messages/details that may
  contain credentials, hosts or document values.

Final validation on 2026-10-30: **878 passed, zero failures/errors/skips**, with
22 existing warnings, against disposable local MongoDB and separate cache/state
Redis services. Tests include real ownership inventory and CLI activation using
its new default, permitted bounds above 500,000/one million and at ten million,
rejection before connection/binding for invalid values, and both CLI error
paths for connection/authentication/duplicate-key failures. Full compilation,
undefined-name lint and whitespace validation pass. Large-limit acceptance uses
small fixtures rather than loading ten million records; no large-catalogue
throughput or memory claim is made. Owned test containers/network were removed.
No production server or remote database was accessed.

The saved-search queue storage question was reviewed without changing retention
or admission behavior. The [queue runbook](../../DURABLE_SAVED_SEARCH_ALERTS.md)
now distinguishes user subscriptions, per-file durable jobs (completed TTL
30 days), and recipient deduplication claims (TTL 180 days), and records the
zero-subscriber job overhead. Enabling alerts/backfilling tokens does not enqueue
all pre-existing media. Source defaults and rollout acceptance gates remain as
documented; this run does not remeasure whole-bot coverage.

## Bounded QA round 1 — inline and group search (2026-10-30)

**Passed and complete for this round.** Application source `7b973bd` includes
two separately committed fixes and 28 new regressions:

- **BUG-066, `8c5ba8b`:** inline access-check failures now receive a safe answer.
  An eight-second deadline cancels slow access/search work; expired replies stay
  contained in the handler. Twenty inline cases cover gates, exemptions,
  personal results, offsets, failures, expiry and cancellation.
- **BUG-067, `7b973bd`:** shared initial/pagination captions escape query HTML,
  preserving literal text in private and group results. Eight group/caption
  cases cover scope, ownership, unavailable/empty results, filter fallback,
  callback size limits, session ownership and result-only auto-deletion.

Full regression: **906 passed, zero failures/errors/skips**, with the same
22 existing Redis deprecation/aiohttp warnings. Compilation and the focused
undefined-name Ruff gate pass. Tests used disposable local MongoDB and two
Redis services, without host-published ports.

**Live Telegram acceptance passed** with both supplied QA accounts after the
operator enabled inline mode. Twelve tiny documents were indexed through
`/link`. Normal inline search returned ten results, then two on the final page
without a further offset; result IDs did not overlap. Admin search, empty
results and selecting a cached document into the supplied QA group passed.
Group results showed twelve files over four pages. A different user's page
click was denied, owner forward/back clicks preserved file IDs, callbacks fit
Telegram's limit, and a group file button opened successful private delivery.
A literal `<unknown>` query displayed safely; a group no-result query stayed
quiet. See the [sanitized evidence](round1-inline-group.json).

Live configuration used premium mode off, custom filters off, indexed media
search and duplicate grouping on, three results per group page and no
auto-delete timer. Document selection was tested live; other inline media
types remain unverified in this round. Ban, subscription, premium, rate-limit,
backend-failure and deadline cases used automated fixtures. Genuine Telegram
FloodWait occurred during fixture setup and wzgram retried; this does not
complete the sustained-load or multi-replica cooldown gates.

Coverage was remeasured across **17,607 statements, 5,846 branches and all 121
tracked application/operator Python files**, including unimported modules:

| Coverage | Lines | Branches | Combined |
|---|---:|---:|---:|
| Automated suite | 56.98% | 43.47% | 53.61% |
| Source-matched automated + live | 68.61% | 54.55% | 65.11% |

Both new coverage shards match the current source at process start/end. Earlier
shards contribute only for files with identical start/end/current SHA256;
changed files are discarded. The evidence records provenance and the complete
denominator. The 67.30% line baseline above remains historical; **100% whole-bot
coverage is not achieved**.

All recorded test messages and one orphan inline fixture from an earlier
harness failure were deleted. Disposable databases, Redis, containers and
networks were removed; both original server services remain running. Fixture
filename/API-return assumptions were corrected in the private harness before
acceptance. No production server or remote Atlas database was accessed.
No new product features were added. Remaining feature/media-type checks and
operational gates stay open for later bounded rounds after `continue`.

## Bounded QA round 2 — Send All and batch links (2026-10-30)

**Passed and complete for this round.** Application source `89bc359` adds no
features and preserves configured limits. Four fixes were committed separately:

- **BUG-068, `9ab903b`:** private Send All independently verifies cached result
  ownership before reserving quota or sending files.
- **BUG-069, `e45bd2a`:** every Send All status escapes literal query markup.
- **BUG-070, `c4ce99c`:** Send All uses shared exception-safe delivery progress.
  Missing media and cancellation before/during lookup or after a confirmed send
  settle as definitely unsent where appropriate; an interrupted in-flight send
  stays uncertain. Optional recent-history failure no longer counts a delivered
  file as failed or changes its quota outcome.
- **BUG-071, `89bc359`:** ordinary batch creation and encoded DSTORE requests
  validate positive, ordered inclusive bounds against the existing configured
  maximum before Telegram/access/quota work. Zero chats and unsupported modes
  are rejected. Legacy single-item and three-field batches remain supported.
  Existing encoded links above the configured maximum are now rejected too;
  no configured limit or maintenance scan limit was reduced.

The initial 21 focused cases reproduced **16 failures and five passes** before
fixes; all 21 pass afterward (eight Send All, thirteen batch range cases).
Full regression: **927 passed, zero failures/errors/skips**, with 22 existing
warnings. Compilation, focused undefined-name Ruff and whitespace checks pass.

**Thirteen live Telegram checks passed** using both QA accounts, the supplied
QA group and a supplied test channel. Private Send All delivered three distinct
files and displayed a literal `<unknown> &` query in its status. Group Send All
redirected to successful three-file private delivery. Cross-user group clicks,
shared owner-bound deep links and expired search sessions were denied.
Telegram rejected altered callback data with `DATA_INVALID` before dispatch;
the new independent cached-owner guard is verified by its handler regression,
without claiming a demonstrated external exploit.

Ordinary and protected batch links each delivered two files. A premium batch
rejected a non-premium user, then delivered two protected files after an admin
premium grant in the disposable database. Expiring its BSON date and
invalidating its exact cache entry caused immediate application rejection,
without waiting for the TTL sweep. A reversed encoded range was also rejected.
The user document recorded exactly **ten charged non-premium file deliveries**;
retained ledger entries were settled, with no reserved/uncertain entry. The
premium transfer did not require a non-premium reservation. See the
[sanitized evidence and coverage provenance](round2-sendall-batch.json).

Live configuration enabled premium mode, quota delivery ledger, recent files
and indexed media search, with a twenty-file allowance and no auto-deletion.
Local MongoDB plus separate cache/state Redis instances had no published host
ports. Cancellation, missing-media, uncertain sends and recent-history failures
used injected automated cases; real transport-failure recovery and production
load gates remain open.

Coverage includes **17,593 statements, 5,834 branches and all 121 tracked
application/operator Python files**, including unimported modules:

| Coverage | Lines | Branches | Combined |
|---|---:|---:|---:|
| Automated suite | 57.52% | 44.05% | 54.17% |
| Source-matched automated + live | 69.82% | 56.00% | 66.38% |

Both new shards match source hashes at start/end/current; prior evidence is
accepted only for identical files. Whole-bot **100% remains open**. All recorded
fixture messages, source-channel uploads, owned containers, volumes and networks
were removed, including cleanup after private harness corrections. The two
original server services remain running. No production server or remote Atlas
was accessed. This round stops here; further feature QA waits for `continue`.

## Bounded QA round 3 — favorites and recent files (2026-10-30)

**Passed and complete for this round**, including the requested `/bsetting`
label correction. Application source `124fcd6` includes four separate commits:

- **BUG-072, `56241ba`:** indexed media search displays **Indexed Search** in
  both the settings menu and detail view. The stored key, value and behavior
  are unchanged; both UI surfaces were checked live.
- **BUG-073, `4525d59`:** `/unfavorite` can remove stale membership by unique ID
  after media is deleted, for typed commands and replies. Adding unavailable
  media still fails. Existing aliases resolve to canonical IDs when available.
- **BUG-074, `9c63812`:** favorite Remove controls use stable owner-scoped
  collection tokens, keeping long/multibyte names within callback limits and
  preserving actions from menus opened before a rename. Older name-based
  callbacks remain valid. Reading a legacy collection lazily fills its existing
  token field, so those controls also work for old records.
- **BUG-075, `124fcd6`:** recent-history trimming deletes only owner-scoped rows
  whose timestamp still matches the snapshot. A refreshed row survives a
  concurrent prune. Trimming is best-effort during racing writes; the real-Mongo
  test confirms that a subsequent write restores the fifty-entry bound without
  touching another user.

The nine new regressions initially reported **seven failures and two passes**;
all nine now pass. The complete suite reports **936 passed, zero
failures/errors/skips**, with the same 22 existing warnings. Real MongoDB cases
verify the prune/refresh interleaving, repeated-download deduplication,
owner-scoped history removal and legacy token persistence. Compilation, focused
undefined-name Ruff, Markdown/local-link and whitespace checks pass.

**Eleven live Telegram checks passed** using both QA accounts and three tiny
indexed documents. Duplicate Favorite clicks produced one membership; opening
that favorite delivered the same file and kept one recent entry. A collection
with a thirty-five-character Sinhala name retained its Remove button. Removing
from its old menu after renaming affected the renamed collection while leaving
the other account's same-named collection intact. Named collection clear/delete
and deleted-catalogue membership cleanup passed; adding deleted media was denied.

Repeated downloads moved the file to the front of `/recent` without duplicates.
Individual removal, clearing all history, the empty menu and preserving the
other account's history passed. The settings menu/detail both displayed Indexed
Search. See the [sanitized acceptance and coverage evidence](round3-favorites-recent.json).
A private-harness assertion was corrected to compare immutable file IDs because
button filenames use the application's existing normalization.

Live configuration enabled favorites, recent files, indexed search, premium
mode and the quota ledger, with a twenty-file allowance and no auto-deletion.
MongoDB and separate cache/state Redis instances were disposable local services
without published host ports. Large-collection navigation, sustained concurrency
and production transport-failure recovery remain outside this bounded run.

Coverage includes **17,605 statements, 5,840 branches and all 121 tracked
application/operator Python files**, including unimported modules:

| Coverage | Lines | Branches | Combined |
|---|---:|---:|---:|
| Automated suite | 57.84% | 44.37% | 54.48% |
| Source-matched automated + live | 69.78% | 56.35% | 66.43% |

Both new shards match start/end/current source hashes. Earlier shards contribute
only unchanged files; changed-file evidence is discarded. These are current
source measurements, not an extension of old line numbers. **100% whole-bot
coverage remains open.** All recorded QA messages and owned containers, volumes
and networks were removed, including cleanup after the harness correction. The
two original server services remain running; no production server or remote
Atlas database was accessed. No product features were added. Stop here until
the operator requests `continue`.

## Bounded QA round 4 — saved-search alerts and file reports (2026-10-30)

**Passed and complete for this round.** Application source `468e18d` includes
three fixes, each committed separately:

- **BUG-076, `6b1cbb8`:** the management menu fetches all 25 permitted saved
  searches, exposing the oldest Run/Pause/Delete controls. Owner scoping,
  explicit smaller limits and Telegram callback bounds are preserved.
- **BUG-077, `6521b28`:** durable alert fan-out releases a fenced claim and
  skips recipients identified by Telegram as blocked, deactivated or invalid.
  This neither records a false successful send nor disables their subscription.
  Other subscribers still receive alerts and the job can complete. Release
  lease loss prevents checkpointing; transient send failures still retry.
- **BUG-078, `468e18d`:** report resolution uses its stored filename directly.
  An optional legacy filename lookup failure falls back safely, allowing
  notifications, notification-result recording and the admin response to finish
  after the resolution has already committed.

The nine new regressions initially reported **eight failures and one pass**;
all nine now pass. Full suite: **945 passed, zero failures/errors/skips**, with
22 existing warnings. Real-Mongo regressions cover all 25 menu entries and a
queue that completes for a reachable subscriber after skipping a blocked one,
without a sent claim for the blocked recipient. Invalid/deactivated recipients,
lost release leases, transient send failure and optional metadata outages use
injected failures. Compilation, focused Ruff, Markdown/local-link and whitespace
checks pass.

**Seventeen live Telegram checks passed** with both QA accounts, five distinct
indexed documents and the declared QA log channel. Saved-search creation and
resaving deduplicated correctly and displayed literal query markup. A new match
notified both subscribers once; reindexing a copied duplicate created neither
an extra job nor an extra notification. Pause suppressed new-file alerts while
manual Run still worked; Resume restored alerts. Deleting one account's search
left the other account's same query active and stopped future alerts for the
owner who deleted it.

Reporting the same file/reason twice created one issue; the second account
subscribed to that issue. Submission and resolution messages reached the log
channel. The admin list showed the file and both reporters; resolution notified
both and persisted results. Repeated resolution did not resend; a new report
reopened the same issue with resolution history retained.

The normal QA account temporarily blocked the QA bot. A matching new file still
completed its durable job and notified the reachable admin; there was no false
sent claim for the blocked account. Resolving a reopened report notified the
reachable reporter and recorded the blocked reporter as unreachable. Bot access
was then restored and `/start` verified. All five alert jobs finished with no
pending/dead work. See the [sanitized evidence](round4-alerts-reports.json).

Live configuration enabled alerts, durable alert workers, file reports, indexed
search, premium mode and the quota ledger, with a twenty-file allowance and no
auto-deletion. MongoDB and separate cache/state Redis instances were disposable
local services without published ports. Legacy alert behavior remained covered
by the automated suite. Large fan-out load, long FloodWait/lease interactions,
crash reconciliation and durable report-notification recovery remain open;
report notifications are best-effort after resolution.

Coverage includes **17,617 statements, 5,844 branches and all 121 tracked
application/operator Python files**, including unimported modules:

| Coverage | Lines | Branches | Combined |
|---|---:|---:|---:|
| Automated suite | 57.88% | 44.40% | 54.52% |
| Source-matched automated + live | 69.84% | 56.49% | 66.51% |

Both new shards match source hashes at start/end/current; older evidence is
accepted only for unchanged files. **Whole-bot 100% remains open.** All recorded
QA messages, including startup/report log posts, and owned containers, volumes
and networks were removed. The normal account was unblocked; both original
server services remain running. No production server or remote Atlas database
was accessed. No product features or schema migrations were added. Stop here
until the next `continue`.


## Bounded QA round 5 — ban and unban (2026-10-30)

**Passed and complete for this round.** Final application source `d734c04`.
The operator explicitly required configured bot admins and owners to retain
their bypass. That policy supersedes the earlier PH-001 administrator-denial
policy; ordinary premium users and premium-disabled mode remain subject to bans.
All **407 existing logger lines across 26 operator-edited files** are preserved.

Eleven fixes are committed individually:

| Issue | Commit | Result |
|---|---|---|
| BUG-079 | `06a2d79` | Preserve added diagnostics and initialize two missing module loggers. |
| BUG-080 | `a33150d` | Read ordinary-user moderation state from MongoDB, bypass stale Redis, and deny unavailable authorization safely; retain admin/owner exemptions. |
| BUG-081 | `493d683` | Guard user menus, subscription retries, public file-store, filters/connections and request shortcuts. |
| BUG-082 | `9fd677c` | Recheck saved-alert and broadcast recipients before content delivery; keep privileged exemptions. |
| BUG-083 | `87f5149` | Atomically fence ordinary-user quota reservation against a concurrent ban. |
| BUG-084 | `eaa6697` | Reject delayed abuse decisions after unban or manual ban; require the current warning threshold. |
| BUG-085 | `828793c` | Escape names/reasons in formatted notices and bound callback denials. |
| BUG-086 | `4d6b735` | Stop remaining Send All/search/JSON/channel-batch deliveries after a ban and settle confirmed/unsent quota. |
| BUG-087 | `45ed05c` | Disable Telegram result caching for ordinary-user inline queries; retain privileged caching. |
| BUG-088 | `c2be86d` | Gate pagination before cached-session or backend work. |
| BUG-089 | `d734c04` | Normalize BSON and legacy warning dates before UTC calculations; prevent request escalation/stats crashes. |

**Automated verification:** **1,016 passed, zero failures/errors/skips**, with
22 existing warnings. This is 71 more cases than round 4. The route matrix
covers 27 user entry points. Real-Mongo tests exercise stale profiles, moderation
mutations, quota fences, delayed abuse decisions, and warning escalation with
BSON, naive ISO and offset ISO timestamps, including 30-day expiry. The six
warning-date cases all failed before BUG-089 and pass after it. Other injected
checks cover unavailable authorization, safe response text, lost/background
access, explicit admin/owner bypasses and interruption of five bulk paths.
Compilation, Ruff F821/F822/F823, local Markdown links and whitespace checks pass.

**19 live checks passed** using both supplied QA accounts, four distinct tiny
indexed documents and the declared QA group/log channel. They cover invalid and
unknown moderation targets; unauthorized ban attempts; active private/group and
inline search; ordinary premium users denied in free mode; old file, Send All,
pagination, favorite and group buttons; public file-store routes; literal ban
reasons; repeat ban/unban; and stale active/banned Redis profiles.

A configured admin was deliberately marked banned and still used private/inline
search, file delivery, saved alerts and broadcast management. The banned normal
account received neither the new-file content alert nor the broadcast; no saved
alert sent claim was created. Unban reset request-abuse counters while preserving
premium, downloads and lifetime request totals.

The QA bot was then recreated with **both owned Redis databases empty and the
same disposable MongoDB**; the normal user's ban still applied. A two-file Send
All was interrupted after the first confirmed file: the second file was not
sent, one quota slot was refunded, and the ledger settled at confirmed=1,
refund=1. Unban restored delivery without resetting consumed quota. Three group
requests using temporary allowance=1 and warning limit=2 produced a real
automatic ban; further requests were denied. Unban restored the request allowance.
The warning-date crash was found here, reproduced separately, fixed, and both
live phases and the full suite rerun against the final source. See the
[sanitized evidence](round5-ban-unban.json).

The private harness was corrected to enable the selected public file-store
route, wait for asynchronous quota settlement, and reseed consumed quota after
the existing premium-removal operation reset it. Attempt-owned messages and
infrastructure were cleaned after each attempt. These harness corrections did
not change product behavior. Production limits and `.env` were not modified.

The run also exercised Telegram FloodWait retries. Opening `/bsetting` logged a
handled `MESSAGE_ID_INVALID` when it tried to edit the incoming command; its
fallback reply displayed the menu, the setting persisted and restart applied it.
That existing menu fallback is recorded for the next settings QA round; this
round does not claim a clean log or complete settings-menu coverage. The next
round resolved that routine fallback with BUG-090; its evidence follows below.

Coverage includes **17,776 statements, 5,880 branches and all 121 tracked
application/operator Python files**, including unimported modules:

| Coverage | Lines | Branches | Combined |
|---|---:|---:|---:|
| Automated suite | 59.02% | 45.65% | 55.70% |
| Source-matched automated + live | 69.37% | 56.00% | 66.05% |

All three new shards match start/end/current source hashes. Historical evidence
contributes only for unchanged files; the operator's diagnostic additions and
other source edits invalidate old coverage for affected files. **Whole-bot 100%
remains open.** Fresh access checks cannot revoke media already delivered,
previously issued inline results or Telegram calls already in flight.
Representative production load, multi-replica moderation timing and large
subscriber fan-out remain outside this bounded round. Authoritative moderation
checks add MongoDB reads; production latency and capacity still need observation.

All recorded QA messages and owned containers, volumes and networks were removed.
The two original server services remain running. No production server or remote
Atlas database was accessed. No product features or schema migrations were added.
Stop here until the next `continue`.


## Bounded QA round 6 — bot settings (2026-10-30)

**Passed and complete for this round.** Final application source `3c676f2`.
This round covers `/bsetting`, primary-owner permissions, settings controls and
edit-dialog lifecycle. Configured admin/owner ban/quota bypasses and all prior
operator-added diagnostic lines remain preserved. Four fixes are committed
separately:

| Issue | Commit | Result |
|---|---|---|
| BUG-090 | `9624114` | Reply directly to `/bsetting`; edit existing bot menus on navigation, ignore unchanged-message responses, and retain a fallback for uneditable bot messages. |
| BUG-091 | `04c1d3a` | Reject protected edits/resets, invalid boolean controls and malformed pages; validate removed/locked settings before capturing the next owner message. |
| BUG-092 | `a8330a0` | Display saved/default values and policy notes literally; preserve stored captions/templates unchanged. |
| BUG-093 | `3c676f2` | Closing an older menu cannot cancel another dialog; failed or cancelled prompts clean up only their own session token. |

The initial 31 focused cases reported **22 failures and nine passes** before
these fixes. Three additional session-boundary cases were then added. The full
suite now passes **1,050 tests, zero failures/errors/skips**, with 22 existing
warnings and **34 new cases**. They cover incoming-command versus bot-menu
behavior, unchanged and uneditable menus, protected settings across mutation
controls, malformed/removed controls, primary/secondary/ordinary-user permissions,
literal string/list rendering, message/chat ownership and session token races.
Injected failed/cancelled prompt delivery leaves no hidden edit session.
Compilation, Ruff F821/F822/F823, local Markdown links/anchors and whitespace
checks pass.

**18 live Telegram checks passed** using both supplied accounts and declared QA
group/log destinations. The primary owner opened private and group menus; normal
users could neither open settings nor operate the owner's group controls. Normal
callback answers and repeat No-op navigation created no duplicate menu. Protected
connection settings had no mutation controls; the single-source global-owner
registry toggle remained locked. A boolean value persisted with a restart
reminder. Integer zero failed validation without a MongoDB write; valid input
saved as an integer and its source message was deleted. `/cancel` discarded a
dialog without writing. Closing an older menu left the newer edit usable.

A caption containing literal markup, ampersands, quotes and an existing filename
placeholder was stored unchanged, displayed literally and reopened for editing.
Both special auto-delete/start template prompts rendered. The owner saved a
second admin ID through the list editor; the resulting list contained integers.
An unfinished edit was then left open while the bot was recreated with **both
owned Redis databases empty and the same disposable MongoDB**. The saved integer,
boolean, caption and admin list loaded into the new runtime. The unfinished edit
did not overwrite the saved value. The second account was now a configured
secondary admin and still could not open or operate primary-owner settings. The
primary owner retained access and reset a saved value to its default. See the
[sanitized evidence](round6-bsettings.json).

Telegram rejected one early harness request for a page callback absent from its
issued keyboard before the bot could dispatch it. The harness was corrected to
click existing controls, and all owned posts/resources from that attempt were
cleaned. The successful run logged the expected rejected-integer validation
exception, and **no routine settings-menu edit failure**. Forged protected
callbacks, malformed controls, unchanged-menu server responses, prompt failures
and token races use injected automated checks. Live edits used private chat;
full 60-second expiry, every combination of all 67 settings, cross-chat owner
edits, multi-process timing and representative production load remain open.

Coverage includes **17,813 statements, 5,892 branches and all 121 tracked
application/operator Python files**, including unimported modules:

| Coverage | Lines | Branches | Combined |
|---|---:|---:|---:|
| Automated suite | 59.33% | 46.06% | 56.03% |
| Source-matched automated + live | 69.53% | 56.40% | 66.26% |

All three new shards match start/end/current source hashes. Historical shards
contribute only unchanged-file evidence; no old arcs are remapped to edited
source. **Whole-bot 100% remains open.** All recorded QA messages and owned
containers, volumes and networks were removed. The two original server services
remain running. No production server, remote Atlas database, deployment `.env`
or production limit was changed. No new product features or schema migrations
were added. Stop here until the next `continue`.


## Bounded QA round 7 — force subscription (2026-10-30)

**Passed and complete for this round.** Final source `815ea27`. Six issues
were fixed with individual commits and pagination follow-ups. Configured
admin/owner and authorized-user subscription exemptions remain intact. Authorized
ordinary users still face ban checks; a privileged account cannot consume
another user's retry. Public group previews and their pagination remain open;
private search/pages, inline search and file retrieval enforce membership.
All 407 prior operator logger lines are preserved.

| Issue | Commit | Result |
|---|---|---|
| BUG-094 | `e24147a` | Required chats must prove membership; unknown/error states deny access. Restricted members use `is_member`. |
| BUG-095 | `a638e10` | Validate retry namespace/owner/payload; failed checks and foreign clicks preserve the saved action. |
| BUG-096 | `7c78213` | Replay callbacks with their real type and original actor/message so private-chat and subscription checks work. |
| BUG-097 | `026c177` | Omit unavailable join URLs instead of creating invalid `Chat ID: ...` URL buttons; keep retry usable. |
| BUG-098 | `9abca15`, `dddbbb9`, `fd04956` | Guard private pagination, preserve public group pages, route all pagination actions, and store oversized retries under short owned keys. Unavailable action storage falls back to a general check. |
| BUG-099 | `a1dfc1e` | `/start subscribe` from inline mode leads to the welcome screen after joining, rather than file decoding. |

**Automated:** **1,108 passed, zero failures/errors/skips**, with 22 existing
warnings and 58 new cases. The initial 45 focused cases showed 21 failures and
24 passes; eight supplementary page/inline cases all failed before their fixes.
Five later cases expanded pagination action and public-preview boundaries.
The matrix covers channel/group member states, unverifiable chats, malformed or
expired state, foreign owners, repeated pre-join retries, replay types, missing
join URLs, oversized controls and unavailable operational-state writes. Four
older pagination regressions now explicitly model an active actor, real callback
shape and configured subscription state. The variant-page and protected-state
checks assert that search/rendering actually ran, removing their earlier ability
to pass at an unrelated authorization denial. A separate shell test exposed a
partial PID-file read; `815ea27` publishes its fixture PID atomically. A new group
fixture was also corrected to use a valid cached query reference (`23e2037`).
The complete suite was rerun after those test corrections. Compilation, Ruff
F821/F822/F823, local Markdown links/anchors and whitespace checks pass.

**20 live Telegram checks passed** with both accounts, two tiny indexed documents,
one declared QA channel and one declared QA supergroup. Both memberships were
initially MEMBER, and the QA bot was an administrator in both. Baseline private,
group and inline searches worked. A private harness sentinel made an attempted
membership lookup for the configured admin fail; admin search/delivery still
worked because the bypass avoided that lookup. Owner chat privileges were not
removed.

Leaving the required channel blocked old private file, Send All and page
buttons, fresh private search and inline results. Public group search and page
previews remained available. Two pre-join clicks preserved the deep-link retry
session. Clicking the normal user's group retry from the admin account returned
an ownership denial and left its state intact. Rejoining the channel resumed
file delivery, Send All, the original page action, Help and both private/group
deep links. Successful deep-link replay consumed its session. The inline Join
switch and its retry opened the welcome screen; fresh inline results returned.

Leaving only the required group still denied private/inline access despite
valid channel membership. Rejoining restored delivery. A temporary group
restriction left the normal user as RESTRICTED with `is_member=true`; private
and inline search remained available. The individual restriction was then
fully lifted. Deleting one owned retry key simulated expiry; the callback showed
a safe expiry response, and reissuing the original file link after joining
recovered delivery. See the [sanitized evidence](round7-subscription.json).

The first harness expectation was corrected when live behavior confirmed the
intentional public group preview policy. A later cleanup check showed that
copying group defaults did not remove an individual restriction; the harness
was corrected to lift all individual restrictions, and an independent read-back
confirmed MEMBER before the final replay. The final run verifies both original
memberships and no individual restriction. Two real, expiring bot invite links
were reused within the private fixture and revoked at shutdown; two admin
restore links were also revoked. Attempt-owned chat messages, membership service
messages and infrastructure were cleaned. The final bot log contains an expected
handled FloodWait and no error/traceback. No production invite-cache or load
behavior is claimed from that fixture.

Coverage includes **17,851 statements, 5,914 branches and all 121 tracked
application/operator Python files**, including unimported modules:

| Coverage | Lines | Branches | Combined |
|---|---:|---:|---:|
| Automated suite | 60.58% | 47.65% | 57.37% |
| Source-matched automated + live | 70.24% | 57.14% | 66.98% |

Both new shards match start/end/current source hashes; historical evidence is
accepted only for unchanged files. **Whole-bot 100% remains open.** Live expiry
used deletion of one owned key rather than waiting for wall-clock TTL. Chat
outages, malformed state and unavailable storage use injected failures. Premium
mode, join-request-only chats, every legacy deep-link variant, concurrent valid
callback exactly-once behavior, crash-after-consumption recovery, long FloodWait
interactions and representative production load remain outside this bounded
live round. No durable replay/idempotency feature was introduced.

All QA memberships/permissions are restored, temporary invite links revoked,
recorded messages deleted and owned containers, volumes and networks removed.
The two original server services remain running. No production server, remote
Atlas database, deployment `.env` or production limits were changed. No new
product features or MongoDB schema/index migrations were added. Stop here until
the next `continue`.

## Feature round 8 — multiple force-sub channels and limited invites (2026-10-30)

**Implemented and QA passed for this bounded round.** The operator explicitly
requested this extension before premium QA, superseding the earlier pause on
new features for this scope. FEAT-012 is `b2dea82`; the separately committed
live-discovered BUG-100 fix is `b2fcb38`. No production server or remote Atlas
database was accessed. All database testing used disposable local MongoDB and
two separate Redis instances; Telegram used the provided QA accounts/chats.

`AUTH_CHANNEL` now accepts multiple comma-separated channel IDs or usernames,
with legacy single-value reads preserved. Groups accept IDs/usernames too.
`/bsetting` exposes **Force Sub Channels**, **Force Sub Groups**, **Invite
Expiry (min)** and **Invite Member Limit**. The latter two default to **15
minutes** and **one member**, with valid ranges 1–525600 and 1–99999 respectively.
There are 69 managed settings. Before saving an interactive nonempty target
edit, every chat must resolve to the correct type and the bot must be an
administrator with Invite Users permission. The saved list contains canonical
IDs. Rejection leaves the prior MongoDB value intact and sends no restart
notice; validation creates no probe invites. Environment bootstrap precedes
Telegram connection, so initial environment targets use startup diagnostics.

The initial ordinary-user `/start` now presents the subscription gate before
welcome. Join prompts contain only missing memberships and generate expiring,
member-limited links, including for public chats. A failed Try Again refreshes
links and preserves the owned action. Admin/owner and authorized-user
subscription exemptions remain intact. Saved changes apply after restart;
existing issued links keep their original expiry. No schema/index migration or
bulk data rewrite is required. The example environment file has one declaration
per force-subscription key.

**BUG-100:** a valid large Telegram ID round-trips through MongoDB as BSON
`Int64`. The original exact built-in-integer check rejected those saved IDs,
breaking settings reload/menu/startup. The parser now accepts integer subclasses,
converts them to plain integers and continues rejecting booleans. Four focused
cases failed before the fix (27 passed); all 31 passed afterward, including
real MongoDB channel/group writes, cache clearing and reloads. The fix did not
change production limits or existing logging policy. Of the operator's 407
prior diagnostic lines, 405 remain exact and two now identify the actual
channel in the multiple-channel loop; none were removed.

**Automated:** **1,163 passed, zero failures/errors/skips**, including **55 new
cases**, with 22 existing warnings. Parser and compatibility cases cover scalar,
list, zero/empty, duplicate, username, BSON and malformed inputs. Permission
cases cover missing access, wrong chat type, non-admin roles, missing Invite
Users, all-target validation before storage, aliases resolving to the same ID,
clearing requirements, missing validation clients and actionable UI rejection.
Invite cases cover defaults, changed limits, missing memberships, public-chat
limited URLs, API failures and retry refresh/action preservation. Full Python
compilation, Ruff F821/F822/F823, dependency consistency, Markdown links/anchors,
JSON/privacy checks and whitespace checks pass.
The final logs include expected exception diagnostics for inaccessible chats,
missing permissions and the deliberately invalid expiry; these are handled
rejections with user feedback, rather than an unhandled runtime failure.

**18 live checks passed across three bot phases.** Phase one read a legacy
scalar setting, rejected an inaccessible channel, then rejected an administrator
without Invite Users before saving. Granting the exact missing right allowed
two channels and one group to be stored through `/bsetting`, without creating
validation invites. The bot was recreated with owned Redis empty and the same
MongoDB. A first-time normal-user `/start` produced a real 15-minute/one-member
link only for the missing channel; the already joined channel/group had no
extra join buttons. Pre-join retry refreshed the link, and joining opened
welcome. Leaving a channel and group together produced one working limited
link per missing target; joining both recovered access.

Expiry zero was rejected without changing saved defaults. Expiry one minute
and member limit two were then saved through `/bsetting`. A second empty-Redis
restart retained those values. Telegram returned both requested values on new
links. After waiting until the actual expiry plus two seconds, a real join
failed with `InviteHashExpired`; Try Again generated a fresh link, and joining
restored welcome. The configured primary admin/owner retained bypass and
settings access throughout. See the [sanitized evidence](round8-multisub.json).

The earlier local image disappeared during a server-state change. The
repository Dockerfile was rebuilt as `file-filter-bot:qa-multisub-20261030`,
image `8ea67dde9ec1`. The complete accepted suite and all three live phases
ran on **Python 3.13.7 / wzgram 3.1.6**, not the old runtime. Other current
versions are recorded in the evidence. No requirements pin or production
container was changed. Original server services were left untouched.
An offline image inspection also matched all 122 application files against
the tested/current source and confirmed the recorded dependency versions.

Coverage includes **17,914 statements, 5,942 branches and all 122 tracked
application/operator Python files**, including unimported modules:

| Coverage | Lines | Branches | Combined |
|---|---:|---:|---:|
| Automated suite | 60.89% | 48.06% | 57.70% |
| Source-matched automated + live | 70.37% | 57.32% | 67.12% |

All four new shards match the application at process start, process end and
final source. Historical execution is accepted only for unchanged files, with
no line-number remapping. Earlier shards used their recorded dependency
versions; this is accumulated source-matched evidence, not a claim that all
historical live scenarios reran on wzgram 3.1.6. **Whole-bot 100% remains open.**

Limits: Telegram's member limit is a simultaneous per-link membership cap,
not a user binding or lifetime join counter. The live fixture verified actual
server metadata and successful joins; it did not use a second independent
recipient to demonstrate cap rejection because the other available account
owns these chats. Public-chat link selection, non-admin group roles and
synthetic malformed/API failures have automated coverage. Large channel lists,
join-request-only policies, FloodWait bursts, concurrent link consumption,
every legacy retry variant and representative production load were not live
acceptance claims for this round. Premium was disabled here; **premium grants,
removal, expiry and daily quotas are the next bounded QA scope**.

The six bot-created links and two admin recovery links were revoked. Recorded
messages/service messages were removed, both provided memberships restored,
and the one attempt-owned temporary channel deleted. Owned containers and
networks were removed; the two original server services remain running. The
private evidence retains credentials/links locally and the committed record
contains neither. Deployment `.env`, remote MongoDB data and production limits
were unchanged. Stop here until the next `continue`.
