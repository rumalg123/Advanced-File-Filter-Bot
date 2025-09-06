import asyncio
from functools import lru_cache
from typing import Dict

from pyrogram.enums import ParseMode
from core.cache.redis_cache import CacheManager
from core.utils.logger import get_logger
from core.utils.rate_limiter import RateLimiter
from repositories.user import UserRepository, UserStatus

logger = get_logger(__name__)


class BroadcastService:
    """Service for handling broadcasts"""

    def __init__(
            self,
            user_repo: UserRepository,
            cache_manager: CacheManager,
            rate_limiter: RateLimiter
    ):
        self.user_repo = user_repo
        self.cache = cache_manager
        self.rate_limiter = rate_limiter
        self.batch_size = 50
        self.delay_between_batches = 2  # seconds

        # Add these improvements to the BroadcastService class:

    # core/services/broadcast.py
    async def broadcast_to_users(
            self,
            client,  # Add client parameter
            message,
            progress_callback=None,
            target_users=None
    ) -> Dict[str, int]:
        """Broadcast message to all users with improvements"""
        stats = {
            'total': 0,
            'success': 0,
            'blocked': 0,
            'deleted': 0,
            'failed': 0
        }

        # Get all users in batches
        offset = 0
        last_progress_update = 0

        while True:
            if target_users:
                if offset >= len(target_users):
                    break
                users = target_users[offset:offset + self.batch_size]
            else:
                users = await self.user_repo.find_many(
                    {'status': {'$ne': UserStatus.BANNED.value}},
                    limit=self.batch_size,
                    skip=offset
                )

            if not users:
                break

            # Process batch
            for user in users:
                user_id = user.id if hasattr(user, 'id') else user
                stats['total'] += 1

                try:
                    if hasattr(message, 'copy'):
                        # Copy message with HTML parse mode
                        await message.copy(user_id, parse_mode=ParseMode.HTML)
                    else:
                        # Send text message with HTML parse mode
                        await client.send_message(user_id, message, parse_mode=ParseMode.HTML)

                    stats['success'] += 1

                except Exception as e:
                    error_msg = str(e).lower()
                    if "blocked" in error_msg or "forbidden" in error_msg:
                        stats['blocked'] += 1
                    elif "user not found" in error_msg or "chat not found" in error_msg:
                        stats['deleted'] += 1
                        # Remove deleted user
                        if hasattr(user, 'id'):
                            await self.user_repo.delete(user.id)
                    else:
                        stats['failed'] += 1

            # Progress callback and other logic...
            if progress_callback and (stats['success'] + stats['blocked'] + stats['deleted'] + stats[
                'failed'] - last_progress_update) >= 50:
                await progress_callback(stats)
                last_progress_update = stats['success'] + stats['blocked'] + stats['deleted'] + stats['failed']

            # Adaptive delay
            if stats['total'] > 0:
                success_rate = stats['success'] / stats['total']
                await asyncio.sleep(self.delay_between_batches * (2 if success_rate < 0.5 else 1))
            else:
                await asyncio.sleep(self.delay_between_batches)

            offset += self.batch_size

        if progress_callback:
            await progress_callback(stats)

        return stats

@lru_cache(maxsize=1)
def get_broadcast_service(
        user_repo: UserRepository,
        cache_manager: CacheManager,
        rate_limiter: RateLimiter
) -> BroadcastService:
    """Get singleton BroadcastService instance"""
    return BroadcastService(user_repo, cache_manager, rate_limiter)