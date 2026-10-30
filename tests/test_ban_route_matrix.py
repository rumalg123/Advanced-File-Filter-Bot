from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import handlers.decorators as decorators
from handlers.callbacks_handlers.user import UserCallbackHandler
from handlers.callbacks_handlers.subscription import SubscriptionCallbackHandler
from handlers.callbacks_handlers.filter import FilterCallBackHandler
from handlers.filestore import FileStoreHandler
from handlers.connection import ConnectionHandler
from handlers.filter import FilterHandler
from handlers.request import RequestHandler
from repositories.user import User,UserStatus

ROUTES=[(UserCallbackHandler,name,'callback') for name in [
    'handle_help_callback','handle_about_callback','handle_stats_callback','handle_plans_callback',
    'handle_start_menu_callback','handle_refresh_recommendations_callback','handle_close_recommendations_callback']]
ROUTES += [(SubscriptionCallbackHandler,'handle_checksub_callback','callback')]
ROUTES += [(FileStoreHandler,name,'message') for name in ['link_command','batch_command','premium_batch_command']]
ROUTES += [(FilterHandler,name,'message') for name in ['add_filter_command','view_filters_command','delete_filter_command','delete_all_command']]
ROUTES += [(ConnectionHandler,name,'message') for name in ['connect_command','disconnect_command','connections_command']]
ROUTES += [(ConnectionHandler,name,'callback') for name in ['delete_group_filters_callback','connection_callback','connection_action_callback','cleanup_connections_callback']]
ROUTES += [(FilterCallBackHandler,name,'callback') for name in ['handle_filter_alert_callback','handle_delall_confirm_callback','handle_delall_cancel_callback']]

ROUTES += [(RequestHandler,'handle_request_message','message')]

@pytest.mark.asyncio
@pytest.mark.parametrize('user_id',[42])
@pytest.mark.parametrize('cls,name,kind',ROUTES,ids=[f'{cls.__name__}.{name}' for cls,name,_ in ROUTES])
async def test_banned_normal_user_cannot_use_old_menus_or_public_routes(monkeypatch,cls,name,kind,user_id):
    class Message:
        def __init__(self):
            self.from_user=SimpleNamespace(id=user_id)
            self.reply_text=AsyncMock()
    class Callback(Message):
        def __init__(self):
            super().__init__();self.answer=AsyncMock();self.data='qa-callback';self.message=self
    monkeypatch.setattr(decorators,'Message',Message)
    monkeypatch.setattr(decorators,'CallbackQuery',Callback)
    handler=object.__new__(cls)
    handler.bot=SimpleNamespace(user_repo=SimpleNamespace(get_user=AsyncMock(return_value=User(
        id=user_id,name='QA',status=UserStatus.BANNED))),
        config=SimpleNamespace(ADMINS=[1],AUTH_CHANNEL=0,AUTH_GROUPS=[]))
    update=Message() if kind=='message' else Callback()
    await getattr(handler,name)(None,update)
    reply=update.reply_text if kind=='message' else update.answer
    reply.assert_awaited_once()
    assert 'banned' in reply.await_args.args[0].lower()
