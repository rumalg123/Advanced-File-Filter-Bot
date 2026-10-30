from typing import Optional, Dict, Any, List
from uuid import uuid4
from datetime import UTC, datetime, timedelta

from pyrogram import Client, enums
from pyrogram.errors import UserNotParticipant, ChatAdminRequired
from pyrogram.types import InlineKeyboardButton

from core.utils.button_builder import ButtonBuilder
from core.cache.config import CacheKeyGenerator, CacheTTLConfig
from core.utils.logger import get_logger
from core.utils.telegram_api import telegram_api
from core.utils.subscription_config import parse_subscription_targets

logger = get_logger(__name__)


class SubscriptionManager:
    """Manages force subscription functionality"""

    def __init__(self, auth_channel=None, auth_groups=None, cache_manager=None,
                 invite_expire_minutes: int = 15, invite_member_limit: int = 1):
        self.auth_channels = parse_subscription_targets(auth_channel)
        self.auth_channel = self.auth_channels[0] if self.auth_channels else None
        self.auth_groups = parse_subscription_targets(auth_groups)
        self.cache = cache_manager
        if type(invite_expire_minutes) is not int or not 1 <= invite_expire_minutes <= 525600:
            raise ValueError('Invite expiry must be between 1 and 525600 minutes.')
        if type(invite_member_limit) is not int or not 1 <= invite_member_limit <= 99999:
            raise ValueError('Invite member limit must be between 1 and 99999.')
        self.invite_expire_minutes = invite_expire_minutes
        self.invite_member_limit = invite_member_limit

    @staticmethod
    async def inspect_chat(client: Client, target, expected_type=None):
        """Read the actual bot role; never create a probe link or write settings."""
        try:
            chat = await telegram_api.call_api(client.get_chat, target, chat_id=target)
        except Exception as error:
            logger.error("Cannot inspect force-subscription chat %s: %s", target, error, exc_info=True)
            raise ValueError(f'Cannot access chat {target}. Add the bot as an administrator with Invite Users permission.') from error
        allowed = ({enums.ChatType.CHANNEL} if expected_type == 'channel' else
                   {enums.ChatType.GROUP, enums.ChatType.SUPERGROUP} if expected_type == 'group' else
                   {enums.ChatType.CHANNEL, enums.ChatType.GROUP, enums.ChatType.SUPERGROUP})
        if chat.type not in allowed:
            raise ValueError(f'Chat {target} is not a valid force-subscription {expected_type or "channel/group"}.')
        try:
            member = await telegram_api.call_api(client.get_chat_member, chat.id, 'me', chat_id=chat.id)
        except Exception as error:
            logger.error("Cannot verify bot permissions in chat %s: %s", target, error, exc_info=True)
            raise ValueError(f'Cannot verify bot permissions in chat {target}. Add it as an administrator with Invite Users permission.') from error
        if member.status not in {enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER}:
            raise ValueError(f'Bot is not an administrator in chat {target}. Grant admin and Invite Users permission before saving.')
        if member.status != enums.ChatMemberStatus.OWNER and getattr(
            getattr(member, 'privileges', None), 'can_invite_users', False
        ) is not True:
            raise ValueError(f'Bot is missing Invite Users permission in chat {target}. Enable it before saving.')
        return chat

    @classmethod
    async def validate_targets(cls, client, targets, *, expected_type):
        resolved = []
        for target in parse_subscription_targets(targets):
            chat = await cls.inspect_chat(client, target, expected_type)
            if chat.id not in resolved:
                resolved.append(chat.id)
        return resolved

    async def _is_user_member(self, client, chat_id, user_id):
        try:
            member = await telegram_api.call_api(client.get_chat_member, chat_id, user_id, chat_id=chat_id)
            return self._is_current_member(member)
        except UserNotParticipant:
            return False
        except Exception as error:
            logger.error("Cannot check subscription for chat %s: %s", chat_id, error, exc_info=True)
            return False

    @staticmethod
    def _is_current_member(member) -> bool:
        if member.status == enums.ChatMemberStatus.RESTRICTED:
            return getattr(member, 'is_member', None) is True
        return member.status in {
            enums.ChatMemberStatus.OWNER,
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.MEMBER,
        }

    async def is_subscribed(
            self,
            client: Client,
            user_id: int,
            check_channel: bool = True,
            check_groups: bool = True
    ) -> bool:
        """
        Check if user is subscribed to required channel/groups

        Args:
            client: Pyrogram client
            user_id: User ID to check
            check_channel: Whether to check AUTH_CHANNEL
            check_groups: Whether to check AUTH_GROUPS

        Returns:
            bool: True if subscribed to all required channels/groups
        """
        try:
            # Check AUTH_CHANNEL
            if check_channel and self.auth_channels:
                for auth_channel in self.auth_channels:
                    try:
                        member = await telegram_api.call_api(
                            client.get_chat_member,
                            auth_channel,
                            user_id,
                            chat_id=auth_channel
                        )
                        if not self._is_current_member(member):
                            return False
                    except UserNotParticipant:
                        return False
                    except Exception as e:
                        error_msg = str(e).lower()
                        if "channel_private" in error_msg or "chat not found" in error_msg:
                            # An inaccessible required chat cannot prove membership.
                            logger.error(f"Bot cannot access AUTH_CHANNEL {auth_channel}: {e}")
                            # You might want to notify admins here
                            return False
                        else:
                            logger.error(f"Error checking channel subscription: {e}")
                            return False
            # Check AUTH_GROUPS
            if check_groups and self.auth_groups:
                for group_id in self.auth_groups:
                    try:
                        member = await telegram_api.call_api(
                            client.get_chat_member,
                            group_id,
                            user_id,
                            chat_id=group_id
                        )
                        if not self._is_current_member(member):
                            return False
                    except UserNotParticipant:
                        return False
                    except Exception as e:
                        error_msg = str(e).lower()
                        if "channel_private" in error_msg or "chat not found" in error_msg:
                            logger.error(f"Bot cannot access AUTH_GROUP {group_id}: {e}")
                            return False
                        else:
                            logger.error(f"Error checking group {group_id} subscription: {e}")
                            return False

            return True

        except Exception as e:
            logger.error(f"Error in subscription check: {e}")
            return False

    async def get_invite_link(self, client: Client, chat_id, *, verified_chat=None) -> Optional[str]:
        """Get invite link for a chat"""
        try:
            if verified_chat is None:
                verified_chat = await self.inspect_chat(client, chat_id)
            # Try to create invite link
            invite = await telegram_api.call_api(
                client.create_chat_invite_link,
                verified_chat.id,
                name='Force subscription',
                expire_date=datetime.now(UTC) + timedelta(minutes=self.invite_expire_minutes),
                member_limit=self.invite_member_limit,
                creates_join_request=False,
                chat_id=chat_id
            )
            return invite.invite_link
        except ChatAdminRequired:
            logger.error(f"Bot is not admin in chat {chat_id}")
            return None
        except Exception as e:
            logger.error(f"Error creating invite link for {chat_id}: {e}")
            return None

    async def get_chat_link(self, client: Client, chat_id, *, verified_chat=None) -> Optional[str]:
        """Always use a limited invite, including for public chats."""
        try:
            invite_link = await self.get_invite_link(client, chat_id, verified_chat=verified_chat)
            return invite_link

        except Exception as e:
            logger.error(f"Error getting chat link for {chat_id}: {e}")
            return None

    async def build_subscription_buttons(
        self,
        client: Client,
        user_id: int,
        callback_type: str = "general",
        extra_data: Optional[str] = None,
        session_key: Optional[str] = None,
        custom_callback_data: Optional[str] = None
    ) -> List[List[InlineKeyboardButton]]:
        """
        Build subscription button list for force subscribe prompts.

        This consolidates the duplicate button-building logic from:
        - handlers/decorators.py
        - handlers/commands_handlers/user.py
        - handlers/callbacks_handlers/file.py

        Args:
            client: Pyrogram client
            user_id: User requesting access
            callback_type: Type of callback ('general', 'deeplink', 'file', 'sendall', 'search')
            extra_data: Additional data for callback (file_identifier, search_key, etc.)
            session_key: Session key for deeplink caching (optional)

        Returns:
            List of button rows for InlineKeyboardMarkup
        """
        buttons = []

        # AUTH_CHANNEL button
        for auth_channel in self.auth_channels:
            try:
                if await self._is_user_member(client, auth_channel, user_id):
                    continue
                chat = await self.inspect_chat(client, auth_channel, 'channel')
                chat_link = await self.get_chat_link(client, auth_channel, verified_chat=chat)
                try:
                    channel_name = chat.title or "Updates Channel"
                except Exception as e:
                    logger.error(f"Error fetching channel details for {auth_channel}: {e}")
                    channel_name = "Updates Channel"

                if chat_link:
                    buttons.append([
                        ButtonBuilder.action_button(
                            f"📢 Join {channel_name}",
                            url=chat_link
                        )
                    ])
            except Exception as e:
                logger.error(f"Error creating AUTH_CHANNEL button: {e}")

        # AUTH_GROUPS buttons
        for group_id in self.auth_groups:
            try:
                if await self._is_user_member(client, group_id, user_id):
                    continue
                chat = await self.inspect_chat(client, group_id, 'group')
                chat_link = await self.get_chat_link(client, group_id, verified_chat=chat)
                try:
                    group_name = chat.title or "Required Group"
                except Exception as e:
                    logger.error(f"Error fetching group details for {group_id}: {e}")
                    group_name = "Required Group"

                if chat_link:
                    buttons.append([
                        ButtonBuilder.action_button(
                            f"👥 Join {group_name}",
                            url=chat_link
                        )
                    ])
            except Exception as e:
                logger.error(f"Error creating AUTH_GROUP button for {group_id}: {e}")

        # Build Try Again callback data
        if custom_callback_data:
            callback_data = custom_callback_data
        elif callback_type == "deeplink" and session_key:
            callback_data = f"checksub#dl#{session_key}"
        elif callback_type == "file" and extra_data:
            callback_data = f"checksub#{user_id}#file#{extra_data}"
        elif callback_type == "sendall" and extra_data:
            callback_data = f"checksub#{user_id}#sendall#{extra_data}"
        elif callback_type == "search":
            callback_data = f"checksub#{user_id}#search"
        else:
            callback_data = f"checksub#{user_id}#general"

        if len(callback_data.encode('utf-8')) > 64:
            original = callback_data.split('#', 2)
            stored = False
            if self.cache and len(original) == 3 and original[:2] == ['checksub', str(user_id)]:
                key = CacheKeyGenerator.subscription_session(uuid4().hex[:16])
                try:
                    stored = await self.cache.set(
                        key, {'user_id': user_id, 'deeplink': original[2]},
                        expire=CacheTTLConfig.USER_DATA
                    )
                except Exception:
                    logger.warning("Could not store subscription retry action", exc_info=True)
                if stored:
                    callback_data = f"checksub#dl#{key}"
            if not stored:
                # Membership can still be checked; repeat the original action
                # after joining when operational state cannot be stored.
                callback_data = f"checksub#{user_id}#general"

        buttons.append([
            ButtonBuilder.action_button("🔄 Try Again", callback_data=callback_data)
        ])

        return buttons

    async def check_auth_channels_accessibility(self, client: Client) -> Dict[str, Any]:
        """Check if bot can access AUTH_CHANNEL and AUTH_GROUPS"""
        results = {
            'accessible': True,
            'errors': []
        }

        for kind, targets, expected in [
            ('AUTH_CHANNEL', self.auth_channels, 'channel'),
            ('AUTH_GROUP', self.auth_groups, 'group'),
        ]:
            for target in targets:
                try:
                    await self.inspect_chat(client, target, expected)
                except ValueError as error:
                    results['accessible'] = False
                    results['errors'].append({'type': kind, 'id': target, 'error': str(error)})
        return results
