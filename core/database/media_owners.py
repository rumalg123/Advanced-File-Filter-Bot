"""PH-028: immutable media ownership across independent MongoDB deployments.

The primary is the coordinator. Majority-acknowledged reservations never expire
or change owners. A failed/uncertain write can therefore only retry on that same
owner. This is uniqueness/routing, not a transaction spanning MongoDB clusters.
Activation requires stopped writers and a complete, conflict-free inventory.
"""
import hashlib
from datetime import datetime, UTC
from urllib.parse import urlsplit

from pymongo import ReturnDocument, UpdateOne
from pymongo.errors import DuplicateKeyError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern


class MediaOwnershipError(RuntimeError):
    """Fail closed; messages contain neither URIs nor media identifiers."""


def source_key(uri: str, name: str) -> str:
    """Stable across credentials, URI options and configured source ordering."""
    parsed = urlsplit(uri)
    if parsed.scheme not in ('mongodb', 'mongodb+srv') or not parsed.netloc or not name:
        raise ValueError('Invalid media source configuration')
    seeds = parsed.netloc.rsplit('@', 1)[-1].lower().split(',')
    if parsed.scheme == 'mongodb':
        seeds = [seed if ':' in seed.strip('[]') else seed + ':27017' for seed in seeds]
    authority = ','.join(sorted(seeds))
    return hashlib.sha256(f'{parsed.scheme}://{authority}/{name}'.encode()).hexdigest()


def identity_aliases(document: dict) -> list[str]:
    canonical = document.get('file_unique_id')
    if not isinstance(canonical, str) or not canonical:
        raise MediaOwnershipError('Media inventory requires a nonempty canonical identity')
    aliases = [canonical]
    for field in ('_id', 'file_ref'):
        value = document.get(field)
        if value is not None and value != '':
            if not isinstance(value, str):
                raise MediaOwnershipError('Media inventory contains a non-string alias')
            aliases.append(value)
    return sorted(set(aliases))


class GlobalMediaOwners:
    REGISTRY = 'media_owner_registry'
    CONTROL = 'media_owner_control'
    ALIAS_INDEX = 'media_owner_aliases_unique_v1'

    def __init__(self, databases):
        if not databases:
            raise MediaOwnershipError('No media sources configured')
        self.sources = {source_key(db.uri, db.name): db for db in databases}
        if len(self.sources) != len(databases):
            raise MediaOwnershipError('Duplicate configured media source')
        self.primary = source_key(databases[0].uri, databases[0].name)
        self.topology = hashlib.sha256(','.join(sorted(self.sources)).encode()).hexdigest()

    async def _collection(self, key, name):
        source = self.sources.get(key)
        if source is None or not source.is_active or source.pool is None:
            raise MediaOwnershipError('Media owner is unavailable; ownership cannot move')
        collection = await source.pool.get_collection(name)
        return collection.with_options(write_concern=WriteConcern('majority'),
                                       read_concern=ReadConcern('majority'))

    async def _registry(self):
        return await self._collection(self.primary, self.REGISTRY)

    async def assert_ready(self):
        control = await self._collection(self.primary, self.CONTROL)
        config = await control.find_one({'_id': 'topology-v1'})
        if not config or config.get('state') != 'ready' or config.get('topology') != self.topology:
            raise MediaOwnershipError('Media ownership activation is incomplete or topology changed')

    async def _validate_binding(self, key, *, create=False):
        control = await self._collection(key, self.CONTROL)
        expected = {'coordinator': self.primary, 'source': key}
        if create:
            await control.update_one({'_id': 'binding-v1'}, {'$setOnInsert': expected}, upsert=True)
        binding = await control.find_one({'_id': 'binding-v1'})
        if not binding or any(binding.get(k) != v for k, v in expected.items()):
            raise MediaOwnershipError('Media source is bound to a different coordinator/configuration')

    async def attach(self):
        """Read-only startup validation; activation is an explicit operator step."""
        for key in sorted(self.sources):
            await self._validate_binding(key)
            await self._require_unique_canonical(key)
        registry = await self._registry()
        indexes = await registry.index_information()
        if not any(spec.get('key') == [('identifiers', 1)] and spec.get('unique')
                   and not spec.get('sparse') and not spec.get('partialFilterExpression')
                   and not spec.get('collation') for spec in indexes.values()):
            raise MediaOwnershipError('Media alias uniqueness index is missing or incompatible')
        await self.assert_ready()

    async def _require_unique_canonical(self, key, *, create=False):
        collection = await self._collection(key, 'media_files')
        indexes = await collection.index_information()
        matching = [spec for spec in indexes.values() if spec.get('key') == [('file_unique_id', 1)]]
        if any(spec.get('unique') and not spec.get('sparse')
               and not spec.get('partialFilterExpression') and not spec.get('collation') for spec in matching):
            return
        if create and not matching:
            await collection.create_index([('file_unique_id', 1)], unique=True,
                                          name='unique_file_id_idx')
            return
        raise MediaOwnershipError('Media canonical uniqueness index is missing or incompatible')

    async def activate(self, token: str, *, max_docs_per_source=1000000, batch_size=200):
        """Inventory stopped writers. Failed runs remain locked until token resume.

        No lease stealing, reassignment, deletions or automated deduplication.
        Identity metadata may be partially adopted on failure; ready is never set.
        """
        if not isinstance(token, str) or not 1 <= len(token) <= 128:
            raise ValueError('An explicit activation token (1..128 characters) is required')
        if type(max_docs_per_source) is not int or not 1 <= max_docs_per_source <= 1000000:
            raise ValueError('Invalid media inventory bound')
        if type(batch_size) is not int or not 1 <= batch_size <= 1000:
            raise ValueError('Invalid media inventory batch size')
        # Deterministic first binding arbitrates simultaneous competing primaries.
        for key in sorted(self.sources):
            await self._validate_binding(key, create=True)
        control = await self._collection(self.primary, self.CONTROL)
        config = {'_id': 'topology-v1', 'topology': self.topology,
                  'state': 'initializing', 'activation_token': token}
        try:
            await control.insert_one(config)
        except DuplicateKeyError:
            existing = await control.find_one({'_id': 'topology-v1'})
            if existing.get('topology') != self.topology:
                raise MediaOwnershipError('Media topology change requires explicit migration') from None
            if existing.get('state') == 'ready':
                await self.attach()
                return {'ready': True, 'already_active': True, 'adopted': 0}
            if existing.get('activation_token') != token:
                raise MediaOwnershipError('Activation locked; resume requires the original token and stopped workers') from None
        registry = await self._registry()
        await registry.create_index([('identifiers', 1)], unique=True, name=self.ALIAS_INDEX)
        adopted = 0
        for key in sorted(self.sources):
            await self._require_unique_canonical(key, create=True)
            collection = await self._collection(key, 'media_files')
            cursor = collection.find({}, {'file_unique_id': 1, 'file_ref': 1}).batch_size(batch_size)
            operations = []
            scanned = 0
            try:
                async for document in cursor:
                    scanned += 1
                    if scanned > max_docs_per_source:
                        raise MediaOwnershipError('Media inventory bound exceeded; activation remains incomplete')
                    canonical = document.get('file_unique_id')
                    aliases = identity_aliases(document)
                    operations.append(UpdateOne({'_id': canonical, 'owner_key': key}, {
                        '$setOnInsert': {'owner_key': key, 'state': 'committed',
                                         'created_at': datetime.now(UTC)},
                        '$addToSet': {'identifiers': {'$each': aliases}},
                    }, upsert=True))
                    if len(operations) >= batch_size:
                        await registry.bulk_write(operations, ordered=False)
                        operations.clear()
                if operations:
                    await registry.bulk_write(operations, ordered=False)
                adopted += scanned
            finally:
                await cursor.close()
        result = await control.update_one({**config}, {'$set': {'state': 'ready'}})
        if result.modified_count != 1:
            raise MediaOwnershipError('Media activation lost its coordinator lock')
        await self.attach()
        return {'ready': True, 'already_active': False, 'adopted': adopted}

    async def inventory(self, *, max_docs_per_source=1000000):
        """Read-only cross-namespace inventory, safe before activation."""
        if type(max_docs_per_source) is not int or not 1 <= max_docs_per_source <= 1000000:
            raise ValueError('Invalid media inventory bound')
        seen, canonicals = {}, set()
        scanned = conflicts = 0
        for key in sorted(self.sources):
            collection = await self._collection(key, 'media_files')
            cursor = collection.find({}, {'file_unique_id': 1, 'file_ref': 1}).batch_size(200)
            count = 0
            try:
                async for document in cursor:
                    count += 1
                    if count > max_docs_per_source:
                        raise MediaOwnershipError('Media inventory bound exceeded')
                    aliases = identity_aliases(document)
                    identity = (document['file_unique_id'], key)
                    conflicts += identity in canonicals
                    canonicals.add(identity)
                    for alias in aliases:
                        if alias in seen and seen[alias] != identity:
                            conflicts += 1
                        seen[alias] = identity
                scanned += count
            finally:
                await cursor.close()
        return {'complete': True, 'sources': len(self.sources), 'documents': scanned,
                'identity_conflicts': conflicts, 'eligible': conflicts == 0}

    async def reserve(self, canonical: str, aliases: list[str], proposed_owner: str):
        await self.assert_ready()
        if proposed_owner not in self.sources:
            raise MediaOwnershipError('Unknown proposed media owner')
        aliases = identity_aliases({'file_unique_id': canonical}) + aliases
        if any(not isinstance(alias, str) or not alias for alias in aliases):
            raise MediaOwnershipError('Invalid media alias')
        registry = await self._registry()
        update = {'$setOnInsert': {'owner_key': proposed_owner, 'state': 'reserved',
                                   'created_at': datetime.now(UTC)},
                  '$addToSet': {'identifiers': {'$each': sorted(set(aliases))}}}
        try:
            return await registry.find_one_and_update({'_id': canonical}, update,
                upsert=True, return_document=ReturnDocument.AFTER)
        except DuplicateKeyError:
            # A concurrent canonical upsert can win. Alias conflicts still fail.
            try:
                existing = await registry.find_one_and_update({'_id': canonical},
                    {'$addToSet': update['$addToSet']}, return_document=ReturnDocument.AFTER)
                if existing is not None:
                    return existing
            except DuplicateKeyError:
                pass
            raise MediaOwnershipError('Media alias is already reserved by another identity') from None

    async def resolve(self, identifier):
        await self.assert_ready()
        return await (await self._registry()).find_one({'identifiers': identifier})

    async def find(self, identifier):
        reservation = await self.resolve(identifier)
        if reservation is None:
            return None
        collection = await self._collection(reservation['owner_key'], 'media_files')
        document = await collection.find_one({'file_unique_id': reservation['_id']})
        if document is not None and reservation['state'] != 'committed':
            await self._commit(reservation)
        return document

    async def _commit(self, reservation):
        await (await self._registry()).update_one(
            {'_id': reservation['_id'], 'owner_key': reservation['owner_key']},
            {'$set': {'state': 'committed'}})

    async def create(self, document, proposed_owner):
        reservation = await self.reserve(document['file_unique_id'], identity_aliases(document), proposed_owner)
        collection = await self._collection(reservation['owner_key'], 'media_files')
        query = {'file_unique_id': document['file_unique_id']}
        try:
            result = await collection.update_one(query, {'$setOnInsert': document}, upsert=True)
            inserted = result.upserted_id is not None
        except DuplicateKeyError:
            # Canonical insert race: return the winner, never try another shard.
            if await collection.find_one(query) is None:
                raise MediaOwnershipError('Media owner write conflicted with existing identity') from None
            inserted = False
        stored = await collection.find_one(query)
        if stored is None:
            raise MediaOwnershipError('Media owner write was not observable; reservation retained')
        await self._commit(reservation)
        return inserted, stored

    async def update(self, identifier, changes):
        if {'_id', 'file_unique_id', 'file_id'} & changes.keys():
            raise MediaOwnershipError('Canonical media identity and owner are immutable')
        reservation = await self.resolve(identifier)
        if reservation is None:
            return False
        alias = changes.get('file_ref')
        if alias is not None and alias != '':
            await self.reserve(reservation['_id'], [alias], reservation['owner_key'])
        collection = await self._collection(reservation['owner_key'], 'media_files')
        # Changing text invalidates the optional search prefilter in this write.
        from core.utils.search_tokens import SEARCH_TOKEN_FIELD, SEARCH_TOKEN_VERSION_FIELD
        operation = {'$set': changes}
        if {'file_name', 'caption'} & changes.keys():
            operation['$unset'] = {SEARCH_TOKEN_FIELD: '', SEARCH_TOKEN_VERSION_FIELD: ''}
        result = await collection.update_one({'file_unique_id': reservation['_id']}, operation)
        return result.matched_count > 0

    async def delete(self, identifier):
        reservation = await self.resolve(identifier)
        if reservation is None:
            return 0
        collection = await self._collection(reservation['owner_key'], 'media_files')
        result = await collection.delete_one({'file_unique_id': reservation['_id']})
        # Keep identity reservations forever, including after deletion. Reingest
        # uses the same owner; deletion is not a ban/tombstone for that identity.
        return result.deleted_count
