# Final-source QA and remaining coverage

QA date: 2026-10-29. Application source: `850bc31` (documentation follows).
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
