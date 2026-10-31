"""Small request-handler fixture; no Telegram or database connections."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from handlers.request import RequestHandler


def request_fixture(tracking=True):
    user = SimpleNamespace(id=7, first_name='Alice', username=None, mention='Alice')
    message = SimpleNamespace(id=10, text='#request Missing title', from_user=user,
                              reply_text=AsyncMock())
    repository = SimpleNamespace(
        find_pending_content_request=AsyncMock(return_value=None),
        create_content_request=AsyncMock(return_value=({'query':'Missing title'}, True)),
        update_content_request=AsyncMock(return_value=True),
        get_content_request=AsyncMock(return_value=None),
        claim_content_request_transition=AsyncMock(return_value=True),
        finish_content_request_transition=AsyncMock(return_value=True),
        rollback_content_request_transition=AsyncMock(return_value=True),
    )
    handler = object.__new__(RequestHandler)
    handler._shutdown = asyncio.Event()
    handler.bot = SimpleNamespace(
        config=SimpleNamespace(ADMINS=[1], SUPPORT_GROUP_ID=-1001,
                               REQ_CHANNEL=-1002, LOG_CHANNEL=-1003, MAX_BTN_SIZE=3),
        feature_service=SimpleNamespace(enabled=lambda flag: tracking),
        feature_repo=repository,
        user_repo=SimpleNamespace(track_request=AsyncMock(return_value=(True,'Allowed',False,False))),
        file_service=SimpleNamespace(search_files_with_access_check=AsyncMock(return_value=([],0,0,True,None))),
    )
    handler.search_results_service = SimpleNamespace(send_results=AsyncMock(return_value=True))
    client = SimpleNamespace(send_message=AsyncMock(), get_users=AsyncMock(return_value=user))
    return handler, message, client


def callback_fixture(data='req_action#done#7#10', admin_id=1, tracking=True):
    handler, _, client = request_fixture(tracking)
    handler.bot.feature_repo.get_content_request.return_value={'status':'pending'}
    query = SimpleNamespace(data=data, from_user=SimpleNamespace(id=admin_id),
                            answer=AsyncMock(),
                            message=SimpleNamespace(text='New request', edit_text=AsyncMock(),
                                                    edit_reply_markup=AsyncMock()))
    return handler, query, client


async def direct_api(operation, *args, **kwargs):
    kwargs.pop('chat_id', None)
    return await operation(*args, **kwargs)
