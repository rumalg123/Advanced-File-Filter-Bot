# PH-022: Durable quota reservation settlement and delivery uncertainty

**Status:** code CI passed ([run 40820004258](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40820004258)) at SHA `5a8c231f`; staging pending / Draft PR #4. **Do not enable in production.** No production data was accessed, no live collection/index was modified, and no application was deployed.

## Defect

Successful MongoDB daily quota reservations could previously be refunded more than once. Refund requests were constrained to the quota day (PH-021) but did not carry a durable reservation identity, so repeated calls could incorrectly credit unused quota. Concurrent Telegram sends create a separate problem: an API timeout or process cancellation is **not proof that a file was never delivered**. The old handlers sometimes refunded even after initiating such an ambiguous send.

MongoDB's single-document update operations are atomic, and the update filter is re-checked against the current document state: https://www.mongodb.com/docs/manual/core/write-operations-atomicity/. Telegram's Bot API returns a Message after a successful send, but does not expose an atomic operation with a MongoDB quota update: https://core.telegram.org/bots/api.

## Opt-in flag and storage

`FEATURE_QUOTA_DELIVERY_LEDGER=false` **by default**. With the flag off, no additional user document fields are written; existing PH-021 reservation returns and refunds keep their legacy behavior.

With explicit staged opt-in, each user document gains a `quota_delivery_ledger` array. Reservation entries contain a random ID, UTC day, reserved amount, status and timestamps. The existing `User` DTO ignores the internal ledger, and the persisted `daily_retrieval_count` / `last_retrieval_date` fields remain unchanged. No new collection, index, Redis key, Telegram callback, or subscription API is required.

The quota reservation and entry creation happen in **one atomic user-document aggregation-pipeline update**. An entry is initially `reserved` and a successful reservation returns the existing three-item tuple with an int-compatible `QuotaReservation` carrying the ID, day and original amount. Subtracting already-delivered files retains this metadata. Re-executing an operation with the same token does not debit again; the code can recover a successful but ambiguously acknowledged database write by searching for its token.

A settlement transitions `reserved` to `settled` and refunds only the confirmed unused amount, **in the same atomic user-document update**. A repeated settlement cannot match the original reserved state and cannot refund again. It also refuses to change a different UTC day and to make the daily counter negative. Fully delivered reservations are settled without a refund.

## Unknown Telegram outcomes

- A file-delivery call that returns a successful Telegram Message is **confirmed**.
- A failure before any file-delivery API attempt is a **known no-send** and may release the reservation.
- An attempted send that times out, is cancelled, loses its result or otherwise has unknown side effects is **uncertain**. The opt-in handler marks the reservation `uncertain` and **does not automatically refund**. Manual operator review is required.
- Partial bulk deliveries are treated conservatively when the unresolved errors cannot be distinguished from successful external sends. This may temporarily withhold a refund from a user whose file was not delivered. An operator must review the evidence before crediting a known-missing portion.

`UserRepository.resolve_uncertain_quota(user_id, reservation_id, refund_count)` is an **internal operator-only** reconciliation method. It is not wired to any user-triggerable command or unauthenticated endpoint. Its atomic transition permits one reviewed adjustment per uncertain record, only for the original UTC day and within the unconfirmed amount. If a new quota day has already been written, its old-day refund is rejected to protect the new day's counters; manual customer-service compensation is a separate process.

**Crucial:** The bot cannot guarantee exactly-once Telegram delivery or exactly-once external send intent. A process kill before marking an attempted delivery uncertain leaves its record `reserved` and needs operator inspection. A returned Telegram error can be a definitive local rejection or an unknown remote outcome. Do not equate one with the other automatically.

## Bounded and compatibility behavior

Each new opt-in reservation prunes `settled` ledger entries and retains unresolved `reserved` and `uncertain` records for review. If 256 unresolved entries accumulate for a user, new quota reservations **fail closed** with an operator-review message instead of silently evicting evidence or growing a user document without bounds. There is no timed automatic deletion of unresolved records. This is a staging safety mechanism, not a production-ready reconciliation dashboard.

The old two-argument `release_quota(user_id, count)` API remains callable. Tokenized amounts settle idempotently, while untagged legacy integer refunds retain PH-021's date-scoped guarded decrement and **are not made globally idempotent**. Older bot replicas without the new flag must not be mixed with ledger-enabled replicas.

The current implementation covers single-file callbacks, single-file deep links, send-all callbacks, and normal completion of multi-file deep-link workflows. **Unhandled process termination and some uncaught bulk cancellation paths may leave a `reserved` record without a final `uncertain` state**; they must be found and reconciled in staging. The default-off rollout is intentional until these paths and operator procedures are reviewed.

## Acceptance checklist

- [x] Full Python regression suite, compile/lint, disposable MongoDB/dual Redis and Docker/Compose preflight **passed** at code SHA `5a8c231f` ([run 40820004258](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40820004258)). Initial CI identified a callback test setup issue and a real MongoDB `$filter` variable-scope bug; both were corrected, with an added assertion that unresolved entries survive midnight rollover.
- [ ] Prove a user never receives more quota through duplicate or concurrent refund attempts, including 20 same-token settlement races, midnight rollovers, manual reconciliation and ledger overflow.
- [ ] Test default flag off: existing user documents remain untouched, and legacy callbacks/deep links still refund known failures.
- [ ] Fault inject a send that returns successfully but then loses its database acknowledgement, a send raising an ambiguous timeout, cancellation during a send, UserIsBlocked and error before API invocation for **single-file callbacks, send-all, deep-link and channel/batch**.
- [ ] Demonstrate that each completed file is charged once, definitely unsent files are refunded once, and ambiguous results remain recorded for operator review without duplicate credits.
- [ ] Review operator monitoring, reconciliation instructions, the 256-unresolved fail-closed threshold and per-user document growth on a production-shaped staging database. Define how to handle old-day customer compensation outside the quota counter.
- [ ] Validate mixed-version upgrade and rollback using a duplicate staging database and isolated Telegram identities. Do not enable the flag while old workers remain active.

## Rollback

Keep `FEATURE_QUOTA_DELIVERY_LEDGER=false` until sign-off. Turning it off returns new reservation/refund behavior to the legacy path but **does not delete** ledger fields previously written. Do not automatically delete, backfill or overwrite unsettled records. Rolling back to an old image will reintroduce duplicate-refund and ambiguous-delivery risks unless all ledger-active jobs are drained/reconciled first.

**PH-022 remains In review**, with CI and staging evidence required and the more general end-to-end exactly-once Telegram guarantee explicitly impossible without API support.
