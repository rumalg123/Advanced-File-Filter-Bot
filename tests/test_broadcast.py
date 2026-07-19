from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyrogram import enums

from core.services.broadcast import BroadcastService
from handlers.commands_handlers.admin import AdminCommandHandler


def _broadcast_message(**overrides):
    values = {
        "text": "hello",
        "caption": None,
        "document": None,
        "photo": None,
        "video": None,
        "audio": None,
        "reply_markup": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _admin_bot(**overrides):
    values = {
        "config": SimpleNamespace(ADMINS=[1], LOG_CHANNEL=None),
        "cache": SimpleNamespace(
            get=AsyncMock(return_value=None),
            set=AsyncMock(return_value=True),
            expire=AsyncMock(return_value=True),
        ),
        "cache_invalidator": SimpleNamespace(
            invalidate_broadcast_state=AsyncMock()
        ),
        "app_rate_limiter": SimpleNamespace(
            check_rate_limit=AsyncMock(return_value=(True, None)),
            reset_rate_limit=AsyncMock(),
        ),
        "user_repo": SimpleNamespace(count=AsyncMock(return_value=3)),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_preview_failure_does_not_leave_pending_or_rate_limit():
    bot = _admin_bot()
    handler = AdminCommandHandler(bot)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1),
        id=55,
        reply_to_message=_broadcast_message(),
        reply_text=AsyncMock(side_effect=RuntimeError("preview failed")),
    )

    await handler.broadcast_command(None, message)

    assert getattr(bot, "_pending_broadcast", None) is None
    bot.app_rate_limiter.reset_rate_limit.assert_awaited_once_with(
        1, "broadcast"
    )


@pytest.mark.asyncio
async def test_preview_escapes_source_html_before_storing_pending_state():
    bot = _admin_bot()
    handler = AdminCommandHandler(bot)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1),
        id=56,
        reply_to_message=_broadcast_message(text="<b>Hello & welcome</b>"),
        reply_text=AsyncMock(),
    )

    await handler.broadcast_command(None, message)

    preview = message.reply_text.await_args.args[0]
    assert "&lt;b&gt;Hello &amp; welcome&lt;/b&gt;" in preview
    assert bot._pending_broadcast["message"] is message.reply_to_message


@pytest.mark.asyncio
async def test_confirmation_is_answered_before_delivery_starts():
    events = []

    async def broadcast_to_users(*_args, **kwargs):
        events.append("delivery_started")
        await kwargs["progress_callback"](
            {
                "total": 1,
                "success": 0,
                "blocked": 0,
                "deleted": 0,
                "failed": 0,
            }
        )
        events.append("delivery_finished")
        return {
            "total": 1,
            "success": 1,
            "blocked": 0,
            "deleted": 0,
            "failed": 0,
        }

    async def answer(*_args, **_kwargs):
        events.append("callback_answered")

    async def edit_text(*_args, **_kwargs):
        events.append("message_edited")

    source_message = _broadcast_message()
    bot = _admin_bot(
        broadcast_service=SimpleNamespace(
            broadcast_to_users=broadcast_to_users
        ),
        _pending_broadcast={
            "message": source_message,
            "admin_id": 1,
            "admin_message_id": 55,
        },
    )
    handler = AdminCommandHandler(bot)
    query = SimpleNamespace(
        data="confirm_broadcast",
        from_user=SimpleNamespace(id=1),
        message=SimpleNamespace(edit_text=edit_text),
        answer=answer,
    )

    await handler.handle_broadcast_confirmation(None, query)

    assert events.index("callback_answered") < events.index("delivery_started")
    assert events.count("callback_answered") == 1
    assert bot._pending_broadcast is None


@pytest.mark.asyncio
async def test_stop_broadcast_clears_pending_confirmation():
    bot = _admin_bot(
        _pending_broadcast={
            "message": _broadcast_message(),
            "admin_id": 1,
            "admin_message_id": 55,
        }
    )
    handler = AdminCommandHandler(bot)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1),
        reply_text=AsyncMock(),
    )

    await handler.stop_broadcast_command(None, message)

    assert bot._pending_broadcast is None
    bot.app_rate_limiter.reset_rate_limit.assert_awaited_once_with(
        1, "broadcast"
    )
    assert "Pending broadcast confirmation cancelled" in (
        message.reply_text.await_args.args[0]
    )


@pytest.mark.asyncio
async def test_reset_broadcast_limit_also_clears_pending_confirmation():
    bot = _admin_bot(
        _pending_broadcast={
            "message": _broadcast_message(),
            "admin_id": 1,
            "admin_message_id": 55,
        }
    )
    handler = AdminCommandHandler(bot)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=1),
        reply_text=AsyncMock(),
    )

    await handler.reset_broadcast_limit_command(None, message)

    assert bot._pending_broadcast is None
    assert "Pending confirmation cleared" in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_raw_html_text_is_parsed_for_broadcast(monkeypatch):
    api_call = AsyncMock()
    monkeypatch.setattr(
        "core.services.broadcast.telegram_api.call_api", api_call
    )
    client = SimpleNamespace(send_message=AsyncMock())
    message = _broadcast_message(
        text="<b>Important</b>",
        copy=AsyncMock(),
        reply_markup=object(),
    )
    service = BroadcastService(object(), object(), object())

    status, user_id = await service._send_to_user(client, message, 42)

    assert (status, user_id) == ("success", 42)
    assert api_call.await_args.args[:3] == (
        client.send_message,
        42,
        "<b>Important</b>",
    )
    assert api_call.await_args.kwargs["parse_mode"] == enums.ParseMode.HTML
    message.copy.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_telegram_formatting_uses_message_copy(monkeypatch):
    api_call = AsyncMock()
    monkeypatch.setattr(
        "core.services.broadcast.telegram_api.call_api", api_call
    )
    client = SimpleNamespace(send_message=AsyncMock())
    message = _broadcast_message(
        text="Important",
        entities=[object()],
        copy=AsyncMock(),
    )
    service = BroadcastService(object(), object(), object())

    status, user_id = await service._send_to_user(client, message, 43)

    assert (status, user_id) == ("success", 43)
    assert api_call.await_args.args[:2] == (message.copy, 43)


@pytest.mark.asyncio
async def test_raw_html_media_caption_is_parsed_while_copying(monkeypatch):
    api_call = AsyncMock()
    monkeypatch.setattr(
        "core.services.broadcast.telegram_api.call_api", api_call
    )
    message = _broadcast_message(
        text=None,
        caption="<i>Watch now</i>",
        copy=AsyncMock(),
    )
    service = BroadcastService(object(), object(), object())

    status, user_id = await service._send_to_user(
        SimpleNamespace(send_message=AsyncMock()), message, 44
    )

    assert (status, user_id) == ("success", 44)
    assert api_call.await_args.args[:2] == (message.copy, 44)
    assert api_call.await_args.kwargs["caption"] == "<i>Watch now</i>"
    assert api_call.await_args.kwargs["parse_mode"] == enums.ParseMode.HTML
