from types import SimpleNamespace
from unittest.mock import AsyncMock

from pyrogram import enums
from pyrogram.types import CallbackQuery, Chat, Message, User

from ban_support import Cache
from handlers.callbacks_handlers.subscription import SubscriptionCallbackHandler
from repositories.user import User as BotUser


def fixture(data='checksub#42#general', *, uid=42, subscribed=True):
    cache = Cache()
    bot = SimpleNamespace(
        config=SimpleNamespace(ADMINS=[1], AUTH_USERS=[], AUTH_CHANNEL=-1001,
            AUTH_GROUPS=[-1002], LOG_CHANNEL=0, INDEX_REQ_CHANNEL=0,
            REQ_CHANNEL=0, DELETE_CHANNEL=0, PICS=[], MESSAGE_DELETE_SECONDS=0),
        user_repo=SimpleNamespace(get_user=AsyncMock(return_value=BotUser(id=uid, name='QA'))),
        subscription_manager=SimpleNamespace(is_subscribed=AsyncMock(return_value=subscribed),
            build_subscription_buttons=AsyncMock(return_value=[])),
        cache=cache, cache_invalidator=SimpleNamespace(
            invalidate_subscription_session=AsyncMock(side_effect=cache.delete)),
        bot_username='qa_subscription_bot', bot_name='QA subscription bot',
    )
    message = Message(id=10, chat=Chat(id=uid, type=enums.ChatType.PRIVATE))
    message.reply_text = AsyncMock()
    message.edit_text = AsyncMock()
    message.edit_reply_markup = AsyncMock()
    message.delete = AsyncMock()
    query = CallbackQuery(id='qa-query', from_user=User(id=uid, first_name='QA', is_bot=False,
        client=SimpleNamespace(parse_mode=enums.ParseMode.HTML)),
        message=message, chat_instance='qa', data=data)
    query.answer = AsyncMock()
    return SubscriptionCallbackHandler(bot), query, cache


async def call_api(operation, *args, chat_id=None, **kwargs):
    return await operation(*args, **kwargs)
