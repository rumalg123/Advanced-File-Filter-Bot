# Recoverable channel auto-indexing (PH-005)

**Status:** opt-in, disabled by default. The operator reports durable indexing
enabled in production. Local queue tests pass; remaining operational acceptance
checks are listed below. The log-channel notification regression is fixed in
source on 2026-10-30; production deployment is performed by the operator.


`PROCESSING_DURABLE_INDEXING` is now editable through `/bsetting`; restart to apply changes. The environment initializes missing settings only; existing MongoDB values take precedence. This control change does not waive the acceptance and rollback checks below.

## Summary

Old automatic channel indexing used bounded in-memory queues. Once both were full, the code discarded older overflow messages. Small main queues (10 items or fewer) also had an overflow-drain bug due to hard-coded size subtraction. In-memory queues were lost on restart.

The legacy mode now waits for a free queue slot rather than discarding a received message, and drains overflow even when queues are small. **In-memory mode still loses unprocessed work on a process crash.**

Opt-in durable mode stores the media metadata snapshot before returning from the update handler. It uses a new MongoDB collection (`channel_index_jobs`) without modifying `media_files` or any existing document/index. The collection is created **only when enabled**.

| Event | Durable-mode behavior |
|---|---|
| Duplicate channel message ID | Deterministic job `_id` (`chat_id:message_id`), inserted once |
| Existing file by `file_unique_id` | Existing media logic treats as duplicate; job acknowledged |
| Worker crash or cancellation | Unacknowledged lease expires; another run reclaims |
| Temporary failure | Exponential backoff up to 7 attempts |
| Permanently failing job | Remains in `dead` status; inspection/manual replay |
| Worker loses lease | Stale worker token cannot acknowledge a newer claim |
| Failed enqueue to MongoDB | Explicit exception/log, **not** silently accepted |
| Successfully finished job | Retained for 30 days, then TTL-expired |
| Newly indexed, acknowledged file | Send an Auto-Index Batch Summary to configured `LOG_CHANNEL`; one summary per new durable job |
| Duplicate/replayed file or lost acknowledgement lease | Do not send a new success summary |
| Log-channel send fails | Log a warning; keep indexed media and its completed job, without requeueing or repeating saved-search alerts |

This is **at-least-once**, not exactly-once. A crash after media save but before acknowledgment may replay the job; the existing media unique identity prevents duplicate files. Counts and notification side effects may need separate reconciliation (PH-018).

The durable and memory workers share the summary sender. Memory indexing keeps
one summary per processed batch. Durable indexing sends after a successful job
acknowledgement and attempts the summary even if a channel-counter update or
saved-search enqueue fails. Log delivery is best-effort: a process stop after
acknowledgement can still interrupt the send. Existing completed jobs are not
replayed to backfill old log messages. `LOG_CHANNEL=0` disables the summaries.

## MongoDB footprint

Only new `channel_index_jobs` gets these fields: `_id`, `chat_id`, `message_id`, `media` snapshot, `status`, `attempts`, `created_at`, `next_attempt_at`, lease and optional failure/completion timestamps.

`created_at` and `next_attempt_at` are initially the same UTC instant: a new job
is immediately eligible. Actual processing is recorded by `started_at`,
`attempts` and `finished_at`; matching enqueue timestamps do not prove completion.

Three indexes on this **new collection only**:

1. `channel_job_pending`: status, next_attempt_at, created_at
2. `channel_job_reclaim`: status, lease_until
3. `channel_job_done_retention`: TTL on finished_at, 30 days (dead letters retained)

No migration of the ~97K existing `media_files` records or indexes is required.

## Activation on staging only

Default settings, safe for the existing deployment:

```dotenv
PROCESSING_DURABLE_INDEXING=false
PROCESSING_DURABLE_INDEXING_LEASE_SECONDS=180
```

After backing up and verifying permissions, enable on an isolated staging deployment:

```dotenv
PROCESSING_DURABLE_INDEXING=true
PROCESSING_DURABLE_INDEXING_LEASE_SECONDS=180
```

Restart the staging bot. Workers use the same MongoDB connection as the existing media repository. No Redis Streams or Redis-state migration is required.

## Read-only operator checks

```javascript
db.channel_index_jobs.getIndexes()
db.channel_index_jobs.countDocuments({status: "pending"})
db.channel_index_jobs.countDocuments({status: "processing"})
db.channel_index_jobs.countDocuments({status: "dead"})
db.channel_index_jobs.find(
  {status: "dead"},
  {_id: 1, attempts: 1, last_error: 1, failed_at: 1}
).limit(20)
```

For a specific dead-letter replay, review the reason and invoke `ChannelIndexJobRepository.retry_dead(job_id)` through an approved maintenance workflow. No public Telegram command is introduced.

## Acceptance checklist

- [ ] Full compile/pytest CI on final commit
- [ ] Real MongoDB integration test in staging, not just Python doubles
- [ ] Burst beyond legacy queue limits, verify no lost jobs
- [ ] Crash after claim, let lease expire, verify recovery
- [ ] Duplicate channel message, confirm one job and one media file
- [ ] Force DB failure, verify retry/dead-letter alert and manual replay
- [ ] Restart with pending work; verify it continues
- [ ] Confirm channel counts and saved-search notifications behavior under replay
- [ ] Benchmark MongoDB job index and write overhead on the current database tier

## Limitations and rollback

- Telegram updates never delivered to the bot cannot be reconstructed by the job queue. Telegram Bot API updates are retained for up to 24 hours. Extended downtime can require manual channel-history reconciliation.
- If MongoDB cannot accept the incoming job, the handler raises an error, but this **does not** guarantee Telegram will resend it. A separate checkpoint/reconciliation pass remains useful.
- Successful media writes and auxiliary channel-count/notification effects are not transactional with queue acknowledgement.
- The default single-worker setup avoids complexity; increasing worker count should first implement lease renewal for long jobs.
- Disabling `PROCESSING_DURABLE_INDEXING` rolls back application behavior, but do **not** delete the queue collection during rollback: its pending/dead jobs may be needed for recovery.
- This is additive database storage and indexes. It does not change existing collections.

## References

- [Telegram update retention](https://core.telegram.org/bots/api)
- [Redis Streams as an alternative queue design](https://redis.io/docs/latest/develop/use-cases/streaming/)
