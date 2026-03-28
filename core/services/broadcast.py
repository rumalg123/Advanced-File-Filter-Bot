import asyncio
from typing import Dict, List, Tuple

from core.cache.redis_cache import CacheManager
from core.concurrency.semaphore_manager import semaphore_manager
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
        self.progress_update_interval = 10

    async def _send_to_user(self, client, message, user_id: int) -> Tuple[str, int]:
        """Deliver the broadcast to a single user under the broadcast semaphore."""
        try:
            async with semaphore_manager.acquire('broadcast', f"broadcast_{user_id}"):
                if hasattr(message, 'copy'):
                    await telegram_api.call_api(
                        message.copy,
                        user_id,
                        chat_id=user_id
                    )
                else:
                    text_payload = getattr(message, 'text', None) or getattr(message, 'caption', None) or str(message)
                    await telegram_api.call_api(
                        client.send_message,
                        user_id,
                        text_payload,
                        chat_id=user_id
                    )

            return 'success', user_id
        except asyncio.CancelledError:
            raise
        except Exception as e:
            error_msg = str(e).lower()
            if "blocked" in error_msg or "forbidden" in error_msg:
                return 'blocked', user_id
            if "user not found" in error_msg or "chat not found" in error_msg:
                return 'deleted', user_id

            logger.warning(f"Broadcast delivery failed for user {user_id}: {e}")
            return 'failed', user_id

    @staticmethod
    def _apply_batch_results(
            stats: Dict[str, int],
            batch_results: List[Tuple[str, int]],
            stale_user_ids: set
    ) -> None:
        """Merge a completed batch into the running broadcast stats."""
        for status, user_id in batch_results:
            stats[status] += 1
            if status == 'deleted':
                stale_user_ids.add(user_id)

    async def broadcast_to_users(
            self,
            client,
            message,
            progress_callback=None,
            target_users=None
    ) -> Dict[str, int]:
        """Broadcast a message to users with bounded parallelism."""
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

        offset = 0
        last_user_id = None
        last_progress_update = 0
        stale_user_ids = set()

        while True:
            if target_users:
                if offset >= len(target_users):
                    break
                users = target_users[offset:offset + self.batch_size]
            else:
                user_filter = {'status': {'$ne': UserStatus.BANNED.value}}
                if last_user_id is not None:
                    user_filter['_id'] = {'$gt': last_user_id}

                users = await self.user_repo.find_many(
                    user_filter,
                    limit=self.batch_size,
                    sort=[('_id', 1)]
                )

            if not users:
                break

            if not target_users and hasattr(users[-1], 'id'):
                last_user_id = users[-1].id

            batch_results = await asyncio.gather(*[
                self._send_to_user(
                    client,
                    message,
                    user.id if hasattr(user, 'id') else user
                )
                for user in users
            ])
            self._apply_batch_results(stats, batch_results, stale_user_ids)

            processed_count = stats['success'] + stats['blocked'] + stats['deleted'] + stats['failed']
            if progress_callback and (processed_count - last_progress_update) >= self.progress_update_interval:
                await progress_callback(stats)
                last_progress_update = processed_count

            if processed_count > 0:
                success_rate = stats['success'] / processed_count
                delay = self.delay_between_batches * (2 if success_rate < 0.5 else 1)
                await asyncio.sleep(delay)
            else:
                await asyncio.sleep(self.delay_between_batches)

            if target_users:
                offset += self.batch_size

        for stale_user_id in stale_user_ids:
            await self.user_repo.delete(stale_user_id)

        if progress_callback:
            await progress_callback(stats)

        return stats
