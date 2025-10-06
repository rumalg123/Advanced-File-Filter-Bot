from functools import lru_cache
from typing import Optional, List, Tuple
from datetime import date

from core.cache.redis_cache import CacheManager
from core.utils.logger import get_logger
from core.utils.rate_limiter import RateLimiter
from repositories.media import MediaRepository, MediaFile, FileType
from repositories.user import UserRepository
from core.cache.config import CacheTTLConfig

logger = get_logger(__name__)


class FileAccessService:
    """Service for managing file access and retrieval"""

    def __init__(
            self,
            user_repo: UserRepository,
            media_repo: MediaRepository,
            cache_manager: CacheManager,
            rate_limiter: RateLimiter,
            config=None
    ):
        self.user_repo = user_repo
        self.media_repo = media_repo
        self.cache = cache_manager
        self.rate_limiter = rate_limiter
        self.config = config
        self.settings_cache_ttl = CacheTTLConfig


    async def check_and_grant_access(
            self,
            user_id: int,
            file_identifier: str,
            increment: bool = True,
            owner_id: Optional[int] = None
    ) -> Tuple[bool, str, Optional[MediaFile]]:
        """
        Check if user can access file and grant access if allowed
        Now uses unified lookup that works with both file_id and file_ref
        Returns: (allowed, message, file_object)
        """
        logger.info(f"check_and_grant_access: user_id={user_id}, file={file_identifier}, increment={increment}, owner_id={owner_id}")

        # Check rate limit first
        is_allowed, cooldown = await self.rate_limiter.check_rate_limit(
            user_id, 'file_request'
        )
        if not is_allowed:
            return False, f"Rate limit exceeded. Try again in {cooldown} seconds.", None

        # Get file details using unified lookup
        file = await self.media_repo.find_file(file_identifier)
        if not file:
            return False, "File not found.", None

        # Check user access
        logger.info(f"Checking user access for user_id={user_id}, owner_id={owner_id}")
        can_access, reason = await self.user_repo.can_retrieve_file(user_id, owner_id)

        logger.info(f"can_access={can_access}, increment={increment}")

        # For non-premium users, check if they would exceed limit AFTER incrementing
        if can_access and increment and not self.config.DISABLE_PREMIUM:
            user = await self.user_repo.get_user(user_id)
            is_admin = user_id in self.config.ADMINS if self.config.ADMINS else False

            if user and not user.is_premium and user_id != owner_id and not is_admin:
                # Check if incrementing would exceed the limit
                today = date.today()
                current_count = user.daily_retrieval_count if user.last_retrieval_date == today else 0

                if current_count >= self.user_repo.daily_limit:
                    return False, f"Daily limit reached ({current_count}/{self.user_repo.daily_limit})", None

        if can_access and increment:
            # Increment retrieval count for non-premium users when premium is enabled
            # Use the config passed to the service, not a new instance
            if not self.config:
                logger.error("FileAccessService config is None, cannot check premium settings")
                return can_access, reason, file if can_access else None

            logger.info(f"DISABLE_PREMIUM={self.config.DISABLE_PREMIUM}")
            # Only increment if premium system is enabled
            if not self.config.DISABLE_PREMIUM:
                user = await self.user_repo.get_user(user_id)
                logger.info(f"User found: {user is not None}")
                if user:
                    logger.info(f"User {user_id}: is_premium={user.is_premium}, daily_count={user.daily_retrieval_count}")

                # Check if user is admin
                is_admin = user_id in self.config.ADMINS if self.config.ADMINS else False
                logger.info(f"Is admin: {is_admin}, Is owner: {user_id == owner_id}")

                if user and not user.is_premium and user_id != owner_id and not is_admin:
                    logger.info(f"Incrementing retrieval count for user {user_id}")
                    count = await self.user_repo.increment_retrieval_count(user_id)
                    logger.info(f"New retrieval count for user {user_id}: {count}")
                else:
                    logger.info(f"Not incrementing: user_premium={user.is_premium if user else 'no_user'}, is_owner={user_id == owner_id}, is_admin={is_admin}")
            else:
                logger.info(f"Not incrementing: DISABLE_PREMIUM is True")

        return can_access, reason, file if can_access else None


    async def search_files_with_access_check(
            self,
            user_id: int,
            query: str,
            chat_id: int,
            file_type: Optional[str] = None,
            offset: int = 0,
            limit: int = 10
    ) -> Tuple[List[MediaFile], int, int, bool]:
        """
        Search files with access check
        Returns: (files, next_offset, total, has_access)
        """
        # Check rate limit
        is_allowed, cooldown = await self.rate_limiter.check_rate_limit(
            user_id, 'search'
        )
        if not is_allowed:
            return [], 0, 0, False

        # Check user access (without incrementing count for search)
        can_access, _ = await self.user_repo.can_retrieve_file(user_id)
        if not can_access:
            return [], 0, 0, False


        # Convert file_type string to enum if provided
        file_type_enum = None
        if file_type:
            try:
                file_type_enum = FileType(file_type.lower())
            except ValueError:
                pass
        use_caption_filter = self.config.USE_CAPTION_FILTER if self.config else True
        # Search files
        files, next_offset, total = await self.media_repo.search_files(
            query,
            file_type_enum,
            offset,
            limit,
            use_caption_filter
        )

        return files, next_offset, total, True

# Singleton service instances
@lru_cache(maxsize=1)
def get_file_access_service(
        user_repo: UserRepository,
        media_repo: MediaRepository,
        cache_manager: CacheManager,
        rate_limiter: RateLimiter
) -> FileAccessService:
    """Get singleton FileAccessService instance"""
    return FileAccessService(user_repo, media_repo, cache_manager, rate_limiter)