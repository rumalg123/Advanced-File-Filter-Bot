from typing import Optional, List, Tuple, Dict, Any

from pyrogram import Client, enums

from core.cache.config import CacheKeyGenerator
from core.cache.redis_cache import CacheManager
from core.utils.logger import get_logger
from repositories.connection import ConnectionRepository

logger = get_logger(__name__)


async def verify_user_in_group(
        client: Client,
        user_id: int,
        group_id: int
) -> bool:
    """Verify if user is still in the group"""
    try:
        member = await client.get_chat_member(group_id, user_id)
        return member.status not in [
            enums.ChatMemberStatus.LEFT,
            enums.ChatMemberStatus.BANNED
        ]
    except Exception:
        return False


class ConnectionService:
    """Service for managing user-group connections"""

    def __init__(
            self,
            connection_repo: ConnectionRepository,
            cache_manager: CacheManager,
            admins: List[int]
    ):
        self.connection_repo = connection_repo
        self.cache = cache_manager
        self.admins = admins

    async def connect_to_group(
            self,
            client: Client,
            user_id: int,
            group_id: int
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Connect user to a group
        Returns: (success, message, group_title)
        """
        # Verify user is admin in the group or is bot admin
        if user_id not in self.admins:
            try:
                member = await client.get_chat_member(group_id, user_id)
                if member.status not in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER
                ]:
                    return False, "You need to be an admin in the group!", None
            except Exception as e:
                logger.error(f"Error checking admin status: {e}")
                return False, "Failed to verify admin status!", None

        # Verify bot is in the group
        try:
            bot_member = await client.get_chat_member(group_id, "me")
            if bot_member.status != enums.ChatMemberStatus.ADMINISTRATOR:
                return False, "I need to be an admin in the group!", None
        except Exception:
            return False, "Make sure I'm present in the group!", None

        # Get group info
        try:
            chat = await client.get_chat(group_id)
            title = chat.title
        except Exception:
            title = f"Group {group_id}"

        # Add connection
        success = await self.connection_repo.add_connection(str(user_id), str(group_id))

        if success:
            return True, f"Successfully connected to <b>{title}</b>!", title
        else:
            return False, "You're already connected to this chat!", title

    async def disconnect_from_group(
            self,
            client: Client,
            user_id: int,
            group_id: int,
            delete_filters: bool = True  # Add this parameter
    ) -> Tuple[bool, str]:
        """
        Disconnect user from a group
        Returns: (success, message)
        """
        success = await self.connection_repo.delete_connection(
            str(user_id),
            str(group_id)
        )

        if success:
            await self.cache.delete(CacheKeyGenerator.user_connections(str(user_id)))
            return True, "Successfully disconnected from this chat"
        else:
            return False, "This chat isn't connected to me!"

    async def get_active_connection(self, user_id: int) -> Optional[int]:
        """Get active connection for user"""
        connection = await self.connection_repo.get_active_connection(str(user_id))
        return int(connection) if connection else None

    async def get_all_connections(
            self,
            client: Client,
            user_id: int
    ) -> List[Dict[str, Any]]:
        """Get all connections with details for user"""
        group_ids = await self.connection_repo.get_all_connections(str(user_id))

        if not group_ids:
            return []

        connections = []
        active_group = await self.connection_repo.get_active_connection(str(user_id))

        for group_id in group_ids:
            try:
                chat = await client.get_chat(int(group_id))
                is_active = group_id == active_group

                connections.append({
                    'id': group_id,
                    'title': chat.title,
                    'is_active': is_active,
                    'type': chat.type.value
                })
            except Exception as e:
                logger.error(f"Error getting chat info for {group_id}: {e}")
                # Still include the connection even if we can't get chat info
                connections.append({
                    'id': group_id,
                    'title': f"Group {group_id}",
                    'is_active': group_id == active_group,
                    'type': 'unknown'
                })

        return connections

    async def set_active_connection(
            self,
            user_id: int,
            group_id: str
    ) -> Tuple[bool, str]:
        """Set active connection for user (ensures only one active)"""
        # First deactivate all connections
        await self.connection_repo.deactivate_all_connections(str(user_id))

        # Then activate the selected one
        success = await self.connection_repo.make_active(str(user_id), group_id)

        if success:
            return True, "Connection set as active"
        else:
            return False, "Failed to set active connection"

    async def clear_active_connection(self, user_id: int) -> bool:
        """Clear active connection for user"""
        return await self.connection_repo.make_inactive(str(user_id))

    async def get_or_private_chat_id(
            self,
            user_id: int,
            chat_id: int,
            chat_type: enums.ChatType
    ) -> Tuple[int | None, Optional[str]]:
        """
        Get appropriate chat ID based on context
        Returns: (chat_id, chat_title)
        """
        if chat_type == enums.ChatType.PRIVATE:
            # Get active connection in private chat
            active_connection = await self.get_active_connection(user_id)
            if active_connection:
                return active_connection, None
            else:
                return None, None
        else:
            # Use current chat in groups
            return chat_id, None


    async def cleanup_invalid_connections(
            self,
            client: Client,
            user_id: int
    ) -> int:
        """Remove connections where user is no longer member"""
        connections = await self.connection_repo.get_all_connections(str(user_id))
        if not connections:
            return 0

        removed_count = 0

        for group_id in connections:
            try:
                group_id_int = int(group_id)
                if not await verify_user_in_group(client, user_id, group_id_int):
                    if await self.connection_repo.delete_connection(str(user_id), group_id):
                        removed_count += 1
            except Exception as e:
                logger.error(f"Error checking connection {group_id}: {e}")

        return removed_count

    async def validate_all_connections(self) -> int:
        """Validate all user connections periodically"""
        invalid_count = 0

        try:
            all_connections = await self.connection_repo.find_many({})

            for conn in all_connections:
                # Check if active group is still in group_details
                if conn.active_group:
                    group_ids = [g["group_id"] for g in conn.group_details]
                    if conn.active_group not in group_ids:
                        invalid_count += 1
                        # Reset invalid active group
                        if group_ids:
                            # Set to first available group
                            await self.connection_repo.make_active(conn.user_id, group_ids[0])
                        else:
                            # No groups available
                            await self.connection_repo.make_inactive(conn.user_id)

            if invalid_count > 0:
                logger.info(f"Fixed {invalid_count} invalid active connections")

        except Exception as e:
            logger.error(f"Error validating connections: {e}")

        return invalid_count