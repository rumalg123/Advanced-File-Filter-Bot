from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.services.file_access import FileAccessService
from handlers.callbacks_handlers.file import FileCallbackHandler
from handlers.commands_handlers.admin import AdminCommandHandler
from handlers.deeplink import DeepLinkHandler
from repositories.user import User, UserRepository


class MemoryCache:
    async def get(self, _key):
        return None

    async def set(self, _key, _value, expire=None):
        return True

    async def delete(self, _key):
        return True


class CapturingPool:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def execute_with_retry(self, func, *args, **kwargs):
        self.calls.append((func, args, kwargs))
        return self.result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('override_days', 'expected_days'),
    [(None, 30), (100, 100)],
)
async def test_premium_repository_uses_default_or_per_grant_duration(
    monkeypatch, override_days, expected_days
):
    repo = UserRepository(CapturingPool(None), MemoryCache(), premium_duration_days=30)
    user = User(id=42, name='Premium User')
    update = AsyncMock(return_value=True)
    monkeypatch.setattr(repo, 'get_user', AsyncMock(return_value=user))
    monkeypatch.setattr(repo, 'update', update)
    repo.cache_invalidator = SimpleNamespace(
        invalidate_user_data=AsyncMock(),
        invalidate_premium_status=AsyncMock(),
    )

    started_at = datetime.now(UTC)
    if override_days is None:
        success, _message, updated_user = await repo.update_premium_status(
            42, True
        )
    else:
        success, _message, updated_user = await repo.update_premium_status(
            42, True, duration_days=override_days
        )

    assert success is True
    update_data = update.await_args.args[1]
    duration = (
        update_data['premium_expiry_date']
        - update_data['premium_activation_date']
    )
    assert duration == timedelta(days=expected_days)
    assert update_data['premium_activation_date'] >= started_at
    assert updated_user.premium_expiry_date == update_data['premium_expiry_date']


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('duration_token', 'expected_days'),
    [(None, 30), ('100d', 100), ('45D', 45)],
)
async def test_addpremium_accepts_optional_day_override(
    duration_token, expected_days
):
    expiry = datetime.now(UTC) + timedelta(days=expected_days)
    user = User(
        id=42,
        name='Premium User',
        is_premium=True,
        premium_expiry_date=expiry,
    )
    user_repo = SimpleNamespace(
        update_premium_status=AsyncMock(return_value=(True, 'Premium added.', user))
    )
    handler = object.__new__(AdminCommandHandler)
    handler.bot = SimpleNamespace(
        config=SimpleNamespace(PREMIUM_DURATION_DAYS=30, LOG_CHANNEL=0),
        user_repo=user_repo,
        cache_invalidator=SimpleNamespace(invalidate_user_cache=AsyncMock()),
    )
    handler._notify_user = AsyncMock(return_value=True)
    command = ['addpremium', '42']
    if duration_token:
        command.append(duration_token)
    message = SimpleNamespace(
        command=command,
        reply_text=AsyncMock(),
        from_user=SimpleNamespace(mention='Admin'),
    )
    callback = AdminCommandHandler.add_premium_command.__wrapped__

    await callback(handler, SimpleNamespace(), message)

    if duration_token:
        user_repo.update_premium_status.assert_awaited_once_with(
            42, True, duration_days=expected_days
        )
    else:
        user_repo.update_premium_status.assert_awaited_once_with(42, True)
    assert f'Duration:</b> {expected_days} days' in message.reply_text.await_args.args[0]
    assert f'Valid for {expected_days} days' in handler._notify_user.await_args.args[2]


@pytest.mark.asyncio
@pytest.mark.parametrize('duration_token', ['0d', '-1d', '100', '10h', '36501d'])
async def test_addpremium_rejects_invalid_duration_override(duration_token):
    user_repo = SimpleNamespace(update_premium_status=AsyncMock())
    handler = object.__new__(AdminCommandHandler)
    handler.bot = SimpleNamespace(
        config=SimpleNamespace(PREMIUM_DURATION_DAYS=30),
        user_repo=user_repo,
    )
    message = SimpleNamespace(
        command=['addpremium', '42', duration_token],
        reply_text=AsyncMock(),
    )
    callback = AdminCommandHandler.add_premium_command.__wrapped__

    await callback(handler, SimpleNamespace(), message)

    user_repo.update_premium_status.assert_not_awaited()
    assert 'Invalid' in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_file_access_uses_atomic_quota_reservation():
    file = SimpleNamespace(file_id="file-id")
    user = User(id=42, name="user")
    user_repo = SimpleNamespace(
        daily_limit=10,
        can_retrieve_file=AsyncMock(return_value=(True, "allowed")),
        get_user=AsyncMock(return_value=user),
        reserve_quota_atomic=AsyncMock(return_value=(True, 1, "reserved"))
    )
    service = FileAccessService(
        user_repo=user_repo,
        media_repo=SimpleNamespace(find_file=AsyncMock(return_value=file)),
        cache_manager=MemoryCache(),
        rate_limiter=SimpleNamespace(check_rate_limit=AsyncMock(return_value=(True, 0))),
        config=SimpleNamespace(DISABLE_PREMIUM=False, ADMINS=[])
    )

    allowed, _reason, returned_file, reserved = await service.check_and_grant_access(
        42, "ref", owner_id=1
    )

    assert allowed is True
    assert returned_file is file
    assert reserved == 1
    user_repo.reserve_quota_atomic.assert_awaited_once_with(42, 1, 10)


@pytest.mark.asyncio
async def test_quota_repository_uses_one_guarded_update_for_new_and_current_day(monkeypatch):
    pool = CapturingPool({"daily_retrieval_count": 3})
    repo = UserRepository(pool, MemoryCache(), daily_limit=10)
    user = User(
        id=42,
        name="user",
        daily_retrieval_count=2,
        last_retrieval_date=date.today()
    )
    monkeypatch.setattr(repo, "get_user", AsyncMock(return_value=user))
    monkeypatch.setattr(repo, "get_collection", AsyncMock(return_value=SimpleNamespace(find_one_and_update=lambda: None)))

    success, reserved, _message = await repo.reserve_quota_atomic(42, 1, 10)

    assert success is True
    assert reserved == 1
    _func, args, _kwargs = pool.calls[0]
    assert "$or" in args[0]
    assert isinstance(args[1], list)
    assert "$cond" in args[1][0]["$set"]["daily_retrieval_count"]


@pytest.mark.asyncio
async def test_request_tracking_consumes_allowance_with_guarded_pipeline(monkeypatch):
    pool = CapturingPool({"daily_request_count": 1, "warning_count": 0})
    repo = UserRepository(pool, MemoryCache())
    user = User(id=42, name="user")
    monkeypatch.setattr(repo, "get_user", AsyncMock(return_value=user))
    monkeypatch.setattr(
        repo,
        "get_collection",
        AsyncMock(return_value=SimpleNamespace(find_one_and_update=lambda: None))
    )

    allowed, _message, should_ban, _should_log = await repo.track_request(42)

    assert allowed is True
    assert should_ban is False
    _func, args, _kwargs = pool.calls[0]
    assert "$or" in args[0]
    assert isinstance(args[1], list)
    assert "$cond" in args[1][0]["$set"]["daily_request_count"]


@pytest.mark.asyncio
async def test_failed_deep_link_delivery_releases_reserved_quota(monkeypatch):
    file = SimpleNamespace(file_id="file-id", file_name="Movie.mkv")
    release_quota = AsyncMock(return_value=True)
    bot = SimpleNamespace(
        config=SimpleNamespace(
            ADMINS=[1],
            MESSAGE_DELETE_SECONDS=0,
            CUSTOM_FILE_CAPTION=None,
            BATCH_FILE_CAPTION=None,
            KEEP_ORIGINAL_CAPTION=False,
            AUTO_DELETE_MESSAGE=None
        ),
        filestore_service=SimpleNamespace(decode_file_identifier=lambda _value: ("ref", False)),
        file_service=SimpleNamespace(
            check_and_grant_access=AsyncMock(return_value=(True, "allowed", file, 1))
        ),
        user_repo=SimpleNamespace(release_quota=release_quota)
    )
    handler = DeepLinkHandler(bot)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        reply_text=AsyncMock(),
        delete=AsyncMock()
    )
    client = SimpleNamespace(send_cached_media=AsyncMock())

    monkeypatch.setattr("handlers.deeplink.CaptionFormatter.format_file_caption", lambda **_kwargs: "caption")
    monkeypatch.setattr("handlers.deeplink.CaptionFormatter.get_parse_mode", lambda: None)
    monkeypatch.setattr(
        "handlers.deeplink.telegram_api.call_api",
        AsyncMock(side_effect=RuntimeError("Telegram send failed"))
    )

    await handler._send_filestore_file(client, message, "encoded")
    release_quota.assert_awaited_once_with(42, 1)


@pytest.mark.asyncio
async def test_bulk_setup_failure_releases_full_reservation(monkeypatch):
    user = User(id=42, name="user")
    release_quota = AsyncMock(return_value=True)
    bot = SimpleNamespace(
        bot_username="testbot",
        config=SimpleNamespace(
            ADMINS=[1],
            AUTH_CHANNEL=0,
            AUTH_GROUPS=[],
            DISABLE_PREMIUM=False,
            NON_PREMIUM_DAILY_LIMIT=10
        ),
        cache=SimpleNamespace(get=AsyncMock(return_value={
            "files": [{"file_unique_id": "one"}, {"file_unique_id": "two"}],
            "query": "matrix"
        })),
        user_repo=SimpleNamespace(
            can_retrieve_file=AsyncMock(return_value=(True, "allowed")),
            get_user=AsyncMock(return_value=user),
            reserve_quota_atomic=AsyncMock(return_value=(True, 2, "reserved")),
            release_quota=release_quota
        )
    )
    handler = FileCallbackHandler(bot)
    query = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        data="sendall#search-key#42",
        chat=SimpleNamespace(type="private"),
        answer=AsyncMock(side_effect=RuntimeError("callback expired"))
    )
    client = SimpleNamespace(get_chat=AsyncMock())
    monkeypatch.setattr("handlers.callbacks_handlers.file.telegram_api.call_api", AsyncMock())
    monkeypatch.setattr("handlers.callbacks_handlers.file.is_private_chat", lambda _query: True)

    with pytest.raises(RuntimeError, match="callback expired"):
        await FileCallbackHandler.handle_sendall_callback.__wrapped__(handler, client, query)

    release_quota.assert_awaited_once_with(42, 2)


@pytest.mark.asyncio
async def test_premium_batch_uses_validated_status():
    batch_link = SimpleNamespace(
        id="batch-id",
        source_chat_id=-1001,
        from_msg_id=1,
        to_msg_id=2,
        protected=False
    )
    user = User(id=42, name="user", is_premium=True)
    check_access = AsyncMock(return_value=(False, "expired"))
    bot = SimpleNamespace(
        config=SimpleNamespace(DISABLE_PREMIUM=False),
        user_repo=SimpleNamespace(
            get_user=AsyncMock(return_value=user),
            check_and_update_premium_status=AsyncMock(return_value=(False, "expired"))
        ),
        filestore_service=SimpleNamespace(
            get_premium_batch_link=AsyncMock(return_value=batch_link),
            check_premium_batch_access=check_access
        )
    )
    handler = DeepLinkHandler(bot)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        reply_text=AsyncMock()
    )

    await handler._send_premium_batch(SimpleNamespace(), message, "batch-id")

    assert check_access.await_args.args[2] is False
