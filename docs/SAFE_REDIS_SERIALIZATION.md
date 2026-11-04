# PH-009: Safe Redis cache deserialization and legacy compatibility

**Status:** Implemented on the existing draft hardening PR. Not deployed. No Redis or MongoDB production changes have been made.

## Security finding

`core/cache/serialization.py` previously used Python `pickle.loads` on both explicitly tagged cache payloads (`p` and `cp`) and as the **last resort** for unprefixed legacy values. Even though new writes defaulted to safe JSON/MessagePack, a malicious or corrupted Redis value could still reach executable pickle. Python explicitly warns that untrusted pickle data can execute arbitrary code.

Source: [Python official pickle security warning](https://docs.python.org/3/library/pickle.html).

## Remediation

- Removed the production `pickle` import and every `pickle.loads` / `pickle.dumps` call from the Redis serializer. There is **no compatibility flag** that reenables execution.
- All new cache writes remain JSON or MessagePack, using the **existing** wire prefixes `j`, `m`, `cj` and `cm`. This is not a Redis key schema/version migration; existing safely-encoded data remains readable.
- Deprecated `SerializationMethod.PICKLE` and `COMPRESSED_PICKLE` hints map to equivalent safe MessagePack variants, even if legacy code changes `PICKLE_DISABLED`. Direct calls to `_serialize_pickle` fail with `TypeError`.
- Explicitly pickle-tagged values `p` and `cp` are treated as cache misses. Binary unprefixed pickle never executes; the safe decoder attempts JSON/MessagePack then inert text and otherwise returns `None`. Legacy unprefixed safe JSON, MessagePack and plain UTF-8 remain supported.
- Compressed `cj` / `cm` values use bounded zlib decompression, with a 16 MiB encoded input limit and 32 MiB decoded output limit. Corrupt/oversized values produce cache misses rather than uncontrolled inflation.
- The serializer reports **aggregate counts** of rejected unsafe/invalid cache entries; it does not log raw cache values or Telegram/user IDs. Cache reads do **not** delete, overwrite or reset existing Redis keys.
- Removed unsafe pickle estimates from `estimate_memory_usage`, so performance tooling does not accidentally invoke pickle.

## Compatibility and expected effects

This is a **read compatibility** change for older pickle-backed Redis entries only.

| Key contents | After the change |
|---|---|
| Safe prefixed JSON / MessagePack, including compressed | Decoded normally |
| Safe unprefixed JSON / MessagePack | Decoded normally |
| Legacy raw UTF-8 string | Decoded safely if unambiguous |
| Historic `p` / `cp` pickle | Cache miss (`None`), never executed |
| Historic unprefixed binary pickle | Cannot execute; typically a cache miss |
| Large / corrupted compressed payload | Cache miss, bounded memory |
| Existing Redis TTL / key name | Unmodified by decoder |
| Existing MongoDB documents / indexes | Unmodified |

An older pickle-backed Telegram session, search page, subscription state or other operational value may appear expired after release. **No automated live unpickling, destructive purge, mass reserialization, FLUSHDB or silent migration has been performed.** A trusted historical pickle value cannot be converted safely by blindly loading it in the production bot. If the inventory indicates important long-lived pickle values, choose a maintenance window, allow expiring sessions to drain, and design a separately reviewed migration from authoritative sources; do not run `pickle.loads` on values read from Redis.

A separate opt-in state Redis (`PH-003`) requires its own checked migration; this phase does not switch Redis backends.

## Read-only inventory before rollout

`scripts/audit_redis_serialization.py` scans **at most 5,000 Redis keys by default**, checks key type/TTL and reads only the **first two bytes** with `GETRANGE`. It outputs **aggregate format counts**, never raw keys, filenames, Redis values, or connection credentials. It does not decode anything, so classification is intentionally approximate (e.g. plain text beginning with `p` can look like a legacy tag).

With existing environment-provided credentials on **staging** (same environment as the bot):

```bash
python scripts/audit_redis_serialization.py --max-keys 5000
```

On a remote, operator-approved Redis instance:

```bash
python scripts/audit_redis_serialization.py --allow-remote --max-keys 5000
```

For the optional `REDIS_STATE_URI` use `--state`. The script requires explicit `--allow-remote` for non-loopback connections. Review its aggregate counts and the TTL characteristics, particularly suspicious **persistent** keys. **Do not post database/Redis credentials or serialized values in GitHub.**

## Verification and release gates

- [x] Tests added for malicious pickle (`__reduce__`) with no execution, including `p`, `cp` and unprefixed binary formats.
- [x] Safe format compatibility and compressed roundtrips, including date formats.
- [x] Tests added for corrupted, truncated and compressed-bomb payloads and rejected unsupported Python objects.
- [x] Tests added for cache manager `get` / `mget`, missing keys, TTL preservation and safe read-only format inventory.
- [x] Ephemeral local Redis integration test added for mixed safe/legacy values.
- [ ] Full CI including MongoDB and two Redis services passes on final PH-009 source.
- [ ] Read-only format/TTL inventory on actual staging/production Redis, approved by operator.
- [ ] Real Telegram staging search, active-session/callback/pagination, rate-limit and subscription smoke checks.
- [ ] Rollback review: reverting code would reintroduce executable pickle loading and should **not** be used as a preferred security rollback. Restore valid state from authoritative sources or regenerate sessions if necessary.
- [ ] No unsupported long-lived pickle state or operational dependency remains before marking PH-009 Verified.

## Boundary of this phase

This is a cache-deserialization security fix, **not** a MongoDB schema migration, Redis flush, authentication change, or PH-003 Redis topology migration. Production deployment remains a separate operator approval after staging checks.

