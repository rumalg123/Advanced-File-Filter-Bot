"""Minimal, non-destructive real Telegram smoke checks.

Only run from the protected QA workflow. Both users send /start to the
dedicated QA bot; no group/channel messages, deletes or broadcasts occur.
Expand with carefully scoped feature tests in subsequent PRs.
"""
import asyncio
import os

import pytest
from pyrogram import Client

pytestmark = pytest.mark.telegram_e2e


async def _expect_start_response(client: Client, bot_username: str, bot_id: int) -> None:
    sent = await client.send_message(bot_username, "/start")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 45
    while loop.time() < deadline:
        async for message in client.get_chat_history(bot_username, limit=15):
            if message.id <= sent.id:
                break
            if message.from_user and message.from_user.id == bot_id:
                return
        await asyncio.sleep(2)
    raise AssertionError("The dedicated QA bot did not reply to /start within 45 seconds")


@pytest.mark.asyncio
async def test_admin_and_normal_user_can_reach_qa_bot() -> None:
    api_id = int(os.environ["API_ID"])
    api_hash = os.environ["API_HASH"]
    bot_username = os.environ["QA_BOT_USERNAME"].lstrip("@")
    admin = Client(
        "qa_admin", api_id=api_id, api_hash=api_hash,
        session_string=os.environ["QA_ADMIN_SESSION"], in_memory=True,
    )
    user = Client(
        "qa_normal", api_id=api_id, api_hash=api_hash,
        session_string=os.environ["QA_USER_SESSION"], in_memory=True,
    )

    async with admin, user:
        admin_self, user_self = await asyncio.gather(admin.get_me(), user.get_me())
        assert not admin_self.is_bot and not user_self.is_bot
        assert admin_self.id == int(os.environ["QA_OWNER_ID"])
        assert user_self.id != admin_self.id

        bot_info = await admin.get_users(bot_username)
        assert bot_info.is_bot
        assert bot_info.username.lower() == bot_username.lower()

        # Both dedicated QA identities must be members of the configured group.
        qa_group = int(os.environ["QA_GROUP_ID"])
        admin_group, user_group = await asyncio.gather(
            admin.get_chat(qa_group), user.get_chat(qa_group),
        )
        assert admin_group.id == qa_group and user_group.id == qa_group

        # The two requests are intentionally concurrent to exercise both sessions.
        await asyncio.wait_for(
            asyncio.gather(
                _expect_start_response(admin, bot_username, bot_info.id),
                _expect_start_response(user, bot_username, bot_info.id),
            ),
            timeout=100,
        )
