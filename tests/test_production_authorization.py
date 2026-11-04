"""PH-001: deny banned/unknown users across all file-access routes.

These tests do not touch MongoDB, Redis, or Telegram. The repository's
central can_retrieve_file decision is tested directly and through selected
handler/service entry points. A live integration smoke test is still required.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.services.file_access import FileAccessService
from handlers.callbacks_handlers.file import FileCallbackHandler
from handlers.decorators import check_ban
from handlers.deeplink import DeepLinkHandler
from repositories.user import User, UserRepository, UserStatus


def make_repo(monkeypatch, user, *, premium_disabled=False, admins=(1,)):
    import repositories.user as user_module

    monkeypatch.setattr(
        user_module, "_feature_config",
        SimpleNamespace(disable_premium=premium_disabled),
    )
    monkeypatch.setattr(
        user_module, "_channel_config",
        SimpleNamespace(get_admin_list=lambda: list(admins)),
    )

    repo = UserRepository(None, SimpleNamespace())
    repo.get_user = AsyncMock(return_value=user)
    repo.check_and_update_premium_status = AsyncMock(
        return_value=(False, "Not premium")
    )
    return repo


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("premium_disabled", "user_id", "admins", "owner_id"),
    [
        (True, 42, (), None),
        (False, 42, (), None),
    ],
)
async def test_banned_normal_users_are_denied_in_free_and_premium_modes(
    monkeypatch, premium_disabled, user_id, admins, owner_id
):
    banned = User(
        id=user_id,
        name="Banned",
        status=UserStatus.BANNED,
        ban_reason="Violation",
        is_premium=True,
        premium_expiry_date=datetime.now(UTC) + timedelta(days=30),
    )
    repo = make_repo(
        monkeypatch, banned, premium_disabled=premium_disabled, admins=admins
    )

    allowed, reason = await repo.can_retrieve_file(user_id, owner_id)
    assert allowed is False
    assert "banned" in reason.lower()
    repo.check_and_update_premium_status.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("premium_disabled", [False, True])
@pytest.mark.parametrize(("user_id", "admins", "owner_id"), [
    (42, (), None),
])
async def test_unknown_or_unavailable_user_fails_closed(
    monkeypatch, premium_disabled, user_id, admins, owner_id
):
    repo = make_repo(
        monkeypatch, None, premium_disabled=premium_disabled, admins=admins
    )
    allowed, reason = await repo.can_retrieve_file(user_id, owner_id)
    assert not allowed
    assert "not found" in reason.lower() or "unavailable" in reason.lower()
    repo.check_and_update_premium_status.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("premium_disabled", "admins", "owner_id"), [
    (True, (), None),
    (False, (42,), 1),
    (False, (), 42),
])
async def test_existing_non_banned_exempt_users_keep_access(
    monkeypatch, premium_disabled, admins, owner_id
):
    repo = make_repo(
        monkeypatch,
        User(id=42, name="Allowed", status=UserStatus.ACTIVE),
        premium_disabled=premium_disabled,
        admins=admins,
    )
    allowed, _ = await repo.can_retrieve_file(42, owner_id)
    assert allowed


@pytest.mark.asyncio
async def test_regular_users_keep_daily_limit_enforcement(monkeypatch):
    user = User(
        id=42, name="Regular", daily_retrieval_count=10,
        last_retrieval_date=datetime.now(UTC).date(),
    )
    repo = make_repo(monkeypatch, user, premium_disabled=False, admins=())
    allowed, reason = await repo.can_retrieve_file(42)
    assert not allowed
    assert "limit" in reason.lower()


@pytest.mark.asyncio
async def test_single_file_and_search_early_reject_banned_user(monkeypatch):
    repo = make_repo(
        monkeypatch,
        User(id=42, name="Banned", status=UserStatus.BANNED),
        premium_disabled=True,
    )
    media_repo = SimpleNamespace(
        find_file=AsyncMock(return_value=SimpleNamespace(file_id="id")),
        search_files=AsyncMock(),
    )
    service = FileAccessService(
        user_repo=repo,
        media_repo=media_repo,
        cache_manager=SimpleNamespace(),
        rate_limiter=SimpleNamespace(
            check_rate_limit=AsyncMock(return_value=(True, 0))
        ),
        config=SimpleNamespace(DISABLE_PREMIUM=True, ADMINS=[], USE_CAPTION_FILTER=True),
    )

    allowed, reason, file, reserved = await service.check_and_grant_access(
        42, "file_ref", owner_id=1
    )
    assert not allowed and "banned" in reason.lower()
    assert file is None and reserved == 0

    files, offset, total, has_access, reason = (
        await service.search_files_with_access_check(42, "doctor x", 42)
    )
    assert files == [] and offset == total == 0
    assert not has_access and "banned" in reason.lower()
    media_repo.search_files.assert_not_awaited()


@pytest.mark.asyncio
async def test_banned_admin_keeps_configured_decorator_bypass(monkeypatch):
    # Using a simple callback stub avoids reliance on Telegram's constructors.
    class FakeCallback:
        def __init__(self):
            self.from_user = SimpleNamespace(id=1)
            self.answer = AsyncMock()

    import handlers.decorators as decorators
    monkeypatch.setattr(decorators, "CallbackQuery", FakeCallback)

    user_repo = SimpleNamespace(
        get_user=AsyncMock(return_value=User(
            id=1, name="Banned admin", status=UserStatus.BANNED
        ))
    )
    handler = SimpleNamespace(
        bot=SimpleNamespace(
            user_repo=user_repo,
            config=SimpleNamespace(ADMINS=[1]),
        )
    )
    callback = FakeCallback()
    protected_handler = AsyncMock()

    @check_ban()
    async def protected(self, client, message):
        await protected_handler()

    await protected(handler, None, callback)
    protected_handler.assert_awaited_once()
    callback.answer.assert_not_awaited()
    user_repo.get_user.assert_not_awaited()


@pytest.mark.asyncio
async def test_sendall_callback_ban_gate_precedes_cache_read(monkeypatch):
    # The actual method already uses @check_ban; its decorator must not
    # bypass a banned regular user and enter the cached delivery flow.
    class FakeCallback:
        def __init__(self):
            self.from_user = SimpleNamespace(id=42)
            self.answer = AsyncMock()

    import handlers.decorators as decorators
    monkeypatch.setattr(decorators, "CallbackQuery", FakeCallback)

    user_repo = SimpleNamespace(
        get_user=AsyncMock(return_value=User(
            id=42, name="Banned regular user", status=UserStatus.BANNED
        ))
    )
    cache = SimpleNamespace(get=AsyncMock())
    handler = FileCallbackHandler(
        SimpleNamespace(
            user_repo=user_repo,
            cache=cache,
            config=SimpleNamespace(ADMINS=[1]),
        )
    )

    await handler.handle_sendall_callback(None, FakeCallback())
    cache.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_banned_premium_batch_denied_before_link_access_checks():
    user_repo = SimpleNamespace(
        get_user=AsyncMock(return_value=User(
            id=42, name="Banned", status=UserStatus.BANNED, is_premium=True,
            premium_expiry_date=datetime.now(UTC) + timedelta(days=5)
        )),
        check_and_update_premium_status=AsyncMock(),
    )
    filestore_service = SimpleNamespace(
        get_premium_batch_link=AsyncMock(return_value=SimpleNamespace(
            source_chat_id=-1001,
            from_msg_id=1,
            to_msg_id=5,
            protected=False,
        )),
        check_premium_batch_access=AsyncMock(),
        send_channel_files=AsyncMock(),
    )
    bot = SimpleNamespace(
        user_repo=user_repo,
        filestore_service=filestore_service,
        config=SimpleNamespace(DISABLE_PREMIUM=True),
    )
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        reply_text=AsyncMock(),
    )

    await DeepLinkHandler(bot)._send_premium_batch(None, message, "premium-key")
    message.reply_text.assert_awaited_once()
    user_repo.check_and_update_premium_status.assert_not_awaited()
    filestore_service.check_premium_batch_access.assert_not_awaited()
    filestore_service.send_channel_files.assert_not_awaited()


def test_callback_and_deeplink_file_flows_still_use_central_access():
    """Guard against removing the shared authorization contract later."""
    import inspect
    from handlers.callbacks_handlers.file import FileCallbackHandler
    from handlers.deeplink import DeepLinkHandler

    # The callback entry point performs a central file-access service check.
    assert "check_and_grant_access" in inspect.getsource(
        FileCallbackHandler.handle_file_callback
    )
    # Multi-file paths use the same central UserRepository policy.
    for handler in (
        DeepLinkHandler._send_dstore_files,
        DeepLinkHandler._send_all_from_search,
        DeepLinkHandler._send_batch,
        DeepLinkHandler._send_all_files,
        FileCallbackHandler.handle_sendall_callback,
    ):
        assert "can_retrieve_file" in inspect.getsource(handler)


@pytest.mark.asyncio
@pytest.mark.parametrize('missing',[False,True])
@pytest.mark.parametrize('user_id,admins,owner_id',[(1,(1,),None),(42,(),42)])
async def test_configured_admin_and_explicit_owner_keep_access_bypass(monkeypatch,missing,user_id,admins,owner_id):
    user=None if missing else User(id=user_id,name='Privileged',status=UserStatus.BANNED)
    repo=make_repo(monkeypatch,user,premium_disabled=False,admins=admins)
    allowed,_=await repo.can_retrieve_file(user_id,owner_id)
    assert allowed
    repo.get_user.assert_not_awaited()
