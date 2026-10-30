# PH-028: Global media identity and ownership

**Implementation complete; local and three-source remote QA passed.**
`DATABASE_GLOBAL_OWNER_REGISTRY` is managed through `/bsetting`, with an initial
default of `false`. Multiple distinct valid URI/database pairs unlock editing;
the recommended default becomes `true` once matching activation is ready.
Existing saved values override environment initialization. Without activation and
this flag, creation across independent databases remains blocked. Production
rollout and merging remain separate operator decisions.

## Guarantees and limits

`GlobalMediaOwners` uses the first configured MongoDB as coordinator. A unique
multikey index on one `identifiers` array enforces collisions across canonical
`file_unique_id`, Telegram `_id` and `file_ref` namespaces. Majority-acknowledged
atomic reservation happens before any media insertion. The winning owner is
immutable; concurrent creators, retries and pending reservations use that owner.
Each source also requires a full unique canonical index. New inserts use an
idempotent canonical upsert on exactly one owner.

Claims never expire, move or get stolen. A failed coordinator or owner causes an
error rather than a fallback write elsewhere. After a crash before insertion,
retry writes to the reserved owner. After insertion but before commit, a read or
retry verifies the owner document and repairs the committed marker. A lost
acknowledgment therefore cannot create another shard copy.

This is not an atomic transaction across MongoDB clusters. During an uncertain
write the caller may receive an error even though the owner accepted it; retry
resolves that uncertainty. Concurrent deletion and insertion have normal
last-operation behavior on that owner. Deletion retains all identity reservations;
explicit reingestion recreates on the same owner. Deletion is not a permanent
ban. Owner transfer, source removal and coordinator migration require a separate
offline migration; this implementation deliberately provides no automatic move.
All writers must use this protocol. An external client or old image with direct
MongoDB write privileges can bypass application invariants.

The coordinator retains reservations for every indexed identity, including
deleted files and media owned by other sources. Size it for that permanent
metadata in addition to its own media; switching the media write source does
not transfer or shrink the registry.

For a single-source production deployment with no bindings, adding the first
secondary later uses the initial two-source activation procedure below. Do it
before the coordinator is full: the registry and its indexes require additional
space on the original primary. That primary also contains users/settings and
other application state, so replacing it with an empty new primary is not a
media-only configuration change. Adding a third source after two-source
activation requires a separate membership migration. See the
[capacity and cutover plan](PRODUCTION_CUTOVER.md).

Write-source statistics include `dataSize + indexSize` after BUG-060. The
configured soft limit is evaluated per database and is not a guarantee of free
space across other databases on the same deployment. Leave provider headroom;
an additional database name in a capped cluster does not expand its capacity.

## Activation

Before the maintenance window, with multiple sources configured and indexing
paused, stage `DATABASE_GLOBAL_OWNER_REGISTRY=true` through `/bsetting`.
Do not restart between staging that value and completing activation. Then stop
every writer and follow the steps below. For an entirely offline rollout,
explicitly update the primary's existing `bot_settings` record as part of the
maintenance procedure; setting only `.env` will not override a saved `false`.
Adding URI/name pairs requires loading the new environment through container
recreation; it does not itself activate ownership.

1. Back up the selected sources. Stop **every** writer, including index workers,
   old bot processes and maintenance jobs. Inventory is not a cross-cluster
   snapshot while external writers continue.
2. Privately export `DATABASE_URI`, `DATABASE_NAME`, `DATABASE_URIS` and
   `DATABASE_NAMES`, as for the bot. For seed-list URIs containing commas, instead
   export `MEDIA_OWNER_SOURCES_JSON` as an array of `{uri, name}` objects. The
   first source is the coordinator; never reorder it. Activation requires at
   least two sources, matching the bot's multi-database startup contract. Include
   the complete intended topology before activation: adding another source later
   requires an offline migration. A single-source read-only inventory is allowed.
3. Run the default read-only cross-namespace inventory:

   ```sh
   python -m scripts.activate_media_owners --allow-remote
   ```

   Require `complete=true`, `eligible=true` and zero identity conflicts. Missing
   canonical IDs, invalid aliases, unavailable sources and scan overflow are
   hard errors. Resolve legacy conflicts explicitly; no automatic deletion or
   deduplication occurs.
4. Choose and retain an activation token, then apply while writers remain stopped:

   ```sh
   python -m scripts.activate_media_owners --allow-remote --apply --activation-token QA-CUTOVER-1
   python -m scripts.activate_media_owners --allow-remote --status
   ```

   The CLI and library default to a maximum of 10,000,000 records per source
   (`--limit` can reduce it),
   with bounded batches. Activation binds every source to its coordinator,
   creates the registry and required uniqueness indexes, and adopts existing
   records. Existing compatible unique indexes are reused. Incompatible indexes
   block activation; nothing is dropped, renamed or made less restrictive.
5. Confirm the effective saved `DATABASE_GLOBAL_OWNER_REGISTRY=true` (or its
   environment initialization when no record exists), keep the entire original topology,
   and restart the new bot. Startup only attaches to an already-ready registry;
   it never activates implicitly. Existing binding markers prevent silently
   disabling ownership or restarting as a single-source bot. Secondary ordering
   may change; coordinator/source membership may not.
6. Test indexing, duplicate indexing, delivery via all aliases, owner updates,
   deletion, pagination, restart and outage behavior before admitting writers.
   Multi-database keyword bulk deletion remains explicitly unsupported.

## Interrupted activation, recovery and rollback

An interrupted activation leaves `initializing`, partial adoption and permanent
source bindings. No new media writes are admitted. Stop the interrupted process,
verify writers remain stopped, fix the cause and resume with the **same** token.
The scan restarts idempotently and publishes `ready` only after every source
completes. A different token cannot steal the lock. Do not run two operators with
the same token or mutate control documents manually.

A binding disagreement, changed coordinator/topology or missing uniqueness index
fails startup. Restore the intended topology/index definition and revalidate;
never point a fresh coordinator at the same sources to bypass recovery.

Once activated, toggling the flag off is **not** a safe rollback. Roll back to a
previous build that implements this protocol, with identical configuration, or
keep writers stopped. An older image requires an offline export/consolidation,
complete identity audit and explicit retirement of source bindings before writes
resume. This runbook does not offer an automatic destructive retirement command.
Search-token rollback is independent; see [its runbook](INDEXED_MEDIA_SEARCH.md).

The settings backend rejects disabling bound ownership through boolean buttons,
free-text edits, defaults or imports. A single/invalid-source configuration has
no edit controls. Startup still rejects a missing binding/index, incomplete
activation, or topology mismatch regardless of how the setting was changed.

## Local acceptance evidence, 2026-10-29

Real disposable MongoDB tests cover 100 simultaneous creators choosing different
owners; cross-namespace alias races; legacy duplicates; conflicting canonical
indexes; competing coordinators; interrupted bounded inventory and token resume;
crashes before write and after owner acknowledgment; coordinator/owner outages;
restart; immutable identity; alias update; owner-only deletion and reingestion;
and real operator inventory/apply/status commands. No raw URI or media identity
appears in operator reports. The earlier defensive audit and flag-off interlock
remain regression-tested. Current remote results are recorded in
[the active QA log](qa/coverage-expansion/STATUS.md).

## Source configuration pairing

Bot startup and the legacy metadata tool normalize URI/name pairs together.
Repeating the primary pair no longer shifts the next source's name; two distinct
databases on the same URI remain distinct sources. Missing additional names
retain the primary-name fallback. Excess names are rejected instead of silently
truncated. Eight configuration contracts and related ownership/recovery tests pass.
