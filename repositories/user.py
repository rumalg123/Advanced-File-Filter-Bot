import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, date, timedelta
from dataclasses import dataclass, asdict
from enum import Enum

from pymongo import UpdateOne

from core.cache.config import CacheTTLConfig, CacheKeyGenerator
from core.database.base import BaseRepository, AggregationMixin

from core.utils.logger import get_logger
logger = get_logger(__name__)


class UserStatus(Enum):
    ACTIVE = "active"
    BANNED = "banned"
    INACTIVE = "inactive"


@dataclass
class User:
    """User entity"""
    id: int
    name: str
    status: UserStatus = UserStatus.ACTIVE
    ban_reason: Optional[str] = None
    is_premium: bool = False
    premium_activation_date: Optional[datetime] = None
    daily_retrieval_count: int = 0
    last_retrieval_date: Optional[date] = None
    created_at: datetime = None
    updated_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
        if self.updated_at is None:
            self.updated_at = datetime.utcnow()


class UserRepository(BaseRepository[User], AggregationMixin):
    """Repository for user operations"""

    def __init__(self, db_pool, cache_manager,premium_duration_days=30, daily_limit=10):
        super().__init__(db_pool, cache_manager, "users")
        self.premium_duration_days = premium_duration_days
        self.daily_limit = daily_limit
        self.ttl = CacheTTLConfig()  # Add this

    def _entity_to_dict(self, user: User) -> Dict[str, Any]:
        """Convert User entity to dictionary"""
        data = asdict(user)
        data['_id'] = data.pop('id')
        data['status'] = user.status.value
        # Convert dates to ISO format for JSON serialization
        if data.get('premium_activation_date'):
            data['premium_activation_date'] = data['premium_activation_date'].isoformat()
        if data.get('last_retrieval_date'):
            data['last_retrieval_date'] = data['last_retrieval_date'].isoformat()
        data['created_at'] = data['created_at'].isoformat()
        data['updated_at'] = data['updated_at'].isoformat()
        return data

    def _dict_to_entity(self, data: Dict[str, Any]) -> User:
        """Convert dictionary to User entity"""
        data['id'] = data.pop('_id')
        data['status'] = UserStatus(data.get('status', 'active'))

        # Parse dates
        if data.get('premium_activation_date'):
            if isinstance(data['premium_activation_date'], str):
                data['premium_activation_date'] = datetime.fromisoformat(data['premium_activation_date'])

        if data.get('last_retrieval_date'):
            if isinstance(data['last_retrieval_date'], str):
                data['last_retrieval_date'] = date.fromisoformat(data['last_retrieval_date'])

        if data.get('created_at'):
            if isinstance(data['created_at'], str):
                data['created_at'] = datetime.fromisoformat(data['created_at'])

        if data.get('updated_at'):
            if isinstance(data['updated_at'], str):
                data['updated_at'] = datetime.fromisoformat(data['updated_at'])

        return User(**data)

    def _get_cache_key(self, user_id: int) -> str:
        """Generate cache key for user"""
        return CacheKeyGenerator.user(user_id)

    async def create_user(self, user_id: int, name: str) -> bool:
        """Create new user"""
        user = User(id=user_id, name=name)
        return await self.create(user)

    async def get_user(self, user_id: int) -> Optional[User]:
        """Get user by ID with proper TTL"""
        cache_key = CacheKeyGenerator.user(user_id)

        # Try cache first
        cached = await self.cache.get(cache_key)
        if cached:
            return self._dict_to_entity(cached)

        # Fetch from database
        user = await self.find_by_id(user_id, use_cache=False)
        if user:
            # Cache with proper TTL
            await self.cache.set(
                cache_key,
                self._entity_to_dict(user),
                expire=self.ttl.USER_DATA
            )
        return user

    async def is_user_exist(self, user_id: int) -> bool:
        """Check if user exists"""
        user = await self.get_user(user_id)
        return user is not None

    async def ban_user(self, user_id: int, reason: str = "No reason") -> Tuple[bool, str, Optional[User]]:
        """Ban a user"""
        user = await self.get_user(user_id)
        if not user:
            return False, "❌ User not found in database. User must have used the bot before.", None
            # Check if already banned
        if user.status == UserStatus.BANNED:
            ban_date = user.updated_at.strftime('%Y-%m-%d %H:%M:%S') if user.updated_at else 'Unknown'
            return False, (
                f"❌ User is already banned!\n\n"
                f"**User ID:** `{user_id}`\n"
                f"**Name:** {user.name}\n"
                f"**Reason:** {user.ban_reason or 'No reason provided'}\n"
                f"**Banned on:** {ban_date}"
            ), user
        update_data = {
            'status': UserStatus.BANNED.value,
            'ban_reason': reason,
            'updated_at': datetime.utcnow()
        }

        success = await self.update(user_id, update_data)

        if success:
            await self.cache.delete(CacheKeyGenerator.user(user_id))
            #await self.cache.delete(CacheKeyGenerator.banned_users())
            # Update cache with banned users list
            banned_key = CacheKeyGenerator.banned_users()
            banned_users = await self.find_many({'status': UserStatus.BANNED.value})
            banned_ids = [u.id for u in banned_users]
            await self.cache.set(banned_key, banned_ids, expire=300)  # 5 minutes instead of 1 hour
            user.status = UserStatus.BANNED
            user.ban_reason = reason
            user.updated_at = datetime.utcnow()
            logger.info(f"User {user_id} banned and cache updated")

        return success, "✅ User banned successfully!" if success else "❌ Failed to ban user.", user

    async def unban_user(self, user_id: int) -> Tuple[bool, str, Optional[User]]:
        """Unban a user"""
        user = await self.get_user(user_id)
        if not user:
            return False, "❌ User not found in database.", None

        # Check if user is actually banned
        if user.status != UserStatus.BANNED:
            return False, f"❌ User `{user_id}` is not banned!", user
        update_data = {
            'status': UserStatus.ACTIVE.value,
            'ban_reason': None,
            'updated_at': datetime.utcnow()
        }

        success = await self.update(user_id, update_data)

        if success:
            # Update cache
            await self.cache.delete(CacheKeyGenerator.user(user_id))
            banned_key = CacheKeyGenerator.banned_users()
            banned_users = await self.find_many({'status': UserStatus.BANNED.value})
            banned_ids = [u.id for u in banned_users]
            await self.cache.set(banned_key, banned_ids, expire=300)  # 5 minutes TTL

            user.status = UserStatus.ACTIVE
            user.ban_reason = None
            user.updated_at = datetime.utcnow()
            logger.info(f"User {user_id} unbanned and cache updated")

        return success, "✅ User unbanned successfully!" if success else "❌ Failed to unban user.", user

    async def get_banned_users(self) -> List[int]:
        """Get all banned user IDs with proper cache key"""
        cache_key = CacheKeyGenerator.banned_users()
        cached = await self.cache.get(cache_key)
        if cached is not None:
            return cached

        users = await self.find_many({'status': UserStatus.BANNED.value})
        banned_ids = [user.id for user in users]

        await self.cache.set(cache_key, banned_ids, expire=self.ttl.BANNED_USERS_LIST)
        return banned_ids

    async def refresh_banned_users_cache(self) -> List[int]:
        """Refresh banned users cache from database"""
        users = await self.find_many({'status': UserStatus.BANNED.value})
        banned_ids = [user.id for user in users]

        cache_key = CacheKeyGenerator.banned_users()
        await self.cache.set(cache_key, banned_ids, expire=300)  # 5 minutes TTL

        logger.debug(f"Refreshed banned users cache: {len(banned_ids)} users")
        return banned_ids

    async def update_premium_status(self, user_id: int, is_premium: bool) -> Tuple[bool, str, Optional[User]]:
        """Update user premium status"""
        # Check if user exists
        user = await self.get_user(user_id)
        if not user:
            return False, "❌ User not found in database.", None

        # Check if already has the same premium status
        if user.is_premium == is_premium:
            status_text = "premium" if is_premium else "non-premium"
            return False, f"❌ User is already {status_text}!", user
        update_data = {
            'is_premium': is_premium,
            'premium_activation_date': datetime.utcnow() if is_premium else None,
            'updated_at': datetime.utcnow()
        }

        if not is_premium:
            update_data['daily_retrieval_count'] = 0

        success = await self.update(user_id, update_data)
        if success:
            # Update user object
            user.is_premium = is_premium
            user.premium_activation_date = datetime.utcnow() if is_premium else None
            user.updated_at = datetime.utcnow()
            if not is_premium:
                user.daily_retrieval_count = 0

        action = "added" if is_premium else "removed"
        return success, f"✅ Premium status {action} successfully!" if success else f"❌ Failed to {action.replace('ed', '')} premium status.", user

    async def check_and_update_premium_status(self, user: User) -> Tuple[bool, Optional[str]]:
        """Check and update premium status if expired"""
        if not user.is_premium:
            return False, None

        if not user.premium_activation_date:
            return False, None

        expiry_date = user.premium_activation_date + timedelta(days=self.premium_duration_days)

        if datetime.utcnow() > expiry_date:
            # Premium expired
            await self.update_premium_status(user.id, False)
            return False, "Premium subscription expired"

        days_remaining = (expiry_date - datetime.utcnow()).days
        return True, f"Premium active ({days_remaining} days remaining)"

    async def increment_retrieval_count(self, user_id: int) -> int:
        """Increment daily retrieval count"""
        user = await self.get_user(user_id)
        if not user:
            return 0

        today = date.today().isoformat()

        # Reset count if it's a new day
        if user.last_retrieval_date != today:
            user.daily_retrieval_count = 0

        user.daily_retrieval_count += 1

        update_data = {
            'daily_retrieval_count': user.daily_retrieval_count,
            'last_retrieval_date': today,
            'updated_at': datetime.utcnow()
        }

        await self.update(user_id, update_data)
        return user.daily_retrieval_count

    async def can_retrieve_file(self, user_id: int, owner_id: Optional[int] = None) -> Tuple[bool, str]:
        """Check if user can retrieve a file"""
        # Owner always has access
        from bot import BotConfig
        config = BotConfig()
        if config.DISABLE_PREMIUM:
            return True, "Unlimited access (Premium disabled)"
        logger.info(f"owner_id: {owner_id}, user_id: {user_id}")
        if owner_id and user_id == owner_id:
            return True, "Owner access"

        user = await self.get_user(user_id)
        logger.info(f"user:{user}")
        if not user:
            return False, "User not found"

        # Check ban status
        if user.status == UserStatus.BANNED:
            return False, f"User banned: {user.ban_reason}"

        # Check premium status
        is_premium, premium_msg = await self.check_and_update_premium_status(user)
        if is_premium:
            return True, premium_msg

        # Check daily limit for non-premium users
        today = date.today()
        if user.last_retrieval_date != today:
            # New day, reset count
            return True, f"Daily limit: 0/{self.daily_limit}"

        if user.daily_retrieval_count >= self.daily_limit:
            return False, f"Daily limit reached ({self.daily_limit}/{self.daily_limit})"

        remaining = self.daily_limit - user.daily_retrieval_count
        return True, f"Daily limit: {user.daily_retrieval_count}/{self.daily_limit} (Remaining: {remaining})"

    async def get_user_stats(self) -> Dict[str, Any]:
        """Get user statistics"""
        cache_key = CacheKeyGenerator.user_stats()
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        pipeline = [
            {"$facet": {
                "total": [{"$count": "count"}],
                "premium": [
                    {"$match": {"is_premium": True}},
                    {"$count": "count"}
                ],
                "banned": [
                    {"$match": {"status": UserStatus.BANNED.value}},
                    {"$count": "count"}
                ],
                "active_today": [
                    {"$match": {
                        "last_retrieval_date": date.today().isoformat()
                    }},
                    {"$count": "count"}
                ]
            }}
        ]

        results = await self.aggregate(pipeline)
        if results:
            facets = results[0]
            stats = {
                'total': facets['total'][0]['count'] if facets['total'] else 0,
                'premium': facets['premium'][0]['count'] if facets['premium'] else 0,
                'banned': facets['banned'][0]['count'] if facets['banned'] else 0,
                'active_today': facets['active_today'][0]['count'] if facets['active_today'] else 0,
            }
            await self.cache.set(cache_key, stats, expire=self.ttl.USER_STATS)
            return stats
        return {'total': 0, 'premium': 0, 'banned': 0, 'active_today': 0}

    async def cleanup_expired_premium(self) -> int:
        """Cleanup expired premium subscriptions"""
        cutoff_date = datetime.utcnow() - timedelta(days=self.premium_duration_days)

        filter_query = {
            'is_premium': True,
            'premium_activation_date': {'$lte': cutoff_date.isoformat()}
        }

        users = await self.find_many(filter_query)

        if users:
            operations = []
            for user in users:
                operations.append(
                    UpdateOne(
                        {'_id': user.id},
                        {'$set': {
                            'is_premium': False,
                            'premium_activation_date': None,
                            'updated_at': datetime.utcnow()
                        }}
                    )
                )

            if operations:
                await self.bulk_write(operations)

        return len(users)