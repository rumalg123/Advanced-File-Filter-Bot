"""
Reusable guard functions for role and permission checks
"""
from functools import wraps
from typing import Optional, Callable, Any, Union, List

from pyrogram import Client
from pyrogram.types import Message, CallbackQuery

from core.utils.errors import ErrorFactory, ErrorCode
from core.utils.logger import get_logger

logger = get_logger(__name__)


class Guards:
    """Reusable permission and role guard functions"""
    
    @staticmethod
    async def check_admin_permission(
        user_id: int, 
        admin_list: List[int], 
        correlation_id: Optional[str] = None
    ) -> tuple[bool, Optional[str]]:
        """Check if user has admin permissions"""
        if user_id in admin_list:
            logger.info(f"Admin access granted", extra={
                "event": "admin_check",
                "user_id": user_id,
                "correlation_id": correlation_id,
                "outcome": "granted"
            })
            return True, None
        
        error = ErrorFactory.create_error(
            ErrorCode.INSUFFICIENT_PERMISSIONS,
            "This command requires admin privileges",
            correlation_id=correlation_id,
            user_id=user_id
        )
        
        return False, "⚠️ This command is restricted to bot admins only."
    
    @staticmethod
    async def check_premium_permission(
        user_id: int,
        user_premium_status: bool,
        global_premium_required: bool,
        link_premium_required: bool = False,
        correlation_id: Optional[str] = None
    ) -> tuple[bool, Optional[str]]:
        """
        Check premium permissions with precedence rules:
        1. Link-level premium overrides global settings
        2. If link requires premium, user must have premium (regardless of global)
        3. If global premium required and no link override, user must have premium
        """
        # Link-level premium requirement takes precedence
        if link_premium_required:
            if user_premium_status:
                logger.info("Premium access granted via link-level requirement", extra={
                    "event": "premium_check", 
                    "user_id": user_id,
                    "correlation_id": correlation_id,
                    "link_premium": True,
                    "user_premium": user_premium_status,
                    "outcome": "granted"
                })
                return True, None
            else:
                error = ErrorFactory.create_error(
                    ErrorCode.PREMIUM_REQUIRED,
                    "This content requires premium membership",
                    correlation_id=correlation_id,
                    user_id=user_id,
                    details={"link_premium_required": True}
                )
                return False, "💎 This content requires premium membership to access."
        
        # Global premium requirement (if no link override)
        elif global_premium_required:
            if user_premium_status:
                logger.info("Premium access granted via global requirement", extra={
                    "event": "premium_check",
                    "user_id": user_id, 
                    "correlation_id": correlation_id,
                    "global_premium": True,
                    "user_premium": user_premium_status,
                    "outcome": "granted"
                })
                return True, None
            else:
                error = ErrorFactory.create_error(
                    ErrorCode.PREMIUM_REQUIRED,
                    "Premium membership required", 
                    correlation_id=correlation_id,
                    user_id=user_id,
                    details={"global_premium_required": True}
                )
                return False, "💎 Premium membership required to use this bot."
        
        # No premium requirements
        logger.info("Access granted - no premium requirements", extra={
            "event": "premium_check",
            "user_id": user_id,
            "correlation_id": correlation_id,
            "outcome": "granted"
        })
        return True, None
    
    @staticmethod
    async def check_ban_status(
        user_id: int,
        is_banned: bool,
        correlation_id: Optional[str] = None
    ) -> tuple[bool, Optional[str]]:
        """Check if user is banned"""
        if is_banned:
            error = ErrorFactory.create_error(
                ErrorCode.BANNED_USER,
                "User is banned from using this bot",
                correlation_id=correlation_id,
                user_id=user_id
            )
            return False, "🚫 You are banned from using this bot."
        
        return True, None
    
    @staticmethod
    async def check_rate_limit(
        user_id: int,
        current_count: int,
        limit: int,
        reset_time: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> tuple[bool, Optional[str]]:
        """Check rate limiting"""
        if current_count >= limit:
            error = ErrorFactory.create_error(
                ErrorCode.RATE_LIMIT_EXCEEDED,
                f"Rate limit exceeded: {current_count}/{limit}",
                correlation_id=correlation_id,
                user_id=user_id,
                details={
                    "current_count": current_count,
                    "limit": limit,
                    "reset_time": reset_time
                }
            )
            
            message = f"⏰ Rate limit exceeded. You've used {current_count}/{limit} requests."
            if reset_time:
                message += f" Limit resets at {reset_time}."
                
            return False, message
        
        return True, None


def require_admin(admin_list: List[int]) -> Callable:
    """Decorator to require admin permissions"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self, client: Client, message: Union[Message, CallbackQuery], *args, **kwargs) -> Any:
            user_id = message.from_user.id if message.from_user else None
            if not user_id:
                await message.reply("❌ Unable to identify user.")
                return
            
            allowed, error_msg = await Guards.check_admin_permission(user_id, admin_list)
            if not allowed:
                if isinstance(message, CallbackQuery):
                    await message.answer(error_msg, show_alert=True)
                else:
                    await message.reply(error_msg)
                return
            
            return await func(self, client, message, *args, **kwargs)
        
        return wrapper
    return decorator


def require_premium(
    global_premium_required: bool = False,
    link_premium_required: bool = False
) -> Callable:
    """Decorator to require premium permissions with precedence rules"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self, client: Client, message: Union[Message, CallbackQuery], *args, **kwargs) -> Any:
            user_id = message.from_user.id if message.from_user else None
            if not user_id:
                await message.reply("❌ Unable to identify user.")
                return
            
            # Get user premium status (would need to be injected or retrieved)
            # This is a placeholder - in practice you'd get this from user repository
            user_premium_status = False  # Replace with actual lookup
            
            allowed, error_msg = await Guards.check_premium_permission(
                user_id, 
                user_premium_status,
                global_premium_required,
                link_premium_required
            )
            
            if not allowed:
                if isinstance(message, CallbackQuery):
                    await message.answer(error_msg, show_alert=True)
                else:
                    await message.reply(error_msg)
                return
            
            return await func(self, client, message, *args, **kwargs)
        
        return wrapper
    return decorator


def check_banned() -> Callable:
    """Decorator to check if user is banned"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self, client: Client, message: Union[Message, CallbackQuery], *args, **kwargs) -> Any:
            user_id = message.from_user.id if message.from_user else None
            if not user_id:
                await message.reply("❌ Unable to identify user.")
                return
            
            # Get user ban status (would need to be injected or retrieved)
            # This is a placeholder - in practice you'd get this from user repository
            is_banned = False  # Replace with actual lookup
            
            allowed, error_msg = await Guards.check_ban_status(user_id, is_banned)
            if not allowed:
                if isinstance(message, CallbackQuery):
                    await message.answer(error_msg, show_alert=True)
                else:
                    await message.reply(error_msg)
                return
            
            return await func(self, client, message, *args, **kwargs)
        
        return wrapper
    return decorator