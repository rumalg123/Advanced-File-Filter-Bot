import pytest

from bsettings_support import fixture


@pytest.mark.asyncio
@pytest.mark.parametrize('key', ['DATABASE_URI', 'DATABASE_NAME', 'REDIS_URI'])
@pytest.mark.parametrize('action', ['default', 'bool', 'edit'])
async def test_protected_settings_reject_every_callback_mutation(key, action):
    handler, message, query = fixture(key, 'QA protected value', '', 'str')
    query.data = f'bset_{action}_{key}' + ('_true' if action == 'bool' else '')
    await handler.settings_callback(None, query)
    handler.settings_service.update_setting.assert_not_awaited()
    handler.settings_service.reset_to_default.assert_not_awaited()
    handler.session_manager.create_edit_session.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('data', [
    'bset_bool_FEATURE_FAVORITES_maybe', 'bset_bool_CACHE_TIME_true',
    'bset_edit_REMOVED_SETTING', 'bset_page_bad',
])
async def test_invalid_or_removed_controls_cannot_write_or_capture_input(data):
    handler, message, query = fixture()
    query.data = data
    await handler.settings_callback(None, query)
    handler.settings_service.update_setting.assert_not_awaited()
    handler.session_manager.create_edit_session.assert_not_awaited()
    query.answer.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('uid', [2, 3])
@pytest.mark.parametrize('data', [
    'bset_bool_FEATURE_FAVORITES_true', 'bset_edit_CACHE_TIME', 'bset_close',
])
async def test_secondary_admin_and_ordinary_user_cannot_operate_owner_settings(uid, data):
    handler, message, query = fixture()
    query.from_user.id = uid
    query.data = data
    await handler.settings_callback(None, query)
    handler.settings_service.get_all_settings.assert_not_awaited()
    handler.settings_service.update_setting.assert_not_awaited()
    handler.session_manager.create_edit_session.assert_not_awaited()
    message.delete.assert_not_awaited()
    assert 'primary admin' in query.answer.await_args.args[0]
