import re
from functools import wraps
from typing import Optional, Union, Tuple, Any, List
from pyrogram import Client, enums
from pyrogram.types import Message, CallbackQuery
from core.utils.errors import ErrorFactory, ErrorCode
from core.utils.logger import get_logger

logger = get_logger(__name__)


class ValidationUtils:
    """Centralized validation utilities"""

    @staticmethod
    def extract_user_id(message: Union[Message, CallbackQuery]) -> Optional[int]:
        """Extract user ID from Message or CallbackQuery"""
        if isinstance(message, CallbackQuery):
            return message.from_user.id if message.from_user else None
        else:
            return message.from_user.id if message.from_user else None

    @staticmethod
    def is_admin(user_id: int, admins: list) -> bool:
        """Check if user is admin"""
        return user_id in admins

    @staticmethod
    def is_auth_user(user_id: int, auth_users: list) -> bool:
        """Check if user is authorized"""
        return user_id in auth_users

    @staticmethod
    def is_private_chat(message: Union[Message, CallbackQuery]) -> bool:
        """Check if message is from private chat"""
        if isinstance(message, CallbackQuery):
            chat = message.message.chat if message.message else None
        else:
            chat = message.chat
        
        return chat and chat.type == enums.ChatType.PRIVATE

    @staticmethod
    def is_group_chat(message: Union[Message, CallbackQuery]) -> bool:
        """Check if message is from group or supergroup"""
        if isinstance(message, CallbackQuery):
            chat = message.message.chat if message.message else None
        else:
            chat = message.chat
        
        return chat and chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]

    @staticmethod
    def is_bot_user(message: Union[Message, CallbackQuery]) -> bool:
        """Check if user is a bot"""
        if isinstance(message, CallbackQuery):
            from_user = message.from_user
        else:
            from_user = message.from_user
        
        return from_user and from_user.is_bot

    @staticmethod
    def is_special_channel(chat_id: int, special_channels: set) -> bool:
        """Check if chat is a special channel (log, req, delete, etc.)"""
        return chat_id in special_channels

    @staticmethod
    def validate_user_id(user_id: Union[str, int]) -> Tuple[bool, Optional[int], Optional[str]]:
        """Validate and parse user ID from string or int"""
        try:
            if isinstance(user_id, str):
                # Remove @ prefix if present
                clean_id = user_id.lstrip('@')
                
                # Check if it's numeric
                if clean_id.isdigit():
                    parsed_id = int(clean_id)
                    if parsed_id > 0:
                        return True, parsed_id, None
                    else:
                        return False, None, "User ID must be positive"
                else:
                    return False, None, "Invalid user ID format - must be numeric"
            
            elif isinstance(user_id, int):
                if user_id > 0:
                    return True, user_id, None
                else:
                    return False, None, "User ID must be positive"
            
            else:
                return False, None, "User ID must be string or integer"
                
        except (ValueError, OverflowError):
            return False, None, "Invalid user ID format"

    @staticmethod
    def validate_pagination_params(page: Union[str, int], per_page: Union[str, int]) -> Tuple[bool, int, int, Optional[str]]:
        """Validate pagination parameters"""
        try:
            page_int = int(page) if isinstance(page, str) else page
            per_page_int = int(per_page) if isinstance(per_page, str) else per_page
            
            if page_int < 1:
                return False, 0, 0, "Page number must be >= 1"
            
            if per_page_int < 1 or per_page_int > 100:
                return False, 0, 0, "Items per page must be between 1 and 100"
            
            return True, page_int, per_page_int, None
            
        except (ValueError, OverflowError):
            return False, 0, 0, "Invalid pagination parameters"

    @staticmethod
    def validate_file_types(file_types: List[str]) -> Tuple[bool, List[str], Optional[str]]:
        """Validate file type filters"""
        valid_types = {
            'document', 'video', 'audio', 'photo', 'animation', 
            'voice', 'video_note', 'sticker', 'location', 'contact'
        }
        
        cleaned_types = []
        for file_type in file_types:
            clean_type = file_type.lower().strip()
            if clean_type in valid_types:
                cleaned_types.append(clean_type)
            else:
                return False, [], f"Invalid file type: {file_type}. Valid types: {', '.join(valid_types)}"
        
        return True, cleaned_types, None


class ValidationDecorators:
    """Validation decorators for handlers"""

    @staticmethod
    def admin_only(func):
        """Decorator to restrict commands to admins only"""
        @wraps(func)
        async def wrapper(self, client: Client, message: Union[Message, CallbackQuery], *args, **kwargs):
            user_id = ValidationUtils.extract_user_id(message)
            if not user_id or not ValidationUtils.is_admin(user_id, self.bot.config.ADMINS):
                error_msg = "⚠️ This command is restricted to bot admins only."
                if isinstance(message, Message):
                    await message.reply_text(error_msg)
                elif isinstance(message, CallbackQuery):
                    await message.answer(error_msg, show_alert=True)
                return
            return await func(self, client, message, *args, **kwargs)
        return wrapper

    @staticmethod
    def owner_only(func):
        """Decorator to restrict commands to primary admin/owner only"""
        @wraps(func)
        async def wrapper(self, client: Client, message: Union[Message, CallbackQuery], *args, **kwargs):
            user_id = ValidationUtils.extract_user_id(message)
            # Get the first admin as primary owner
            owner_id = self.bot.config.ADMINS[0] if self.bot.config.ADMINS else None
            if not user_id or user_id != owner_id:
                error_msg = "⚠️ This command is restricted to the bot owner only."
                if isinstance(message, Message):
                    await message.reply_text(error_msg)
                elif isinstance(message, CallbackQuery):
                    await message.answer(error_msg, show_alert=True)
                return
            return await func(self, client, message, *args, **kwargs)
        return wrapper

    @staticmethod
    def private_only(func):
        """Decorator to restrict commands to private chats only"""
        @wraps(func)
        async def wrapper(self, client: Client, message: Union[Message, CallbackQuery], *args, **kwargs):
            if not ValidationUtils.is_private_chat(message):
                error_msg = "⚠️ This command can only be used in private chats."
                if isinstance(message, Message):
                    await message.reply_text(error_msg)
                elif isinstance(message, CallbackQuery):
                    await message.answer(error_msg, show_alert=True)
                return
            return await func(self, client, message, *args, **kwargs)
        return wrapper

    @staticmethod
    def auth_user_only(func):
        """Decorator to restrict commands to authorized users only"""
        @wraps(func)
        async def wrapper(self, client: Client, message: Union[Message, CallbackQuery], *args, **kwargs):
            user_id = ValidationUtils.extract_user_id(message)
            if not user_id:
                return
            
            # Allow admins
            if ValidationUtils.is_admin(user_id, self.bot.config.ADMINS):
                return await func(self, client, message, *args, **kwargs)
            
            # Check auth users
            auth_users = getattr(self.bot.config, 'AUTH_USERS', [])
            if not ValidationUtils.is_auth_user(user_id, auth_users):
                error_msg = "⚠️ You are not authorized to use this command."
                if isinstance(message, Message):
                    await message.reply_text(error_msg)
                elif isinstance(message, CallbackQuery):
                    await message.answer(error_msg, show_alert=True)
                return
            
            return await func(self, client, message, *args, **kwargs)
        return wrapper

    @staticmethod
    def no_bots(func):
        """Decorator to prevent bot users from executing commands"""
        @wraps(func)
        async def wrapper(self, client: Client, message: Union[Message, CallbackQuery], *args, **kwargs):
            if ValidationUtils.is_bot_user(message):
                return  # Silently ignore bot users
            return await func(self, client, message, *args, **kwargs)
        return wrapper

    @staticmethod
    def skip_special_channels(func):
        """Decorator to skip execution in special channels"""
        @wraps(func)
        async def wrapper(self, client: Client, message: Union[Message, CallbackQuery], *args, **kwargs):
            if isinstance(message, CallbackQuery):
                chat = message.message.chat if message.message else None
            else:
                chat = message.chat
            
            if chat:
                special_channels = {
                    self.bot.config.LOG_CHANNEL,
                    self.bot.config.INDEX_REQ_CHANNEL,
                    self.bot.config.REQ_CHANNEL,
                    self.bot.config.DELETE_CHANNEL
                }
                special_channels = {ch for ch in special_channels if ch}
                
                if ValidationUtils.is_special_channel(chat.id, special_channels):
                    return  # Skip execution in special channels
            
            return await func(self, client, message, *args, **kwargs)
        return wrapper


class PermissionUtils:
    """Permission checking utilities for groups and channels"""

    @staticmethod
    async def is_group_admin(client: Client, group_id: int, user_id: int) -> bool:
        """Check if user is group admin or owner"""
        try:
            member = await client.get_chat_member(group_id, user_id)
            return member.status in [
                enums.ChatMemberStatus.ADMINISTRATOR,
                enums.ChatMemberStatus.OWNER
            ]
        except Exception as e:
            logger.debug(f"Error checking admin status for user {user_id} in group {group_id}: {e}")
            return False

    @staticmethod
    async def is_group_owner(client: Client, group_id: int, user_id: int) -> bool:
        """Check if user is group owner"""
        try:
            member = await client.get_chat_member(group_id, user_id)
            return member.status == enums.ChatMemberStatus.OWNER
        except Exception as e:
            logger.debug(f"Error checking owner status for user {user_id} in group {group_id}: {e}")
            return False

    @staticmethod
    async def has_admin_rights(client: Client, group_id: int, user_id: int, bot_admins: list) -> bool:
        """Check if user has admin rights (bot admin or group admin)"""
        # Bot admins always have rights
        if ValidationUtils.is_admin(user_id, bot_admins):
            return True
        
        # Check group admin status
        return await PermissionUtils.is_group_admin(client, group_id, user_id)

    @staticmethod
    async def is_owner_or_bot_admin(client: Client, group_id: int, user_id: int, bot_admins: list) -> bool:
        """Check if user is group owner or bot admin"""
        # Bot admins always have rights
        if ValidationUtils.is_admin(user_id, bot_admins):
            return True
        
        # Check group owner status
        return await PermissionUtils.is_group_owner(client, group_id, user_id)

    @staticmethod
    def is_original_requester(callback_user_id: int, original_user_id: int) -> bool:
        """Check if callback user is the original requester"""
        return callback_user_id == original_user_id

    @staticmethod
    def skip_subscription_check(user_id: int, bot_admins: list, auth_users: list) -> bool:
        """Check if user should skip subscription requirements"""
        return (ValidationUtils.is_admin(user_id, bot_admins) or 
                ValidationUtils.is_auth_user(user_id, auth_users))


class AccessControl:
    """File access and quota validation utilities"""

    @staticmethod
    async def can_access_file(user_repo, user_id: int) -> Tuple[bool, str]:
        """Check if user can access files (quota and ban check)"""
        try:
            return await user_repo.can_retrieve_file(user_id)
        except Exception as e:
            logger.error(f"Error checking file access for user {user_id}: {e}")
            return False, "Error checking access permissions"

    @staticmethod
    async def validate_file_access(user_repo, user_id: int, message: Union[Message, CallbackQuery]) -> bool:
        """Validate file access and send error message if needed"""
        can_access, reason = await AccessControl.can_access_file(user_repo, user_id)
        
        if not can_access:
            error_msg = f"⚠️ Access denied: {reason}"
            if isinstance(message, Message):
                await message.reply_text(error_msg)
            elif isinstance(message, CallbackQuery):
                await message.answer(error_msg, show_alert=True)
            return False
        
        return True

    @staticmethod
    async def validate_original_requester(query: CallbackQuery) -> Tuple[bool, Optional[int], Optional[int]]:
        """Validate callback query is from original requester"""
        callback_user_id = ValidationUtils.extract_user_id(query)
        
        try:
            # Parse callback data to get original user ID
            parts = query.data.split('#')
            if len(parts) >= 3:
                original_user_id = int(parts[2])
            else:
                return True, callback_user_id, None  # No original user restriction
            
            if not PermissionUtils.is_original_requester(callback_user_id, original_user_id):
                await query.answer("❌ You cannot interact with this message!", show_alert=True)
                return False, callback_user_id, original_user_id
            
            return True, callback_user_id, original_user_id
            
        except (ValueError, IndexError) as e:
            logger.debug(f"Error parsing callback data: {e}")
            return True, callback_user_id, None  # Allow if parsing fails


class InputValidation:
    """Input validation and sanitization utilities"""

    # Common regex patterns
    FILENAME_SAFE = re.compile(r'^[a-zA-Z0-9._\-\s()[\]{}]+$')
    SEARCH_QUERY = re.compile(r'^[a-zA-Z0-9._\-\s()[\]{}]+$')
    CHANNEL_ID = re.compile(r'^-?\d+$')
    USERNAME = re.compile(r'^@?[a-zA-Z0-9_]{5,32}$')
    
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Sanitize filename for safe usage"""
        if not filename:
            return ""
        
        # Remove potentially dangerous characters
        sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
        # Remove control characters
        sanitized = re.sub(r'[\x00-\x1f\x7f]', '', sanitized)
        # Limit length
        return sanitized[:255]
    
    @staticmethod
    def sanitize_search_query(query: str) -> str:
        """Sanitize search query"""
        if not query:
            return ""
        
        # Remove control characters and excessive whitespace
        sanitized = re.sub(r'[\x00-\x1f\x7f]', '', query)
        sanitized = ' '.join(sanitized.split())
        # Limit length
        return sanitized[:100]
    
    @staticmethod
    def validate_channel_id(channel_id: str) -> Optional[int]:
        """Validate and convert channel ID"""
        try:
            if not InputValidation.CHANNEL_ID.match(str(channel_id)):
                return None
            return int(channel_id)
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def validate_username(username: str) -> Optional[str]:
        """Validate username format"""
        if not username:
            return None
        
        # Remove @ prefix if present
        clean_username = username.lstrip('@')
        
        if InputValidation.USERNAME.match(clean_username):
            return clean_username
        return None
    
    @staticmethod
    def validate_limit_offset(limit: Any, offset: Any, max_limit: int = 50) -> Tuple[int, int]:
        """Validate and sanitize limit/offset parameters"""
        try:
            limit = int(limit) if limit else 10
            offset = int(offset) if offset else 0
            
            # Ensure reasonable bounds
            limit = max(1, min(limit, max_limit))
            offset = max(0, offset)
            
            return limit, offset
        except (ValueError, TypeError):
            return 10, 0
    
    @staticmethod
    def validate_message_text(message: Union[Message, CallbackQuery]) -> Optional[str]:
        """Extract and validate message text"""
        if isinstance(message, CallbackQuery):
            return None  # Callback queries don't have text to validate
        
        if not message.text:
            return None
        
        text = message.text.strip()
        return text if text else None
    
    @staticmethod
    def extract_command_args(message: Message, min_args: int = 0, max_args: int = 10) -> Tuple[bool, list]:
        """Extract and validate command arguments"""
        if not message.text:
            return False, []
        
        parts = message.text.split()
        # Remove command (first part)
        args = parts[1:] if len(parts) > 1 else []
        
        if len(args) < min_args or len(args) > max_args:
            return False, args
        
        # Sanitize arguments
        sanitized_args = [InputValidation.sanitize_search_query(arg) for arg in args]
        
        return True, sanitized_args
    
    @staticmethod
    def validate_callback_data(query: CallbackQuery, expected_parts: int = 2) -> Tuple[bool, list]:
        """Validate callback query data format"""
        if not query.data:
            return False, []
        
        parts = query.data.split('#')
        
        if len(parts) < expected_parts:
            return False, parts
        
        return True, parts
    
    @staticmethod
    def sanitize_caption(caption: str) -> str:
        """Sanitize file caption"""
        if not caption:
            return ""
        
        # Remove control characters
        sanitized = re.sub(r'[\x00-\x1f\x7f]', '', caption)
        # Limit length
        return sanitized[:1024]


# Convenience exports for easy importing
extract_user_id = ValidationUtils.extract_user_id
is_admin = ValidationUtils.is_admin
is_auth_user = ValidationUtils.is_auth_user
is_private_chat = ValidationUtils.is_private_chat
is_group_chat = ValidationUtils.is_group_chat
is_bot_user = ValidationUtils.is_bot_user
is_special_channel = ValidationUtils.is_special_channel

admin_only = ValidationDecorators.admin_only
owner_only = ValidationDecorators.owner_only
private_only = ValidationDecorators.private_only
auth_user_only = ValidationDecorators.auth_user_only
no_bots = ValidationDecorators.no_bots
skip_special_channels = ValidationDecorators.skip_special_channels

# Permission utilities
is_group_admin = PermissionUtils.is_group_admin
is_group_owner = PermissionUtils.is_group_owner
has_admin_rights = PermissionUtils.has_admin_rights
is_owner_or_bot_admin = PermissionUtils.is_owner_or_bot_admin
is_original_requester = PermissionUtils.is_original_requester
skip_subscription_check = PermissionUtils.skip_subscription_check

# Access control
can_access_file = AccessControl.can_access_file
validate_file_access = AccessControl.validate_file_access
validate_original_requester = AccessControl.validate_original_requester

# Input validation and sanitization
sanitize_filename = InputValidation.sanitize_filename
sanitize_search_query = InputValidation.sanitize_search_query
sanitize_caption = InputValidation.sanitize_caption
validate_channel_id = InputValidation.validate_channel_id
validate_username = InputValidation.validate_username
validate_limit_offset = InputValidation.validate_limit_offset
validate_message_text = InputValidation.validate_message_text
extract_command_args = InputValidation.extract_command_args
validate_callback_data = InputValidation.validate_callback_data