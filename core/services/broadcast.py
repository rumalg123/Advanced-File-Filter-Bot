import asyncio
from functools import lru_cache
from typing import Dict

from pyrogram.enums import ParseMode
from core.cache.redis_cache import CacheManager
from core.utils.logger import get_logger
from core.utils.rate_limiter import RateLimiter
from core.utils.telegram_api import telegram_api
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
        # Get total user count upfront for accurate progress calculation
        if target_users:
            total_users = len(target_users)
        else:
            total_users = await self.user_repo.count({'status': {'$ne': UserStatus.BANNED.value}})
        
        stats = {
            'total': total_users,
            'success': 0,
            'blocked': 0,
            'deleted': 0,
            'failed': 0
        }

        # Initial progress callback to show 0%
        if progress_callback:
            await progress_callback(stats)

        # Get all users in batches
        offset = 0
        last_progress_update = 0
        processed_users = 0

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
                processed_users += 1

                try:
                    if hasattr(message, 'copy'):
                        # Check if it's a text message or media with caption
                        if message.text:
                            # For text messages, send with HTML parse mode
                            await telegram_api.call_api(
                                client.send_message, 
                                user_id, message.text, 
                                parse_mode=ParseMode.HTML,
                                chat_id=user_id
                            )
                        elif message.caption:
                            # For media with caption, copy and set parse mode for caption
                            await telegram_api.call_api(
                                message.copy, 
                                user_id, 
                                parse_mode=ParseMode.HTML,
                                chat_id=user_id
                            )
                        else:
                            # For media without caption, just copy
                            await telegram_api.call_api(
                                message.copy, 
                                user_id,
                                chat_id=user_id
                            )
                    else:
                        # Fallback: send as text message with HTML parse mode
                        await telegram_api.call_api(
                            client.send_message, 
                            user_id, str(message), 
                            parse_mode=ParseMode.HTML,
                            chat_id=user_id
                        )

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

            # Progress callback - update more frequently
            processed_count = stats['success'] + stats['blocked'] + stats['deleted'] + stats['failed']
            if progress_callback and (processed_count - last_progress_update) >= 10:  # Update every 10 users
                await progress_callback(stats)
                last_progress_update = processed_count

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