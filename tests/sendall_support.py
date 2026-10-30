"""Send All ownership, literal queries and confirmed-delivery accounting."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock


from core.utils.quota_calendar import QuotaReservation
from handlers.callbacks_handlers.file import FileCallbackHandler
from repositories.user import User


def fixture(monkeypatch):
    reservation = QuotaReservation(2, date(2026, 10, 30), 'round2-sendall')
    user_repo = SimpleNamespace(
        can_retrieve_file=AsyncMock(return_value=(True, 'allowed')),
        get_user=AsyncMock(return_value=User(id=42, name='QA')),
        reserve_quota_atomic=AsyncMock(return_value=(True, reservation, 'reserved')),
        settle_quota_delivery=AsyncMock(return_value=True))
    media = SimpleNamespace(file_unique_id='one', file_id='qa-file')
    bot = SimpleNamespace(bot_username='testbot', config=SimpleNamespace(
        ADMINS=[1], AUTH_CHANNEL=0, AUTH_GROUPS=[], DISABLE_PREMIUM=False,
        NON_PREMIUM_DAILY_LIMIT=10, MESSAGE_DELETE_SECONDS=0,
        AUTO_DELETE_MESSAGE=None, CUSTOM_FILE_CAPTION=None,
        BATCH_FILE_CAPTION=None, KEEP_ORIGINAL_CAPTION=False), user_repo=user_repo,
        cache=SimpleNamespace(get=AsyncMock(return_value={
            'user_id':42, 'files':[{'file_unique_id':'one'}, {'file_unique_id':'two'}],
            'query':'QA <unknown> & text'})),
        media_repo=SimpleNamespace(find_file=AsyncMock(return_value=media)))
    status = SimpleNamespace(edit_text=AsyncMock())
    client = SimpleNamespace(get_chat=AsyncMock(), send_message=AsyncMock(return_value=status),
                             send_cached_media=AsyncMock(return_value=SimpleNamespace()))
    query = SimpleNamespace(from_user=SimpleNamespace(id=42),
        data='sendall#owned-search#42', answer=AsyncMock())
    monkeypatch.setattr('handlers.callbacks_handlers.file.is_private_chat', lambda _: True)
    monkeypatch.setattr('handlers.callbacks_handlers.file.CaptionFormatter.format_file_caption', lambda **_: 'caption')
    async def invoke(operation, *args, chat_id=None, **kwargs):
        return await operation(*args, **kwargs)
    monkeypatch.setattr('handlers.callbacks_handlers.file.telegram_api.call_api', invoke)
    monkeypatch.setattr('handlers.callbacks_handlers.file.asyncio.sleep', AsyncMock())
    return FileCallbackHandler(bot), client, query, status, reservation


async def run(handler, client, query):
    await FileCallbackHandler.handle_sendall_callback.__wrapped__(handler, client, query)
