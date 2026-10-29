"""PH-022 handler fault injection: confirmed and uncertain Telegram responses."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.utils.quota_calendar import QuotaReservation
from handlers.callbacks_handlers.file import FileCallbackHandler
from handlers.deeplink import DeepLinkHandler
from repositories.user import User


def bot_fixture():
    file = SimpleNamespace(
        file_id="tg-file", file_unique_id="unique-file",
        file_name="Movie.mkv", caption=None,
    )
    repo = SimpleNamespace(
        settle_quota_delivery=AsyncMock(return_value=True),
        release_quota=AsyncMock(return_value=True),
    )
    reserved = QuotaReservation(1, date(2026, 10, 29), "stable-token")
    bot = SimpleNamespace(
        config=SimpleNamespace(
            ADMINS=[], AUTH_CHANNEL=0, AUTH_GROUPS=[], DISABLE_PREMIUM=False,
            MESSAGE_DELETE_SECONDS=0, CUSTOM_FILE_CAPTION=None,
            BATCH_FILE_CAPTION=None, KEEP_ORIGINAL_CAPTION=False,
            AUTO_DELETE_MESSAGE=None,
        ),
        bot_username="testbot",
        file_service=SimpleNamespace(
            check_and_grant_access=AsyncMock(
                return_value=(True, "allowed", file, reserved)
            )
        ),
        filestore_service=SimpleNamespace(
            decode_file_identifier=lambda data: ("tg-file", False)
        ),
        user_repo=repo,
    )
    return bot, repo, reserved


@pytest.mark.parametrize("send_success", [False, True])
@pytest.mark.asyncio
async def test_callback_records_sent_or_uncertain_outcome(monkeypatch, send_success):
    bot, repo, reserved = bot_fixture()
    handler = FileCallbackHandler(bot)
    handler._auto_delete_message = AsyncMock()
    handler._feature_file_markup = lambda _file: None
    handler._broken_file_report_markup = lambda _file: None
    query = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        data="file#one#42", chat=SimpleNamespace(type="private"),
        answer=AsyncMock()
    )
    client = SimpleNamespace(get_chat=AsyncMock(), send_cached_media=AsyncMock())

    async def telegram_call(api_func, *_args, **_kwargs):
        if api_func is client.get_chat:
            return SimpleNamespace()
        if api_func is client.send_cached_media and not send_success:
            raise RuntimeError("Telegram send outcome unknown")
        return SimpleNamespace()

    monkeypatch.setattr("handlers.callbacks_handlers.file.telegram_api.call_api", telegram_call)
    monkeypatch.setattr("handlers.callbacks_handlers.file.CaptionFormatter.format_file_caption",
                        lambda **_kwargs: "caption")
    monkeypatch.setattr("handlers.callbacks_handlers.file.CaptionFormatter.get_parse_mode",
                        lambda: None)

    await FileCallbackHandler.handle_file_callback.__wrapped__(handler, client, query)
    repo.settle_quota_delivery.assert_awaited_once_with(
        42, reserved, 1 if send_success else 0, uncertain=not send_success
    )
    repo.release_quota.assert_not_awaited()
    await handler.cancel_pending_tasks()


@pytest.mark.parametrize("send_success", [False, True])
@pytest.mark.asyncio
async def test_single_deeplink_records_delivery_or_ambiguous_send(monkeypatch, send_success):
    bot, repo, reserved = bot_fixture()
    handler = DeepLinkHandler(bot)
    handler._auto_delete_message = AsyncMock()
    client = SimpleNamespace(send_cached_media=AsyncMock())
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        reply_text=AsyncMock(), delete=AsyncMock()
    )
    async def call_api(*_args, **_kw):
        if not send_success:
            raise RuntimeError("Telegram result lost")
        return SimpleNamespace()

    monkeypatch.setattr("handlers.deeplink.telegram_api.call_api", call_api)
    monkeypatch.setattr("handlers.deeplink.CaptionFormatter.format_file_caption",
                        lambda **_kwargs: "caption")
    monkeypatch.setattr("handlers.deeplink.CaptionFormatter.get_parse_mode",
                        lambda: None)
    await handler._send_filestore_file(client, message, "encoded")
    repo.settle_quota_delivery.assert_awaited_once_with(
        42, reserved, 1 if send_success else 0, uncertain=not send_success
    )
    repo.release_quota.assert_not_awaited()


@pytest.mark.asyncio
async def test_deeplink_failure_before_telegram_attempt_refunds_exactly_once(monkeypatch):
    bot, repo, reserved = bot_fixture()
    handler = DeepLinkHandler(bot)
    client = SimpleNamespace(send_cached_media=AsyncMock())
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=42), reply_text=AsyncMock()
    )
    def bad_caption(**_kwargs):
        raise ValueError("invalid caption template")

    monkeypatch.setattr("handlers.deeplink.CaptionFormatter.format_file_caption",
                        bad_caption)
    await handler._send_filestore_file(client, message, "encoded")
    repo.settle_quota_delivery.assert_awaited_once_with(
        42, reserved, 0, uncertain=False
    )
    client.send_cached_media.assert_not_awaited()



@pytest.mark.asyncio
async def test_sendall_setup_failure_closes_tokenized_reservation_once(monkeypatch):
    reservation = QuotaReservation(2, date(2026, 10, 29), "sendall-token")
    repo = SimpleNamespace(
        can_retrieve_file=AsyncMock(return_value=(True, "allowed")),
        get_user=AsyncMock(return_value=User(id=42, name="User")),
        reserve_quota_atomic=AsyncMock(return_value=(True, reservation, "reserved")),
        settle_quota_delivery=AsyncMock(return_value=True),
        release_quota=AsyncMock(return_value=True),
    )
    bot = SimpleNamespace(
        bot_username="testbot",
        config=SimpleNamespace(
            ADMINS=[], AUTH_CHANNEL=0, AUTH_GROUPS=[],
            DISABLE_PREMIUM=False, NON_PREMIUM_DAILY_LIMIT=10
        ),
        cache=SimpleNamespace(get=AsyncMock(return_value={
            "files": [{"file_unique_id": "one"}, {"file_unique_id": "two"}],
            "query": "matrix",
        })),
        user_repo=repo,
    )
    handler = FileCallbackHandler(bot)
    query = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        data="sendall#cached-search#42",
        chat=SimpleNamespace(type="private"),
        answer=AsyncMock(side_effect=RuntimeError("callback no longer valid"))
    )
    client = SimpleNamespace(get_chat=AsyncMock())
    monkeypatch.setattr("handlers.callbacks_handlers.file.is_private_chat",
                        lambda _query: True)
    monkeypatch.setattr("handlers.callbacks_handlers.file.telegram_api.call_api",
                        AsyncMock())

    with pytest.raises(RuntimeError, match="callback no longer valid"):
        await FileCallbackHandler.handle_sendall_callback.__wrapped__(
            handler, client, query
        )
    repo.settle_quota_delivery.assert_awaited_once_with(
        42, reservation, 0, uncertain=False
    )
    repo.release_quota.assert_not_awaited()
