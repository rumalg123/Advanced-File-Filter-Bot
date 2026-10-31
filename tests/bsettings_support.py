from types import SimpleNamespace
from unittest.mock import AsyncMock

from handlers.commands_handlers.bot_settings import BotSettingsHandler


def fixture(key='CACHE_TIME', value=600, default=300, kind='int'):
    handler = object.__new__(BotSettingsHandler)
    handler.bot = SimpleNamespace(config=SimpleNamespace(ADMINS=[1, 2]))
    handler.settings_service = SimpleNamespace(
        get_all_settings=AsyncMock(return_value={key: {
            'value': value, 'default': default, 'type': kind,
            'description': 'QA setting',
        }}),
        update_setting=AsyncMock(return_value=True),
        reset_to_default=AsyncMock(return_value=True),
    )
    handler.session_manager = SimpleNamespace(
        create_edit_session=AsyncMock(return_value='qa-edit'),
        get_edit_session=AsyncMock(return_value=None),
        cancel_edit_session=AsyncMock(),
    )
    handler.invalidate_related_caches = AsyncMock()
    message = SimpleNamespace(
        id=10, chat=SimpleNamespace(id=1),
        edit_text=AsyncMock(), reply_text=AsyncMock(), delete=AsyncMock(),
    )
    query = SimpleNamespace(
        from_user=SimpleNamespace(id=1), message=message, answer=AsyncMock(),
    )
    return handler, message, query
