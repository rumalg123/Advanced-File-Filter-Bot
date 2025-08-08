
from typing import Optional, Union, Dict, Any

from pyrogram import Client, enums
from pyrogram.errors import UserNotParticipant, ChatAdminRequired
from pyrogram.types import Message, CallbackQuery, InlineQuery

from core.utils.logger import get_logger
logger = get_logger(__name__)


class SubscriptionManager:
    """Manages force subscription functionality"""

    def __init__(self, auth_channel: Optional[int] = None, auth_groups: Optional[list] = None):
        self.auth_channel = auth_channel
        self.auth_groups = auth_groups or []

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
            if check_channel and self.auth_channel:
                try:
                    member = await client.get_chat_member(self.auth_channel, user_id)
                    if member.status == enums.ChatMemberStatus.BANNED:
                        return False
                    # If user is left/kicked, they're not subscribed
                    if member.status in [
                        enums.ChatMemberStatus.LEFT,
                        enums.ChatMemberStatus.RESTRICTED
                    ]:
                        return False
                except UserNotParticipant:
                    return False
                except Exception as e:
                    error_msg = str(e).lower()
                    if "channel_private" in error_msg or "chat not found" in error_msg:
                        # If bot can't access channel, log error but don't block user
                        logger.error(f"Bot cannot access AUTH_CHANNEL {self.auth_channel}: {e}")
                        # You might want to notify admins here
                        return True  # Allow access if bot can't verify
                    else:
                        logger.error(f"Error checking channel subscription: {e}")
                        return False

            # Check AUTH_GROUPS
            if check_groups and self.auth_groups:
                for group_id in self.auth_groups:
                    try:
                        member = await client.get_chat_member(group_id, user_id)
                        if member.status in [
                            enums.ChatMemberStatus.BANNED,
                            enums.ChatMemberStatus.LEFT,
                            enums.ChatMemberStatus.RESTRICTED
                        ]:
                            return False
                    except UserNotParticipant:
                        return False
                    except Exception as e:
                        error_msg = str(e).lower()
                        if "channel_private" in error_msg or "chat not found" in error_msg:
                            logger.error(f"Bot cannot access AUTH_GROUP {group_id}: {e}")
                            continue  # Skip this group if bot can't access
                        else:
                            logger.error(f"Error checking group {group_id} subscription: {e}")
                            return False

            return True

        except Exception as e:
            logger.error(f"Error in subscription check: {e}")
            return False

    async def get_invite_link(self, client: Client, chat_id: int) -> Optional[str]:
        """Get invite link for a chat"""
        try:
            # Try to create invite link
            invite = await client.create_chat_invite_link(chat_id)
            return invite.invite_link
        except ChatAdminRequired:
            logger.error(f"Bot is not admin in chat {chat_id}")
            return None
        except Exception as e:
            logger.error(f"Error creating invite link for {chat_id}: {e}")
            return None

    async def get_chat_link(self, client: Client, chat_id: int) -> str:
        """Get chat link (invite link or @username)"""
        try:
            chat = await client.get_chat(chat_id)

            # If chat has username, return t.me link
            if chat.username:
                return f"https://t.me/{chat.username}"

            # Otherwise, get invite link
            invite_link = await self.get_invite_link(client, chat_id)
            return invite_link or f"Chat ID: {chat_id}"

        except Exception as e:
            logger.error(f"Error getting chat link for {chat_id}: {e}")
            return f"Chat ID: {chat_id}"

    async def check_auth_channels_accessibility(self, client: Client) -> Dict[str, Any]:
        """Check if bot can access AUTH_CHANNEL and AUTH_GROUPS"""
        results = {
            'accessible': True,
            'errors': []
        }

        # Check AUTH_CHANNEL
        if self.auth_channel:
            try:
                chat = await client.get_chat(self.auth_channel)
                # Try to get bot's member status
                try:
                    member = await client.get_chat_member(self.auth_channel, "me")
                    if member.status not in [
                        enums.ChatMemberStatus.ADMINISTRATOR,
                        enums.ChatMemberStatus.MEMBER
                    ]:
                        results['accessible'] = False
                        results['errors'].append({
                            'type': 'AUTH_CHANNEL',
                            'id': self.auth_channel,
                            'name': chat.title,
                            'error': 'Bot is not a member'
                        })
                except Exception as e:
                    results['accessible'] = False
                    results['errors'].append({
                        'type': 'AUTH_CHANNEL',
                        'id': self.auth_channel,
                        'name': getattr(chat, 'title', 'Unknown'),
                        'error': 'Cannot verify membership'
                    })
            except Exception as e:
                error_msg = str(e).lower()
                if "channel_private" in error_msg:
                    results['accessible'] = False
                    results['errors'].append({
                        'type': 'AUTH_CHANNEL',
                        'id': self.auth_channel,
                        'error': 'Channel is private - Bot needs to be added'
                    })
                else:
                    results['accessible'] = False
                    results['errors'].append({
                        'type': 'AUTH_CHANNEL',
                        'id': self.auth_channel,
                        'error': str(e)
                    })

        # Check AUTH_GROUPS
        for group_id in self.auth_groups:
            try:
                chat = await client.get_chat(group_id)
                # Try to get bot's member status
                try:
                    member = await client.get_chat_member(group_id, "me")
                    if member.status not in [
                        enums.ChatMemberStatus.ADMINISTRATOR,
                        enums.ChatMemberStatus.MEMBER
                    ]:
                        results['accessible'] = False
                        results['errors'].append({
                            'type': 'AUTH_GROUP',
                            'id': group_id,
                            'name': chat.title,
                            'error': 'Bot is not a member'
                        })
                except Exception as e:
                    results['accessible'] = False
                    results['errors'].append({
                        'type': 'AUTH_GROUP',
                        'id': group_id,
                        'name': getattr(chat, 'title', 'Unknown'),
                        'error': 'Cannot verify membership'
                    })
            except Exception as e:
                error_msg = str(e).lower()
                if "channel_private" in error_msg or "chat not found" in error_msg:
                    results['accessible'] = False
                    results['errors'].append({
                        'type': 'AUTH_GROUP',
                        'id': group_id,
                        'error': 'Group is private - Bot needs to be added'
                    })
                else:
                    results['accessible'] = False
                    results['errors'].append({
                        'type': 'AUTH_GROUP',
                        'id': group_id,
                        'error': str(e)
                    })

        return results

# Utility functions for compatibility with existing code
async def is_subscribed(
        client: Client,
        query: Union[Message, CallbackQuery, InlineQuery],
        auth_channel: Optional[int] = None,
        auth_groups: Optional[list] = None
) -> bool:
    """
    Compatibility function - checks if user is subscribed

    Args:
        client: Pyrogram client
        query: Message, CallbackQuery, or InlineQuery object
        auth_channel: AUTH_CHANNEL ID
        auth_groups: List of AUTH_GROUP IDs

    Returns:
        bool: True if subscribed to all required channels/groups
    """
    # If no auth requirements, allow access
    if not auth_channel and not auth_groups:
        return True

    # Get user ID from different query types
    if hasattr(query, 'from_user') and query.from_user:
        user_id = query.from_user.id
    else:
        return False

    # Use SubscriptionManager
    sub_manager = SubscriptionManager(auth_channel, auth_groups)
    return await sub_manager.is_subscribed(
        client,
        user_id,
        check_channel=bool(auth_channel),
        check_groups=bool(auth_groups)
    )


async def get_auth_channel_link(client: Client, auth_channel: int) -> str:
    """Get AUTH_CHANNEL link for subscription"""
    sub_manager = SubscriptionManager(auth_channel)
    return await sub_manager.get_chat_link(client, auth_channel)


async def check_user_subscription(
        client: Client,
        user_id: int,
        auth_channel: Optional[int] = None,
        auth_groups: Optional[list] = None
) -> tuple[bool, list[str]]:
    """
    Check user subscription and return status with links

    Returns:
        tuple: (is_subscribed, list_of_required_links)
    """
    sub_manager = SubscriptionManager(auth_channel, auth_groups)

    # Check if subscribed
    is_sub = await sub_manager.is_subscribed(client, user_id)

    if is_sub:
        return True, []

    # Get required links
    required_links = []

    if auth_channel:
        link = await sub_manager.get_chat_link(client, auth_channel)
        required_links.append(link)

    if auth_groups:
        for group_id in auth_groups:
            link = await sub_manager.get_chat_link(client, group_id)
            required_links.append(link)

    return False, required_links


