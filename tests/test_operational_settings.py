"""Owner-visible rollout flags, topology locks and pre-routing startup settings."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bot import BotConfig, MediaSearchBot
from config.settings import DatabaseConfig
from core.database.media_owners import GlobalMediaOwners
from core.database.topology import validated_database_sources
from core.services.bot_settings import BotSettingsService
from handlers.commands_handlers.bot_settings import BotSettingsHandler

OWNER = 'DATABASE_GLOBAL_OWNER_REGISTRY'
FLAGS = [OWNER, 'FEATURE_CANONICAL_MEDIA_METADATA', 'FEATURE_QUOTA_DELIVERY_LEDGER',
         'PROCESSING_DURABLE_INDEXING', 'PROCESSING_DURABLE_SAVED_SEARCH_ALERTS']


def database(**overrides):
    values = dict(uri='mongodb://localhost:27017', name='primary', uris='', names='')
    values.update(overrides)
    return DatabaseConfig(_env_file=None, **values)


def settings_service(config=None, controls=None):
    records = {}
    controls = {} if controls is None else controls
    collection = SimpleNamespace(find_one=AsyncMock(side_effect=lambda query: controls.get(query['_id'])))
    pool = SimpleNamespace(get_collection=AsyncMock(return_value=collection))

    async def save(**kwargs):
        records[kwargs['key']] = SimpleNamespace(value=kwargs['value'])
        return True

    async def bulk(items):
        for key, item in items.items():
            records[key] = SimpleNamespace(value=item['value'])
        return True

    repo = SimpleNamespace(db_pool=pool,
        get_setting=AsyncMock(side_effect=records.get),
        get_all_settings=AsyncMock(side_effect=lambda: records.copy()),
        set_setting=AsyncMock(side_effect=save), bulk_upsert=AsyncMock(side_effect=bulk))
    service = BotSettingsService(repo, SimpleNamespace(), database_config=config or database())
    return service, repo, records, controls


def activated_controls(config):
    owners = GlobalMediaOwners([SimpleNamespace(uri=uri, name=name) for uri, name in config.get_sources()])
    return {'binding-v1': {'coordinator': owners.primary, 'source': owners.primary},
            'topology-v1': {'state': 'ready', 'topology': owners.topology}}


@pytest.mark.parametrize('key', FLAGS)
def test_rollout_flags_have_typed_metadata_and_sync_to_their_consumers(key):
    metadata = BotSettingsService.SETTINGS_METADATA[key]
    assert metadata['type'] == 'bool' and metadata['default'] is False
    group, attribute = BotConfig.DB_TO_SETTINGS_MAP[key]
    config = object.__new__(BotConfig)
    config._settings = SimpleNamespace(**{group: SimpleNamespace(**{attribute: False})})
    config._settings.channels = SimpleNamespace(auth_channel='0')
    setattr(config, key, False)
    config.AUTH_CHANNEL = '0'
    config.sync_settings_from_db({key: {'value': True}})
    assert getattr(config, key) is True
    assert getattr(getattr(config._settings, group), attribute) is True


@pytest.mark.asyncio
@pytest.mark.parametrize('key', FLAGS[1:])
async def test_non_owner_flags_can_be_saved_and_reset_with_one_database(key):
    service, repo, records, controls = settings_service()
    assert await service.update_setting(key, 'true')
    assert records[key].value is True
    assert await service.reset_to_default(key)
    assert records[key].value is False


@pytest.mark.asyncio
async def test_initial_environment_values_are_seeded_but_never_overwrite_saved_flags(monkeypatch):
    config = database(uris='mongodb://localhost:27018', names='secondary')
    service, repo, records, controls = settings_service(config)
    for key in FLAGS:
        monkeypatch.setenv(key, 'true')
    await service.initialize_settings()
    for key in FLAGS:
        assert records[key].value is True
        records[key].value = False
    repo.bulk_upsert.reset_mock()
    await service.initialize_settings()
    repo.bulk_upsert.assert_not_awaited()
    for key in FLAGS:
        assert (await service.get_all_settings())[key]['value'] is False


@pytest.mark.parametrize('overrides', [
    {},
    {'uris': 'not-a-mongo-uri', 'names': 'secondary'},
    {'uris': 'mongodb://localhost:27017', 'names': 'primary'},
    {'uris': 'mongodb://localhost:27017/?retryWrites=true', 'names': 'primary'},
    {'uris': 'mongodb://localhost:bad-port', 'names': 'secondary'},
    {'uris': 'mongodb+srv://cluster.example.invalid:27017', 'names': 'secondary'},
    {'uris': 'mongodb://localhost:27018', 'names': 'bad/name'},
    {'uris': '', 'names': 'orphan'},
])
@pytest.mark.asyncio
async def test_single_duplicate_or_invalid_sources_lock_all_owner_write_paths(overrides):
    service, repo, records, controls = settings_service(database(**overrides))
    item = (await service.get_all_settings())[OWNER]
    assert item['editable'] is False
    assert item['default'] is False
    for value in [True, False]:
        with pytest.raises(ValueError):
            await service.update_setting(OWNER, value)
    with pytest.raises(ValueError):
        await service.reset_to_default(OWNER)
    assert await service.import_settings({OWNER: {'value': True}}) == (0, 1)
    repo.set_setting.assert_not_awaited()


def test_valid_srv_configuration_is_checked_without_dns_or_network():
    config = database(uri='mongodb+srv://qa:fixture@first.example.invalid',
        uris='mongodb+srv://qa:fixture@second.example.invalid', names='secondary')
    assert len(validated_database_sources(config)) == 2


@pytest.mark.asyncio
async def test_multiple_sources_allow_staging_enablement_and_explain_activation_before_restart():
    service, repo, records, controls = settings_service(database(uris='mongodb://localhost:27018'))
    item = (await service.get_all_settings())[OWNER]
    assert item['editable'] is True and item['default'] is False
    assert 'activate ownership before restarting' in item['edit_note']
    assert await service.update_setting(OWNER, True)
    assert records[OWNER].value is True
    # A setting write must never activate ownership or create bindings.
    assert controls == {}
    assert await service.reset_to_default(OWNER)
    assert records[OWNER].value is False


@pytest.mark.asyncio
async def test_ready_topology_recommends_true_and_blocks_disabling_or_reset_bypass():
    config = database(uris='mongodb://localhost:27018', names='secondary')
    service, repo, records, controls = settings_service(config, activated_controls(config))
    await service.initialize_settings()
    assert records[OWNER].value is True  # Missing setting inherits recommended default.
    item = (await service.get_all_settings())[OWNER]
    assert item['editable'] is True and item['default'] is True
    with pytest.raises(ValueError, match='cannot be disabled'):
        await service.update_setting(OWNER, False)
    assert await service.reset_to_default(OWNER)
    assert records[OWNER].value is True
    assert await service.import_settings({OWNER: {'value': False}}) == (0, 1)


@pytest.mark.asyncio
async def test_activation_read_failure_locks_edits_without_exposing_uri():
    service, repo, records, controls = settings_service(database(uris='mongodb://localhost:27018'))
    repo.db_pool.get_collection.side_effect = RuntimeError('mongodb://SECRET:password@private')
    item = (await service.get_all_settings())[OWNER]
    assert item['editable'] is False
    assert 'SECRET' not in item['edit_note']
    with pytest.raises(ValueError, match='Cannot verify'):
        await service.update_setting(OWNER, True)
    repo.set_setting.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('key', FLAGS)
async def test_menu_renders_new_flags_and_stays_within_telegram_callback_limit(key):
    config = database(uris='mongodb://localhost:27018')
    service, repo, records, controls = settings_service(config)
    handler = object.__new__(BotSettingsHandler)
    handler.settings_service = service
    message = SimpleNamespace(edit_text=AsyncMock())
    await handler.show_setting_details(message, key)
    keyboard = message.edit_text.await_args.kwargs['reply_markup'].inline_keyboard
    callbacks = [button.callback_data for row in keyboard for button in row]
    assert any(data == f'bset_bool_{key}_true' for data in callbacks)
    assert all(len(data.encode('utf-8')) <= 64 for data in callbacks)


@pytest.mark.asyncio
async def test_locked_registry_has_no_edit_controls_and_forged_callback_is_rejected():
    service, repo, records, controls = settings_service()
    handler = object.__new__(BotSettingsHandler)
    handler.settings_service = service
    handler.bot = SimpleNamespace(config=SimpleNamespace(ADMINS=[1]))
    handler.invalidate_related_caches = AsyncMock()
    message = SimpleNamespace(edit_text=AsyncMock(), reply_text=AsyncMock())
    await handler.show_setting_details(message, OWNER)
    markup = message.edit_text.await_args.kwargs['reply_markup']
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert callbacks == ['bset_back', 'bset_close']
    assert 'at least two' in message.edit_text.await_args.args[0]
    for data in [f'bset_bool_{OWNER}_true', f'bset_default_{OWNER}', f'bset_edit_{OWNER}']:
        query = SimpleNamespace(from_user=SimpleNamespace(id=1), data=data,
                                answer=AsyncMock(), message=message)
        await handler.settings_callback(None, query)
    repo.set_setting.assert_not_awaited()
    handler.invalidate_related_caches.assert_not_awaited()


def storage_fixture(monkeypatch, *, multiple=True, stored=True, bound=False):
    import bot as module
    config = SimpleNamespace(
        DATABASE_URI='mongodb://primary', DATABASE_NAME='primary',
        DATABASE_URIS=['mongodb://primary', 'mongodb://secondary'], DATABASE_NAMES=['primary', 'secondary'],
        DATABASE_SIZE_LIMIT_GB=.5, DATABASE_AUTO_SWITCH=True,
        DATABASE_MAX_FAILURES=5, DATABASE_RECOVERY_TIMEOUT=30, DATABASE_HALF_OPEN_CALLS=2,
        DATABASE_GLOBAL_OWNER_REGISTRY=not stored, is_multi_database_enabled=multiple,
        _settings=SimpleNamespace(database=database()))
    config.sync_settings_from_db = Mock(side_effect=lambda items: setattr(
        config, OWNER, items[OWNER]['value']))
    service = SimpleNamespace(initialize_settings=AsyncMock(),
        get_all_settings=AsyncMock(return_value={OWNER: {'value': stored}}))
    monkeypatch.setattr(module, 'BotSettingsRepository', Mock())
    monkeypatch.setattr(module, 'BotSettingsService', Mock(return_value=service))
    manager = SimpleNamespace(initialize=AsyncMock(), apply_runtime_settings=Mock())
    monkeypatch.setattr(module, 'MultiDatabaseManager', Mock(return_value=manager))
    pool = SimpleNamespace(initialize=AsyncMock(), get_collection=AsyncMock(return_value=
        SimpleNamespace(find_one=AsyncMock(return_value={'source': 'fixture'} if bound else None))))
    instance = SimpleNamespace(config=config, db_pool=pool,
                               cache=SimpleNamespace(initialize=AsyncMock()), multi_db_manager=None)
    return instance, manager, service


@pytest.mark.asyncio
@pytest.mark.parametrize('stored', [False, True])
async def test_startup_uses_saved_owner_flag_before_constructing_multi_database_routes(monkeypatch, stored):
    instance, manager, service = storage_fixture(monkeypatch, stored=stored)

    async def initialize(*args, **kwargs):
        service.get_all_settings.assert_awaited_once()
        instance.config.sync_settings_from_db.assert_called_once()
        assert kwargs['global_owner_registry'] is stored

    manager.initialize.side_effect = initialize
    await MediaSearchBot._initialize_storage(instance)
    manager.initialize.assert_awaited_once()
    instance.db_pool.initialize.assert_awaited_once_with('mongodb://primary', 'primary')


@pytest.mark.asyncio
@pytest.mark.parametrize('multiple,stored,bound,error', [
    (False, True, False, 'complete multi-database topology'),
    (False, False, True, 'activated media ownership'),
    (True, False, True, 'activated media ownership'),
])
async def test_startup_retains_fail_closed_ownership_guards(monkeypatch, multiple, stored, bound, error):
    instance, manager, service = storage_fixture(monkeypatch, multiple=multiple, stored=stored, bound=bound)
    with pytest.raises(RuntimeError, match=error):
        await MediaSearchBot._initialize_storage(instance)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mongo_settings_survive_restart_and_activate_owner_routing_from_saved_flag(monkeypatch):
    """Real settings persistence plus real activation/attach on disposable names."""
    import os
    from uuid import uuid4
    from motor.motor_asyncio import AsyncIOMotorClient
    import bot as module
    from config.settings import FeatureConfig, ProcessingLimitsConfig
    from core.database.multi_pool import MultiDatabaseManager
    from scripts.profile_media_search import is_local

    uri = os.getenv('TEST_MONGO_URI')
    if not uri:
        pytest.skip('Requires disposable local MongoDB')
    assert is_local(uri)
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=3000)
    names = ['qa_bsettings_' + uuid4().hex for _ in range(2)]

    class Pool:
        def __init__(self, name):
            self.db = client[name]
        async def initialize(self, *_args):
            await self.db.command('ping')
        async def get_collection(self, name):
            return self.db[name]
        async def execute_with_retry(self, operation, *args, **kwargs):
            return await operation(*args, **kwargs)

    def config():
        database_config = database(uri=uri, name=names[0], uris=uri, names=names[1])
        result = object.__new__(BotConfig)
        result._settings = SimpleNamespace(database=database_config,
            features=FeatureConfig(_env_file=None), processing=ProcessingLimitsConfig(_env_file=None),
            channels=SimpleNamespace(auth_channel='0'))
        result.DATABASE_URI, result.DATABASE_NAME = uri, names[0]
        result.DATABASE_URIS = [uri, uri]
        result.DATABASE_NAMES = names
        result.DATABASE_SIZE_LIMIT_GB = .5
        result.DATABASE_AUTO_SWITCH = True
        result.DATABASE_MAX_FAILURES = 5
        result.DATABASE_RECOVERY_TIMEOUT = 30
        result.DATABASE_HALF_OPEN_CALLS = 2
        for key in FLAGS:
            setattr(result, key, False)  # Simulate unchanged false environment defaults.
        return result

    managers = []
    def manager_factory():
        manager = object.__new__(MultiDatabaseManager)
        manager.__init__()
        managers.append(manager)
        return manager

    monkeypatch.setattr(module, 'MultiDatabaseManager', manager_factory)
    def instance():
        cache = SimpleNamespace(initialize=AsyncMock(), get=AsyncMock(return_value=None),
                                set=AsyncMock(return_value=True), delete=AsyncMock(return_value=True))
        return SimpleNamespace(config=config(), db_pool=Pool(names[0]), cache=cache, multi_db_manager=None)

    try:
        first = instance()
        await MediaSearchBot._initialize_storage(first)
        assert first.multi_db_manager.media_owners is None
        for key in FLAGS:
            assert await first.bot_settings_service.update_setting(key, True)
            assert (await client[names[0]].bot_settings.find_one({'_id': key}))['value'] is True
        assert await client[names[0]].media_owner_control.count_documents({}) == 0
        await first.multi_db_manager.close()

        owners = GlobalMediaOwners([SimpleNamespace(uri=uri, name=name, pool=Pool(name), is_active=True)
                                   for name in names])
        assert (await owners.activate('qa-bsettings-activation'))['ready']

        second = instance()
        await MediaSearchBot._initialize_storage(second)
        assert second.multi_db_manager.media_owners is not None
        for key in FLAGS:
            assert getattr(second.config, key) is True
            group, attribute = BotConfig.DB_TO_SETTINGS_MAP[key]
            assert getattr(getattr(second.config._settings, group), attribute) is True
        assert (await second.bot_settings_service.get_all_settings())[OWNER]['default'] is True
        with pytest.raises(ValueError, match='cannot be disabled'):
            await second.bot_settings_service.update_setting(OWNER, False)
    finally:
        for manager in managers:
            await manager.close()
        for name in names:
            await client.drop_database(name)
        client.close()
