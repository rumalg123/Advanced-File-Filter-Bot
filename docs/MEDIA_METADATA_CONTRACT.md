# PH-015: Canonical media pixel dimensions and quality tags

**Status:** implemented on the existing hardening branch and Draft PR #4.
**No production deployment or migration.**
The persisted fields are **default-off** behind `FEATURE_CANONICAL_MEDIA_METADATA=false`.
Both CI jobs passed at code SHA `40b4a5da` on [run 40811505457](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40811505457). Staging acceptance remains outstanding before enabling writes.

## Root cause and source-of-truth contract

The existing `MediaFile.resolution` contains **either** actual pixel
dimensions (such as `960x540`) **or** an observed quality tag (such as
`540p`). It is unsafe to treat those values as the same data type.

New optional fields on the *existing* `media_files` collection are:

| Field | Type | Source | Meaning |
|---|---|---|---|
| `width` | positive integer or absent | native Telegram media dimensions, validated as a pair | actual number of pixels horizontally |
| `height` | positive integer or absent | native Telegram media dimensions, validated as a pair | actual number of pixels vertically |
| `quality` | lowercase string like `540p` or absent | explicit tag in filename (preferred), otherwise caption | observed release quality label |
| `resolution` | **unchanged legacy string** | preexisting factory behavior | preserve compatibility with existing clients, filters and migrations |

`960x540` does **not automatically imply** `540p`; a numeric height is
not proof the uploader or release labeled the file as that quality.
Unknown dimensions stay absent rather than guessing from a filename.
A text quality label does not create fabricated pixel dimensions.
Native width/height are rejected if missing, non-integer, boolean, zero,
or outside the bounded parser range.

- `core/utils/media_metadata.py` implements quality/dimensions parsing
  and the read-only legacy adapter `effective_quality`.
- `MediaFileFactory` fills the three **in-memory** optional fields on
  new media while keeping the original `resolution` calculation.
- `MediaFile.display_quality` displays explicit new quality or a quality
  tag found in legacy `resolution`, filename or caption. A legacy
  dimension string alone is insufficient.
- `repositories/media.py` continues decoding documents that lack the
  three new fields. The serializer omits **all three** fields unless
  `FEATURE_CANONICAL_MEDIA_METADATA=true` and then omits unknown fields.
- `core/utils/search_matcher.py` queries the new `quality` metadata,
  legacy `resolution` tag and legacy filename/caption without ignoring
  any existing documents. Caption-off search remains caption-off.
- Search cache algorithm revision was bumped from 2 to 3. Old cached
  search results are isolated and expire naturally, with existing PH-011
  cache generation invalidation still in place.

## Why persistent writes are opt-in

**Critical forward/backward compatibility:** an *older* application image
constructs the `MediaFile` dataclass directly from MongoDB document
fields. It does **not** tolerate `width`, `height` or `quality` in
newly inserted media documents. Simply rolling back that old image
after enabling metadata writes could break media reads.

Therefore `FEATURE_CANONICAL_MEDIA_METADATA` defaults to `false`
and the **central serializer**, including the durable indexing path,
will omit all new fields. This allows the new code to be deployed and
rolled back without adding incompatible documents. Do not enable the
flag simply because CI passed. An authorized rollout requires a
separately reviewed backward-reader compatibility version, tested
restoration/removal strategy, and staging acceptance. Turning the flag
off **does not strip new fields from documents already written**.

MongoDB supports optional schema evolution but application readers
must handle mixed schemas:
[MongoDB schema versioning](https://www.mongodb.com/docs/manual/data-modeling/design-patterns/data-versioning/).

## Zero-migration release procedure

1. Leave `FEATURE_CANONICAL_MEDIA_METADATA=false` in every live
   instance, including indexing workers and replacement images.
2. Run compileall, full pytest, isolated real MongoDB tests and CI
   container preflight against the final code revision.
3. On isolated staging, verify document and video ingestion of
   `Doctor X Mafia S01E03 540p`, `960x540` actual dimensions,
   dimension-only media, no metadata and conflicting filename/caption
   quality labels.
4. Verify native `resolution` and original `season/episode` reads,
   old saved files, Telegram search, download, channel auto-indexing,
   durable indexing snapshots and cache invalidation.
5. Compare search counts/result sets across legacy tag, legacy
   dimensions, quality-only and missing metadata in real MongoDB.
   No live backfill, `createIndex`, `dropIndex`, Redis flush, new
   collection or migration is part of PH-015.
6. Roll back to the previous reviewed image **only while the write flag
   has stayed off**. If canonical writes were enabled, old-image
   rollback is blocked until a tested compatibility strategy or
   recoverable database migration is approved.

## Deliberately deferred: optional backfill

No automatic backfill is implemented or executed. Existing documents
continue to work. A future backfill, if needed, must be an explicitly
approved **separate** operation: read-only inventory first, default
dry-run, bounded/restartable batches, limited-scope updates, original
value/change journal or validated snapshot restoration, concurrent
indexing controls and tested rollback on an isolated clone.

The pre-existing `migrate_media_metadata.py` is a legacy season/episode/
resolution writer. **Do not run it as a PH-015 canonical-field backfill**.
It does not provide safe reversible updates for the new contract.

## Known limitations and acceptance

- Label recognition currently accepts **explicit 3- or 4-digit `Np`
  tokens** (e.g. `480p`, `540p`, `720p`, `1080p`, `2160p`).
  Marketing terms such as 4K, UHD, HDR, remux and codecs are not
  converted into an unverified quality tag. If the name and caption
  disagree, filename wins.
- No inference of actual video encoding resolution from a filename tag;
  dimensions only reflect the Telegram media object.
- Filename and caption-based regex fallbacks can remain expensive;
  PH-006/PH-016 require real query plans before any new index.
- Legacy `resolution` stays mixed by design until all consumers are
  audited and a reversible migration is explicitly approved.
- [x] Exact code SHA `40b4a5da` passed Python, MongoDB/Redis and Docker CI ([run 40811505457](https://github.com/rumalg123/Advanced-File-Filter-Bot/actions/runs/40811505457)).
- [ ] Isolated staging Telegram ingestion, old-file search/delivery
      and read-only mixed-schema search confirmed.
- [ ] Default-off rollout and old-image rollback demonstrated.
- [ ] Separate forward/backward compatibility and restore evidence
      before the first enabled canonical metadata write.

**PH-015 is In review until staging and rollout acceptance.**
