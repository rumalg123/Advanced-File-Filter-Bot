"""Real-Mongo concurrency, recovery and rollback contracts for PH-028."""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import BulkWriteError, DuplicateKeyError

from core.database.media_owners import GlobalMediaOwners, MediaOwnershipError, source_key, identity_aliases
from core.database.multi_pool import DatabaseInfo, MultiDatabaseManager
from repositories.media import MediaRepository, MediaFile, FileType
from scripts.activate_media_owners import source_configuration
from scripts.profile_media_search import is_local


class Pool:
    def __init__(self, db): self.db = db
    async def get_collection(self, name): return self.db[name]
    async def execute_with_retry(self, function, *args, **kwargs):
        return await function(*args, **kwargs)


@pytest_asyncio.fixture
async def topology():
    uri = os.getenv('TEST_MONGO_URI')
    if not uri: pytest.skip('Requires disposable local MongoDB')
    assert is_local(uri)
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=3000)
    names = ['qa_owners_' + uuid4().hex for _ in range(3)]
    sources = [DatabaseInfo(uri=uri, name=name, pool=Pool(client[name])) for name in names]
    try:
        yield sources
    finally:
        for name in names: await client.drop_database(name)
        client.close()


def document(uid='unique', file_id='file', ref='ref'):
    return {'_id': file_id, 'file_unique_id': uid, 'file_ref': ref, 'file_name': 'QA doctor',
            'file_size': 10, 'file_type': 'video', 'mime_type': 'video/mkv', 'caption': 'caption',
            'indexed_at': '2026-10-29T00:00:00+00:00'}


async def collections(sources):
    return [await source.pool.get_collection('media_files') for source in sources]


async def total(sources):
    return sum(await asyncio.gather(*(c.count_documents({}) for c in await collections(sources))))


@pytest.mark.asyncio
async def test_single_source_activation_is_rejected_without_database_mutations(topology):
    source = topology[0]
    owners = GlobalMediaOwners([source])
    assert (await owners.inventory()) == {
        'complete': True, 'sources': 1, 'documents': 0,
        'identity_conflicts': 0, 'eligible': True,
    }
    with pytest.raises(MediaOwnershipError, match='at least two'):
        await owners.activate('unsupported-single-source')
    assert await source.pool.db.list_collection_names() == []


def test_cli_single_source_activation_fails_before_connecting(monkeypatch, capsys):
    from scripts import activate_media_owners as cli
    monkeypatch.setenv('MEDIA_OWNER_SOURCES_JSON',
                       '[{"uri":"mongodb://localhost","name":"qa"}]')
    monkeypatch.setattr('sys.argv', ['activate_media_owners', '--apply',
                                   '--activation-token', 'qa'])
    operate = AsyncMock()
    monkeypatch.setattr(cli, 'operate', operate)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert 'at least two' in capsys.readouterr().err
    operate.assert_not_awaited()


@pytest.mark.asyncio
async def test_100_concurrent_creators_choose_exactly_one_permanent_owner(topology):
    owners = GlobalMediaOwners(topology)
    assert (await owners.activate('race'))['ready']
    keys = list(owners.sources)
    results = await asyncio.gather(*(owners.create(document(file_id=f'file-{i}', ref=f'ref-{i}'),
        keys[i % 3]) for i in range(100)))
    assert sum(inserted for inserted, _ in results) == 1
    assert len({stored['_id'] for _, stored in results}) == 1
    assert await total(topology) == 1
    reservation = await owners.resolve('unique')
    assert reservation['state'] == 'committed'
    assert len(reservation['identifiers']) == 201
    # Every alias, including a losing contender's Telegram file ID, routes to
    # the same canonical record rather than to a different shard.
    assert (await owners.find('ref-99'))['_id'] == results[0][1]['_id']


@pytest.mark.asyncio
@pytest.mark.parametrize('collision', ['file', 'ref', 'unique'])
async def test_cross_namespace_alias_races_reject_the_losing_identity(topology, collision):
    owners = GlobalMediaOwners(topology); await owners.activate('aliases')
    keys = list(owners.sources)
    left = document('unique', 'file', 'ref')
    right = document('right', 'right-file', collision)
    results = await asyncio.gather(owners.create(left, keys[0]), owners.create(right, keys[1]),
                                   return_exceptions=True)
    assert sum(isinstance(result, MediaOwnershipError) for result in results) == 1
    assert await total(topology) == 1


@pytest.mark.asyncio
async def test_reservation_survives_crash_before_write_and_never_changes_owner(topology):
    owners = GlobalMediaOwners(topology); await owners.activate('crash-claim')
    keys = list(owners.sources)
    await owners.reserve('unique', ['file', 'ref'], keys[1])
    topology[1].is_active = False
    with pytest.raises(MediaOwnershipError, match='unavailable'):
        await owners.create(document(), keys[2])
    assert await total(topology) == 0
    topology[1].is_active = True
    restarted = GlobalMediaOwners(topology); await restarted.attach()
    assert (await restarted.create(document(), keys[2]))[0]
    assert (await collections(topology))[1] is not None
    assert await (await collections(topology))[1].count_documents({}) == 1
    assert (await restarted.resolve('unique'))['owner_key'] == keys[1]


@pytest.mark.asyncio
async def test_owner_write_ack_loss_is_recovered_by_read_or_retry(topology, monkeypatch):
    owners = GlobalMediaOwners(topology); await owners.activate('crash-ack')
    keys = list(owners.sources)
    commit = owners._commit
    monkeypatch.setattr(owners, '_commit', AsyncMock(side_effect=ConnectionError('ack lost')))
    with pytest.raises(ConnectionError): await owners.create(document(), keys[2])
    assert await total(topology) == 1
    assert (await owners.resolve('unique'))['state'] == 'reserved'
    monkeypatch.setattr(owners, '_commit', commit)
    assert (await owners.find('file'))['file_unique_id'] == 'unique'
    assert (await owners.resolve('unique'))['state'] == 'committed'
    assert not (await owners.create(document(), keys[0]))[0]
    assert await total(topology) == 1


@pytest.mark.asyncio
async def test_coordinator_outage_never_writes_to_available_secondaries(topology):
    owners = GlobalMediaOwners(topology); await owners.activate('outage')
    keys = list(owners.sources)
    topology[0].is_active = False
    for operation in [owners.create(document(), keys[1]), owners.find('unique'),
                      owners.update('unique', {'caption': 'new'}), owners.delete('unique')]:
        with pytest.raises(MediaOwnershipError): await operation
    assert await total(topology) == 0


@pytest.mark.asyncio
async def test_adoption_aliases_update_delete_and_reingest_keep_same_owner(topology):
    cols = await collections(topology)
    await cols[2].insert_one(document())
    owners = GlobalMediaOwners(topology)
    assert (await owners.inventory()) == {'complete': True, 'sources': 3,
        'documents': 1, 'identity_conflicts': 0, 'eligible': True}
    assert await cols[0].database.list_collection_names() == []
    assert (await owners.activate('adopt'))['adopted'] == 1
    keys = list(owners.sources)
    await cols[2].update_one({}, {'$set': {'_search_terms_v1': ['doctor'], '_search_terms_version': 1}})
    assert await owners.update('file', {'caption': 'Spring', 'file_ref': 'new-ref'})
    stored = await owners.find('new-ref')
    assert stored['caption'] == 'Spring' and '_search_terms_version' not in stored
    assert (await owners.find('ref'))['_id'] == 'file'
    assert await owners.update('unique', {'caption': 'Spring'})  # matched no-op
    assert await owners.delete('ref') == 1
    assert await owners.find('unique') is None
    assert await owners.delete('ref') == 0
    assert await owners.update('ref', {'caption': 'absent'}) is False
    assert (await owners.create(document(), keys[0]))[0]
    assert await cols[2].count_documents({}) == 1 and await total(topology) == 1
    assert (await owners.activate('another-token'))['already_active']


@pytest.mark.asyncio
async def test_updates_cannot_change_identity_or_capture_other_alias(topology):
    owners = GlobalMediaOwners(topology); await owners.activate('immutable')
    key = next(iter(owners.sources))
    await owners.create(document(), key)
    await owners.create(document('other', 'other-file', 'other-ref'), key)
    for changes in [{'file_unique_id': 'other'}, {'_id': 'other-file'}, {'file_id': 'x'},
                    {'file_ref': 'other-ref'}, {'file_ref': 123}]:
        with pytest.raises(MediaOwnershipError): await owners.update('unique', changes)
    assert (await owners.find('unique'))['file_ref'] == 'ref'
    assert await owners.update('missing', {'caption': 'new'}) is False
    assert await owners.delete('missing') == 0


@pytest.mark.asyncio
async def test_incomplete_activation_requires_same_token_and_complete_rescan(topology):
    col = (await collections(topology))[0]
    await col.insert_many([document(str(i), 'f'+str(i), 'r'+str(i)) for i in range(3)])
    owners = GlobalMediaOwners(topology)
    with pytest.raises(MediaOwnershipError, match='bound'):
        await owners.activate('resume-token', max_docs_per_source=1, batch_size=1)
    with pytest.raises(MediaOwnershipError): await owners.attach()
    with pytest.raises(MediaOwnershipError, match='locked'): await owners.activate('wrong-token')
    assert (await owners.activate('resume-token', batch_size=2))['adopted'] == 3
    await owners.attach()
    with pytest.raises(MediaOwnershipError, match='bound'): await owners.inventory(max_docs_per_source=1)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['canonical', 'alias', 'cross-namespace', 'same-shard'])
async def test_conflicting_legacy_inventory_never_becomes_ready(topology, kind):
    cols = await collections(topology)
    await cols[0].insert_one(document())
    right = document('right', 'right-file', 'right-ref')
    if kind in ('canonical', 'same-shard'): right['file_unique_id'] = 'unique'
    if kind == 'alias': right['file_ref'] = 'ref'
    if kind == 'cross-namespace': right['_id'] = 'unique'
    await cols[0 if kind == 'same-shard' else 1].insert_one(right)
    owners = GlobalMediaOwners(topology)
    assert (await owners.inventory())['eligible'] is False
    with pytest.raises((BulkWriteError, DuplicateKeyError)):
        await owners.activate('conflict')
    with pytest.raises(MediaOwnershipError): await owners.attach()
    assert await total(topology) == 2


@pytest.mark.asyncio
async def test_primary_reorder_topology_changes_and_index_drift_fail_closed(topology):
    owners = GlobalMediaOwners(topology); await owners.activate('topology')
    # Reordering secondaries is safe; changing the coordinator is not.
    await GlobalMediaOwners([topology[0], topology[2], topology[1]]).attach()
    for changed in [list(reversed(topology)), topology[:2]]:
        with pytest.raises(MediaOwnershipError): await GlobalMediaOwners(changed).attach()
        with pytest.raises(MediaOwnershipError): await GlobalMediaOwners(changed).activate('other')
    registry = await owners._registry()
    await registry.drop_index(owners.ALIAS_INDEX)
    with pytest.raises(MediaOwnershipError, match='index'): await owners.attach()


@pytest.mark.asyncio
async def test_competing_primaries_cannot_both_activate(topology):
    left, right = GlobalMediaOwners(topology), GlobalMediaOwners(list(reversed(topology)))
    result = await asyncio.gather(left.activate('left'), right.activate('right'), return_exceptions=True)
    assert sum(isinstance(r, dict) and r.get('ready') for r in result) == 1
    assert sum(isinstance(r, MediaOwnershipError) for r in result) == 1


@pytest.mark.asyncio
async def test_incompatible_canonical_index_is_preserved_and_blocks_activation(topology):
    col = (await collections(topology))[0]
    await col.create_index('file_unique_id', name='legacy_nonunique')
    owners = GlobalMediaOwners(topology)
    with pytest.raises(MediaOwnershipError, match='index'): await owners.activate('index')
    indexes = await col.index_information()
    assert 'legacy_nonunique' in indexes and not indexes['legacy_nonunique'].get('unique')


@pytest.mark.asyncio
async def test_repository_routes_create_lookup_update_delete_through_registry(topology):
    manager = object.__new__(MultiDatabaseManager); manager.__init__()
    manager.databases = topology
    manager.media_owners = GlobalMediaOwners(topology)
    await manager.media_owners.activate('repository')
    manager.get_optimal_write_database = AsyncMock(return_value=topology[1].pool)
    repo = MediaRepository(topology[0].pool, SimpleNamespace(), manager)
    repo.cache_invalidator = SimpleNamespace(invalidate_all_search_results=AsyncMock(),
        invalidate_file_stats=AsyncMock(), invalidate_file_cache=AsyncMock(), invalidate_media_entry=AsyncMock())
    file = MediaFile('unique', 'file', 'ref', 'QA doctor', 10, FileType.VIDEO, 'video/mkv', 'caption')
    assert await repo.save_media(file) == (True, 1, None)
    assert (await repo.save_media(file))[:2] == (False, 0)
    assert (await repo.find_file('ref')).file_unique_id == 'unique'
    assert await repo.update('ref', {'caption': 'new', 'file_ref': 'new-ref'})
    assert (await repo.find_file('new-ref')).caption == 'new'
    assert not await repo.update('absent', {'caption': 'x'}, upsert=True)
    assert await repo.delete('ref') and not await repo.delete('ref')
    assert await total(topology) == 0
    topology[0].is_active = False
    assert (await repo.save_media(file))[:2] == (False, 2)
    assert await repo.delete('ref') is False


def test_source_keys_ignore_credentials_options_and_seed_order():
    assert source_key('mongodb://u:p@b:27017,a/db?retryWrites=true', 'media') == source_key('mongodb://a:27017,b:27017', 'media')
    assert source_key('mongodb+srv://u:p@HOST/x', 'media') == source_key('mongodb+srv://host/', 'media')
    assert source_key('mongodb://a', 'one') != source_key('mongodb://a', 'two')
    for uri, name in [('https://a', 'db'), ('mongodb://', 'db'), ('mongodb://a', '')]:
        with pytest.raises(ValueError): source_key(uri, name)


@pytest.mark.parametrize('doc', [{}, {'file_unique_id': ''}, {'file_unique_id': 1},
    {'file_unique_id': 'u', '_id': 1}, {'file_unique_id': 'u', 'file_ref': []}])
def test_invalid_inventory_identity_rejected_without_logging_values(doc):
    with pytest.raises(MediaOwnershipError): identity_aliases(doc)


@pytest.mark.asyncio
async def test_invalid_activation_and_reservation_inputs(topology):
    with pytest.raises(MediaOwnershipError): GlobalMediaOwners([])
    with pytest.raises(MediaOwnershipError): GlobalMediaOwners([topology[0], topology[0]])
    owners = GlobalMediaOwners(topology)
    for args in [dict(token=''), dict(token=None), dict(token='x'*129),
                 dict(token='ok', max_docs_per_source=0), dict(token='ok', batch_size=True)]:
        with pytest.raises(ValueError): await owners.activate(**args)
    with pytest.raises(ValueError): await owners.inventory(max_docs_per_source=True)
    await owners.activate('valid')
    key = next(iter(owners.sources))
    with pytest.raises(MediaOwnershipError): await owners.reserve('u', [], 'unknown')
    with pytest.raises(MediaOwnershipError): await owners.reserve('u', [''], key)


def test_operator_source_configuration(monkeypatch):
    monkeypatch.setenv('MEDIA_OWNER_SOURCES_JSON', '[{"uri":"mongodb://localhost","name":"qa"}]')
    assert source_configuration()[0]['name'] == 'qa'
    for raw in ['{}', '[]', '[{}]', '[{"uri":"mongodb://localhost","name":1}]']:
        monkeypatch.setenv('MEDIA_OWNER_SOURCES_JSON', raw)
        with pytest.raises(ValueError): source_configuration()
    monkeypatch.delenv('MEDIA_OWNER_SOURCES_JSON')
    monkeypatch.setenv('DATABASE_URI', 'mongodb://localhost'); monkeypatch.setenv('DATABASE_NAME', 'qa')
    monkeypatch.setenv('DATABASE_URIS', 'mongodb://localhost'); monkeypatch.setenv('DATABASE_NAMES', '')
    with pytest.raises(ValueError): source_configuration()
    monkeypatch.setenv('DATABASE_NAMES', 'qa2')
    assert len(source_configuration()) == 2


@pytest.mark.asyncio
async def test_owner_write_conflicts_and_unobservable_results_keep_reservation(topology, monkeypatch):
    owners = GlobalMediaOwners(topology); await owners.activate('write-errors')
    key = next(iter(owners.sources)); original = owners._collection
    class FaultyCollection:
        def __init__(self, fail, exists): self.fail, self.exists = fail, exists
        async def update_one(self, *args, **kwargs):
            if self.fail: raise DuplicateKeyError('simulated owner identity race')
            return SimpleNamespace(upserted_id='file')
        async def find_one(self, *args, **kwargs): return document() if self.exists else None
    for fail, exists in [(True, False), (False, False), (True, True)]:
        async def collection(source, name):
            return FaultyCollection(fail, exists) if name == 'media_files' else await original(source, name)
        monkeypatch.setattr(owners, '_collection', collection)
        if exists:
            assert not (await owners.create(document(), key))[0]
        else:
            with pytest.raises(MediaOwnershipError): await owners.create(document(), key)
        assert (await owners.resolve('unique'))['owner_key'] == key
    assert await total(topology) == 0


@pytest.mark.asyncio
async def test_canonical_reservation_upsert_race_retries_existing_owner(topology, monkeypatch):
    owners = GlobalMediaOwners(topology); await owners.activate('reserve-race')
    keys = list(owners.sources)
    original = owners._registry
    first = await owners.reserve('u', ['alias'], keys[0])
    registry = await original()
    class Race:
        calls = 0
        async def find_one_and_update(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1: raise DuplicateKeyError('canonical upsert race')
            return await registry.find_one_and_update(*args, **kwargs)
    race = Race(); monkeypatch.setattr(owners, '_registry', AsyncMock(return_value=race))
    assert (await owners.reserve('u', ['new-alias'], keys[1]))['owner_key'] == first['owner_key']
    monkeypatch.setattr(owners, '_registry', original)
    await owners.reserve('other', ['other-alias'], keys[1])
    with pytest.raises(MediaOwnershipError): await owners.reserve('u', ['other-alias'], keys[0])


@pytest.mark.asyncio
async def test_lost_activation_lock_cannot_publish_ready(topology, monkeypatch):
    owners = GlobalMediaOwners(topology); original = owners._collection
    class LostLock:
        def __init__(self, wrapped): self.wrapped = wrapped
        def __getattr__(self, name): return getattr(self.wrapped, name)
        async def update_one(self, query, *args, **kwargs):
            if query.get('_id') == 'topology-v1': return SimpleNamespace(modified_count=0)
            return await self.wrapped.update_one(query, *args, **kwargs)
    async def collection(key, name):
        wrapped = await original(key, name)
        return LostLock(wrapped) if name == owners.CONTROL else wrapped
    monkeypatch.setattr(owners, '_collection', collection)
    with pytest.raises(MediaOwnershipError, match='lock'): await owners.activate('lost-lock')
    with pytest.raises(MediaOwnershipError): await owners.attach()


@pytest.mark.asyncio
async def test_operator_apply_status_inventory_and_nullable_alias_update(topology):
    from scripts.activate_media_owners import operate
    sources = [dict(uri=s.uri, name=s.name) for s in topology]
    args = SimpleNamespace(apply=False, status=False, limit=100, activation_token='operator')
    assert (await operate(sources, args))['eligible']
    args.apply = True
    assert (await operate(sources, args))['ready']
    args.apply, args.status = False, True
    assert (await operate(sources, args)) == {'ready': True, 'sources': 3}
    owners = GlobalMediaOwners(topology)
    await owners.create(document(), next(iter(owners.sources)))
    assert await owners.update('unique', {'file_ref': None})
    assert (await owners.find('ref'))['file_ref'] is None


@pytest.mark.parametrize('argv', [[], ['--apply'], ['--limit', '0'], ['--limit', '1000001'],
    ['--apply', '--status'], ['--status']])
def test_operator_cli_validation_never_prints_credentials(monkeypatch, capsys, argv):
    from scripts.activate_media_owners import main
    monkeypatch.setattr('sys.argv', ['activate_media_owners'] + argv)
    monkeypatch.setenv('MEDIA_OWNER_SOURCES_JSON', '[{"uri":"mongodb://sensitive-user:sensitive-password@remote.invalid","name":"qa"}]')
    with pytest.raises(SystemExit) as error: main()
    assert error.value.code != 0
    assert 'sensitive' not in capsys.readouterr().err


def test_operator_cli_success_failure_and_conflict_exit(monkeypatch, capsys):
    from scripts import activate_media_owners as cli
    monkeypatch.setattr('sys.argv', ['activate_media_owners'])
    monkeypatch.setenv('MEDIA_OWNER_SOURCES_JSON', '[{"uri":"mongodb://localhost","name":"qa"}]')
    monkeypatch.setattr(cli, 'operate', AsyncMock(return_value={'eligible': True}))
    cli.main(); assert 'true' in capsys.readouterr().out
    monkeypatch.setattr(cli, 'operate', AsyncMock(return_value={'eligible': False}))
    with pytest.raises(SystemExit) as error: cli.main()
    assert error.value.code == 2
    monkeypatch.setattr(cli, 'operate', AsyncMock(side_effect=ConnectionError('qa-sensitive-credential')))
    with pytest.raises(SystemExit) as error: cli.main()
    assert error.value.code == 1 and 'qa-sensitive-credential' not in capsys.readouterr().err
