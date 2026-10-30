# PH-018: Saved-search alert queue, leases, recovery and rollout

**Status:** Code and CI passed ([run 40814929762](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40814929762)). The operator reports this mode enabled in production; fault/reconciliation acceptance checks below remain outstanding. The feature is opt-in.


`PROCESSING_DURABLE_SAVED_SEARCH_ALERTS` is now editable through `/bsetting`; restart to apply changes. The environment initializes missing settings only; existing MongoDB values take precedence. This control change does not waive the acceptance and rollback checks below.

## Original failure

The previous `FeatureService.schedule_new_media` spawned a new asyncio
task on every indexed media file. Under a burst, the bot could create
unbounded matching tasks. Tasks disappeared on process restart. A
successful claim in `saved_search_notifications` could also remain after a
crash before sending, preventing future attempts.

PH-017 already fixed the newest-500 subscriber cutoff, but one matching
task could still scan every active subscriber. PH-018 controls concurrent
jobs and adds recoverable progress, not a full inverted search engine.

## Compatibility and rollout gates

Both configuration switches must be TRUE:
- `FEATURE_SAVED_SEARCH_ALERTS=true`: existing optional alerts toggle.
- `PROCESSING_DURABLE_SAVED_SEARCH_ALERTS=true`: NEW optional Mongo queue.

Both remain **FALSE by default**. Worker count `PROCESSING_SAVED_SEARCH_ALERT_WORKERS`
defaults to 2, validated 1 to 4 per process. Deploy with both flags off
first and verify legacy behavior and read-only monitoring. Do not enable
in production based on CI alone.

When both flags are enabled, the queue creates **one new Mongo collection**,
`saved_search_alert_jobs`. Only that new collection gets three indexes:
- `saved_alert_pending` on status/next_attempt_at/created_at
- `saved_alert_reclaim` on status/lease_until
- `saved_alert_completed_retention`, a TTL index on `finished_at`

The TTL field is set **only for completed jobs**; pending, processing
and dead jobs must remain available for recovery. The TTL worker is
asynchronous and deletion timing is not instantaneous. See the
[MongoDB TTL behavior](https://www.mongodb.com/docs/manual/core/index-ttl/).

The existing `saved_searches`, `media_files` and
`saved_search_notifications` collections and their indexes are retained.
The new mode stores `status`, `lease_token`, `lease_until` and `sent_at`
on **new recipient claim documents**, leaving older claims readable as
already delivered. No backfill, destructive index change, or collection
rename is part of PH-018.

## Job and delivery state machines

### Work admission
The relevant indexing paths await `FeatureService.persist_new_media`
rather than creating untracked tasks. It idempotently enqueues by
`sha256(file_unique_id)` after the media record is stored. Queue snapshots
contain only the minimal file fields required for existing Telegram
buttons and notifications, not entire Telegram messages. This prevents
unbounded application task spawning when opted into the queue. Producers
are backpressured by MongoDB enqueue latency/failure and should expose
errors to operators.

**Important non-atomicity:** the media insert and alert enqueue are two
different Mongo writes, not one transaction. Crash between them may
leave a file with no alert job. The channel durable index worker has a
separate lease/ack path. Current code does **not** guarantee automatic
reconciliation for these cross-write gaps. Stage fault injection and a
reviewed reconciliation workflow are required before claiming lossless
end-to-end indexing/notification. Do not claim transactionality.

### Job leasing
Workers atomically claim one pending job whose retry is due, or a job
whose `processing` lease has expired, using findOneAndUpdate. Each
attempt gets a fresh random fencing token. Only the current lease
holder can checkpoint or acknowledge. Lease renewal happens in a
separate supervised heartbeat; a lost lease causes the worker to fail
and requeue rather than advancing checkpoints.

Each completed **100-subscriber page** is checkpointed by last seen
`_id`. On crash, the job resumes after the last fully processed page.
There is no skip-over on partially processed pages or on an unresolved
recipient claim. At most one page is replayed under ordinary recovery.

Failure retries use bounded exponential backoff and a maximum of eight
attempts. Exhausted jobs remain in the `dead` state for explicit
operator review. `retry_dead(job_id)` is an explicit replay operation,
not a background automatic reset.

### Per-recipient claim
For each matching subscriber, the worker either:
1. Creates a new `sending` recipient claim with a short delivery lease.
2. Recognizes `sent` or an old-format claim as completed, avoiding a
   repeat notification.
3. Recognizes an unexpired `sending` lease as in-flight: stop the page,
   retry the job later without advancing the cursor past that recipient.
4. Reclaims an expired lease and tries sending again.

Successful Telegram API completion is followed by a token-fenced
`sent` acknowledgement. A known failed send releases that worker's
claim and replays the page on retry. A crash before the send
acknowledgement may cause a duplicate delivery after the lease expires.
**Exactly-once Telegram sends are impossible to guarantee with this
uncoordinated external API and Mongo state**. The narrower guarantee
is deduplication of *acknowledged successful* sends plus at-least-once
retries for recoverable queued work.

A Telegram operation that lasts longer than the recipient lease may
be reclaimed by another worker. Production FloodWait behavior,
lease durations and API retry timeouts MUST be validated in staging
before enabling. Do not overclaim idempotency across an unknown external
send outcome.

## Monitoring and bounds

### Primary storage footprint

When both alert flags are enabled, every newly indexed distinct media file
creates one `saved_search_alert_jobs` document, even if there are no active or
matching saved searches. The worker scans subscribers and may finish with zero
sends. Enabling the flags does not enqueue the existing catalogue, and the
search-token backfill does not produce alert jobs.

| Collection | Purpose | Current retention |
|---|---|---|
| `saved_searches` | User-created query subscriptions | Until explicitly removed |
| `saved_search_alert_jobs` | Recoverable per-file matching work and media metadata snapshot | Completed jobs expire 30 days after `finished_at`; pending/processing/dead jobs lack that TTL marker and remain recoverable |
| `saved_search_notifications` | Per-search/per-file delivery claims used for recipient deduplication | 180 days from `created_at`, through the feature repository's TTL index |

The jobs contain file IDs, names, captions and state, not Telegram video/document
contents. They still consume primary database data and index space. At 10,000
new files/day, a 30-day completed-job history is approximately 300,000 job
documents, plus live backlog and per-recipient delivery claims. Actual byte cost
depends on metadata size and indexes. MongoDB TTL cleanup is asynchronous, so
expiration is not an exact deletion deadline. See
[MongoDB TTL behavior](https://www.mongodb.com/docs/manual/core/index-ttl/).

Completed-job retention and admission when there are no subscribers are possible
future storage optimizations. Neither policy is changed by the operator-script
fixes on 2026-10-30. Shortening recipient-claim retention changes deduplication
semantics; pending/dead work needs review rather than bulk deletion to save space.

### Queue metrics

`SavedSearchAlertJobRepository.metrics()` reports queue counts:
`pending`, `processing`, `dead`, and
`oldest_pending_seconds`. Nothing prints private filenames or user IDs.
This is an operator API in code, not a new unauthenticated HTTP
endpoint. The fixed worker count bounds the number of concurrent jobs
in one process, but not across multiple replicas. Page memory remains
bounded by PH-017's 100-document keyset fetches.

No hard global Mongo queue size limit is implemented. Backlog is
persisted instead of silently dropped, but storage/backlog size may
grow without limit if arrival rate permanently exceeds worker
throughput. No separate broker or hidden Redis key migration.

## Tests and approval checklist

- [x] Full CI passed at SHA `e092b9af`: Python, disposable MongoDB/dual
      Redis, compile/lint and Docker/Compose preflight.
      [Run 40814929762](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40814929762).
- [x] Verify both flags default off and **no new collection or index**
      is created in the default deployment.
- [x] Verify queue duplicate submission, claim/reclaim, lease fencing,
      checkpoints, worker cancellation, bounded worker count,
      exponential retry/dead letters and explicit operator replay.
- [x] Verify real MongoDB recipient claims, legacy claim compatibility,
      success acknowledgement, failure release, stale lease and
      recovery from a partial page without duplicate acknowledged sends.
- [ ] Stage producer crashes between media save and job enqueue, worker
      kill/restart and Telegram send-then-crash window. Record actual
      gaps/duplicates and design a safe reconciliation process.
- [ ] Measure queue depth, oldest job lag, per-file subscriber pages,
      worker utilization, API send latency, FloodWait and retries under
      burst conditions. Define alerting thresholds before rollout.
- [ ] Verify shutdown drains or safely abandons jobs, background tasks
      tracked by handler manager, and subsequent process recovers leases.
- [ ] Before rollout compare single/multiple replica lease behavior,
      MongoDB indexes, TTL storage, and old image rollback.

## Rollback

Turn `PROCESSING_DURABLE_SAVED_SEARCH_ALERTS=false` and deploy a reviewed
previous image. The optional collection and in-flight jobs are **retained**,
not dropped. Turning the flag off stops workers but does **not** drain
or complete queued work. Re-enabling the durable flag resumes lease
recovery, subject to existing TTL retention for completed jobs. Do not
run two bot versions with mixed claim semantics concurrently during
the rollout; coordinate the cutover.

No production deployment, PR merge, Redis flush, existing media schema
change, automatic index deletion or legacy record migration was
performed as part of this phase.

**QA reconciliation (2026-10-29):** the checked contracts above passed the current disposable MongoDB/dual-Redis regression suite. Relevant real-Telegram and remote multi-source results are recorded in the [active QA evidence](qa/coverage-expansion/STATUS.md). Unchecked operational/load/rollout gates remain pending.
