"""
Reusable guard functions for role and permission checks.

This module provides static methods for permission checking that can be used
directly in handlers. For decorator-based guards, see handlers/decorators.py.
"""
from typing import Optional, List, Tuple

from core.utils.logger import get_logger

logger = get_logger(__name__)


class Guards:
    """
    Reusable permission and role guard functions.

    These are static methods that can be called directly from handlers
    for permission checking. Returns (allowed: bool, error_message: Optional[str]).
    """

    @staticmethod
    async def check_admin_permission(
        user_id: int,
        admin_list: List[int],
        correlation_id: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """Check if user has admin permissions"""
        if user_id in admin_list:
            logger.debug(f"Admin access granted for user {user_id}")
            return True, None

        logger.debug(f"Admin access denied for user {user_id}")
        return False, "This command is restricted to bot admins only."
    
    @staticmethod
    async def check_premium_permission(
        user_id: int,
        user_premium_status: bool,
        global_premium_required: bool,
        link_premium_required: bool = False,
        correlation_id: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Check premium permissions with precedence rules:
        1. Link-level premium overrides global settings
        2. If link requires premium, user must have premium (regardless of global)
        3. If global premium required and no link override, user must have premium
        """
        # Link-level premium requirement takes precedence
        if link_premium_required:
            if user_premium_status:
                logger.debug(f"Premium access granted for user {user_id} (link requirement)")
                return True, None
            else:
                return False, "This content requires premium membership to access."

        # Global premium requirement (if no link override)
        if global_premium_required:
            if user_premium_status:
                logger.debug(f"Premium access granted for user {user_id} (global requirement)")
                return True, None
            else:
                return False, "Premium membership required to use this bot."

        # No premium requirements
        return True, None
    
    @staticmethod
    async def check_ban_status(
        user_id: int,
        is_banned: bool,
        correlation_id: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """Check if user is banned"""
        if is_banned:
            logger.debug(f"User {user_id} is banned")
            return False, "You are banned from using this bot."

        return True, None

    @staticmethod
    async def check_rate_limit(
        user_id: int,
        current_count: int,
        limit: int,
        reset_time: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """Check rate limiting"""
        if current_count >= limit:
            logger.debug(f"Rate limit exceeded for user {user_id}: {current_count}/{limit}")

            message = f"Rate limit exceeded. You've used {current_count}/{limit} requests."
            if reset_time:
                message += f" Limit resets at {reset_time}."

            return False, message

        return True, None

    @staticmethod
    def is_admin_or_owner(
        user_id: int,
        admin_list: List[int],
        auth_users: Optional[List[int]] = None
    ) -> bool:
        """
        Quick check if user is admin, owner, or auth user.
        Used for skipping permission checks.
        """
        if user_id in admin_list:
            return True
        if auth_users and user_id in auth_users:
            return True
        return False