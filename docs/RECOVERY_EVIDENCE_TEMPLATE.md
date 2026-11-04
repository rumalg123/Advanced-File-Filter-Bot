# PH-012 Staging and recovery drill evidence

**Use a fresh copy for each real operator-run rehearsal. Do not invent results.**
Keep credentials, backup archives, Redis dumps, raw Telegram sessions,
MongoDB documents and all secret tokens **outside GitHub**.

## Environment

| Field | Operator entry |
|---|---|
| Date / timezone | Pending |
| Operator / reviewer | Pending |
| Reviewed commit SHA / image digest | Pending |
| Staging project name | advanced-file-filter-staging |
| Test Telegram bot and dedicated channel isolation verified | Pending |
| Source backup type/timestamp/retention | Pending |
| Source Atlas tier/version and *non-sensitive* cluster reference | Pending |
| Restore target verified to be non-production | Pending |
| Redis config / AOF-RDB mode / version | Pending |
| Backup integrity SHA-256 comparison | Pending |

## Results

| Test | Result (pass/fail/not run) | Evidence reference (no secrets) | Measured elapsed time |
|---|---|---|---|
| Offline env/identity safety preflight | Not run | | |
| Staging Compose network, volumes, no published ports | Not run | | |
| Stage bot startup and test-channel search/file delivery | Not run | | |
| Atlas snapshot / mongodump restore into isolated target | Not run | | |
| Restored Mongo document count and indexes match | Not run | | |
| Redis RDB/AOF restoration into separate instance | Not run | | |
| Restored Redis sessions, TTLs, counters, search generation | Not run | | |
| MongoDB outage and recovery without false search caches | Not run | | |
| Redis outage/restart, bounded retries and rate limiting | Not run | | |
| Rollback to previous reviewed image | Not run | | |
| Operator acceptance | Not run | | |

## Recovery measurements

- **Measured RTO:** not measured. Start/end timestamps: pending.
- **Measured RPO:** not measured. Latest recoverable write/snapshot timestamp: pending.
- **Target RTO and RPO:** not yet defined by the operator.
- **Data excluded or sanitized in staging:** pending.
- **Known issues, incomplete restoration, follow-up items:** pending.
- **Emergency rollback trigger and last-known-good image digest:** pending.
- **Release decision:** Not approved until the required tests are recorded.

All evidence must be independently reviewed before PH-012 can be marked Verified.
