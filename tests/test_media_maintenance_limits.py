"""Large operator scan bounds must agree from CLI through database library."""
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest

from core.database.maintenance_limits import MAX_MEDIA_SCAN_DOCUMENTS
from core.database.media_owners import GlobalMediaOwners
from scripts.backfill_search_tokens import backfill


@pytest.mark.parametrize('limit', [500_001, 1_000_001, 10_000_000])
def test_backfill_accepts_large_limits_without_materializing_large_fixtures(limit):
    cursor = MagicMock()
    cursor.batch_size.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.__iter__.return_value = iter([])
    collection = SimpleNamespace(find=Mock(return_value=cursor))
    result = backfill(collection, limit=limit)
    assert result['scanned'] == 0 and result['truncated'] is False
    cursor.batch_size.assert_called_once_with(200)
    cursor.limit.assert_called_once_with(limit + 1)


@pytest.mark.asyncio
@pytest.mark.parametrize('limit', [0, 10_000_001, True, 1.5, None])
async def test_owner_bounds_reject_invalid_input_before_reading_or_binding_sources(limit):
    owners = GlobalMediaOwners([SimpleNamespace(uri='mongodb://localhost', name=name)
                                for name in ['primary', 'secondary']])
    owners._collection = AsyncMock()
    with pytest.raises(ValueError, match='inventory bound'):
        await owners.inventory(max_docs_per_source=limit)
    with pytest.raises(ValueError, match='inventory bound'):
        await owners.activate('qa-bounds', max_docs_per_source=limit)
    owners._collection.assert_not_awaited()


def test_owner_cli_keeps_ten_million_default_and_passes_it_to_operation(monkeypatch):
    from scripts import activate_media_owners as cli
    monkeypatch.setenv('MEDIA_OWNER_SOURCES_JSON',
        '[{"uri":"mongodb://localhost","name":"primary"},'
        '{"uri":"mongodb://localhost","name":"secondary"}]')
    monkeypatch.setattr('sys.argv', ['activate_media_owners', '--apply', '--activation-token', 'qa-bounds'])
    operation = AsyncMock(return_value={'ready': True})
    monkeypatch.setattr(cli, 'operate', operation)
    cli.main()
    assert operation.await_args.args[1].limit == 10_000_000
    assert MAX_MEDIA_SCAN_DOCUMENTS == 10_000_000


def test_backfill_cli_keeps_million_default_and_accepts_explicit_ten_million(monkeypatch):
    from scripts import backfill_search_tokens as cli
    monkeypatch.setenv('DATABASE_URI', 'mongodb://localhost')
    monkeypatch.setenv('DATABASE_NAME', 'qa-bounds')
    monkeypatch.setattr(cli, 'MongoClient', MagicMock())
    operation = Mock(return_value={'scanned': 0})
    monkeypatch.setattr(cli, 'backfill', operation)
    for argv, expected in [([], 1_000_000), (['--limit', '10000000'], 10_000_000)]:
        monkeypatch.setattr('sys.argv', ['backfill_search_tokens', *argv])
        cli.main()
        assert operation.call_args.kwargs['limit'] == expected


@pytest.mark.parametrize('module_name', ['activate_media_owners', 'backfill_search_tokens'])
@pytest.mark.parametrize('limit', ['0', '10000001'])
def test_operator_cli_rejects_out_of_range_limits_before_connecting(monkeypatch, module_name, limit):
    import importlib
    cli = importlib.import_module('scripts.' + module_name)
    name = 'AsyncIOMotorClient' if module_name == 'activate_media_owners' else 'MongoClient'
    connect = Mock()
    monkeypatch.setattr(cli, name, connect)
    monkeypatch.setattr('sys.argv', [module_name, '--limit', limit])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    connect.assert_not_called()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_mongo_inventory_and_cli_activation_accept_new_default():
    from motor.motor_asyncio import AsyncIOMotorClient
    from scripts.activate_media_owners import operate
    from scripts.profile_media_search import is_local

    uri = os.getenv('TEST_MONGO_URI')
    if not uri:
        pytest.skip('Requires disposable local MongoDB')
    assert is_local(uri)
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=3000)
    names = ['qa_scan_' + uuid4().hex for _ in range(2)]

    class Pool:
        def __init__(self, name):
            self.db = client[name]
        async def get_collection(self, name):
            return self.db[name]

    owners = GlobalMediaOwners([SimpleNamespace(uri=uri, name=name, pool=Pool(name), is_active=True)
                               for name in names])
    try:
        for index, name in enumerate(names):
            await client[name].media_files.insert_one({
                '_id': f'file-{index}', 'file_unique_id': f'unique-{index}', 'file_ref': f'ref-{index}'})
        inventory = await owners.inventory()  # Same ten-million default as CLI.
        assert inventory['complete'] and inventory['eligible'] and inventory['documents'] == 2
        sources = [dict(uri=uri, name=name) for name in names]
        result = await operate(sources, SimpleNamespace(status=False, apply=True,
            limit=MAX_MEDIA_SCAN_DOCUMENTS, activation_token='qa-large-limit'))
        assert result['ready'] and result['adopted'] == 2
        assert (await owners.activate('qa-large-limit'))['already_active']
        assert (await operate(sources, SimpleNamespace(status=True)))['ready']
    finally:
        for name in names:
            await client.drop_database(name)
        client.close()
