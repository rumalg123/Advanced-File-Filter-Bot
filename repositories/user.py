from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, date, timedelta, UTC
from dataclasses import dataclass, asdict
from enum import Enum

from pymongo import UpdateOne

from core.cache.config import CacheTTLConfig, CacheKeyGenerator
from core.cache.enhanced_cache import cache_premium_status
from core.database.base import BaseRepository, AggregationMixin

from core.utils.logger import get_logger
logger = get_logger(__name__)

# Import batch optimizations
try:
    from .optimizations.batch_operations import BatchOptimizations
    BATCH_OPTIMIZATIONS_AVAILABLE = True
except ImportError:
    BATCH_OPTIMIZATIONS_AVAILABLE = False
    logger.warning("Batch optimizations not available, falling back to individual operations")


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
    daily_request_count: int = 0
    last_request_date: Optional[date] = None
    warning_count: int = 0
    last_warning_date: Optional[datetime] = None
    total_requests: int = 0  # Lifetime total
    created_at: datetime = None
    updated_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(UTC)
        if self.updated_at is None:
            self.updated_at = datetime.now(UTC)


class UserRepository(BaseRepository[User], AggregationMixin):
    """Repository for user operations"""

    def __init__(self, db_pool, cache_manager,premium_duration_days=30, daily_limit=10):
        super().__init__(db_pool, cache_manager, "users")
        self.premium_duration_days = premium_duration_days
        self.daily_limit = daily_limit
        self.ttl = CacheTTLConfig()  # Add this
        
        # Initialize batch optimizations
        if BATCH_OPTIMIZATIONS_AVAILABLE:
            self.batch_ops = BatchOptimizations(db_pool, cache_manager)
        else:
            self.batch_ops = None

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
        # ADD THIS LINE:
        if data.get('last_request_date'):
            data['last_request_date'] = data['last_request_date'].isoformat()
        # Also add for last_warning_date while you're at it:
        if data.get('last_warning_date'):
            data['last_warning_date'] = data['last_warning_date'].isoformat()
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

        if data.get('last_request_date'):
            if isinstance(data['last_request_date'], str):
                data['last_request_date'] = date.fromisoformat(data['last_request_date'])

        # ADD THIS:
        if data.get('last_warning_date'):
            if isinstance(data['last_warning_date'], str):
                data['last_warning_date'] = datetime.fromisoformat(data['last_warning_date'])

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
        """Create new user. Idempotent on duplicate key."""
        user = User(id=user_id, name=name)
        try:
            return await self.create(user)
        except Exception as e:
            # Treat duplicate key as success to make user creation idempotent
            from pymongo.errors import DuplicateKeyError
            if isinstance(e, DuplicateKeyError):
                logger.warning(f"User {user_id} already exists. Skipping create.")
                # Ensure cache is consistent
                await self.cache.delete(CacheKeyGenerator.user(user_id))
                return True
            logger.error(f"Error creating user {user_id}: {e}")
            return False

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
                f"<b>User ID:</b> <code>{user_id}</code>\n"
                f"<b>Name:</b> {user.name}\n"
                f"<b>Reason:</b> {user.ban_reason or 'No reason provided'}\n"
                f"<b>Banned on:</b> {ban_date}"
            ), user
        update_data = {
            'status': UserStatus.BANNED.value,
            'ban_reason': reason,
            'updated_at': datetime.now(UTC)
        }

        success = await self.update(user_id, update_data)

        if success:
            await self.cache.delete(CacheKeyGenerator.user(user_id))
            await self.cache.delete(CacheKeyGenerator.banned_users())
            # Update cache with banned users list
            await self.refresh_banned_users_cache()
            user.status = UserStatus.BANNED
            user.ban_reason = reason
            user.updated_at = datetime.now(UTC)
            logger.info(f"User {user_id} banned and cache updated")

        return success, "✅ User banned successfully!" if success else "❌ Failed to ban user.", user

    async def unban_user(self, user_id: int) -> Tuple[bool, str, Optional[User]]:
        """Unban a user"""
        user = await self.get_user(user_id)
        if not user:
            return False, "❌ User not found in database.", None

        if user.status != UserStatus.BANNED:
            return False, f"❌ User <code>{user_id}</code> is not banned!", user

        # Reset request-related counters when unbanning
        update_data = {
            'status': UserStatus.ACTIVE.value,
            'ban_reason': None,
            'warning_count': 0,  # Reset warnings
            'daily_request_count': 0,  # Reset daily count
            'last_warning_date': None,
            'updated_at': datetime.now(UTC)
        }

        success = await self.update(user_id, update_data)

        if success:
            await self.cache.delete(CacheKeyGenerator.user(user_id))
            await self.refresh_banned_users_cache()

            user.status = UserStatus.ACTIVE
            user.ban_reason = None
            user.warning_count = 0
            user.daily_request_count = 0
            user.last_warning_date = None
            user.updated_at = datetime.now(UTC)
            logger.info(f"User {user_id} unbanned and request counters reset")

        return success, "✅ User unbanned successfully! Request counters have been reset." if success else "❌ Failed to unban user.", user

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
        await self.cache.set(cache_key, banned_ids, expire=self.ttl.USER_CONNECTIONS)

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
        update_data: Dict[str, Any] = {
            'is_premium': is_premium,
            'premium_activation_date': datetime.now(UTC) if is_premium else None,
            'updated_at': datetime.now(UTC)
        }

        if not is_premium:
            update_data['daily_retrieval_count'] = 0

        success = await self.update(user_id, update_data)
        if success:
            # Update user object
            user.is_premium = is_premium
            user.premium_activation_date = datetime.now(UTC) if is_premium else None
            user.updated_at = datetime.now(UTC)
            if not is_premium:
                user.daily_retrieval_count = 0
            await self.cache.delete(CacheKeyGenerator.user(user_id))

        action = "added" if is_premium else "removed"
        return success, f"✅ Premium status {action} successfully!" if success else f"❌ Failed to {action.replace('ed', '')} premium status.", user

    @cache_premium_status(ttl=600)  # Cache for 10 minutes
    async def check_and_update_premium_status(self, user: User) -> Tuple[bool, Optional[str]]:
        """Check and update premium status if expired"""
        if not user.is_premium:
            return False, None

        if not user.premium_activation_date:
            return False, None

        expiry_date = user.premium_activation_date + timedelta(days=self.premium_duration_days)

        if datetime.now(UTC) > expiry_date:
            # Premium expired
            await self.update_premium_status(user.id, False)
            return False, "Premium subscription expired"

        days_remaining = (expiry_date - datetime.now(UTC)).days
        return True, f"Premium active ({days_remaining} days remaining)"
    
    async def batch_check_premium_status(
        self, 
        user_ids: List[int]
    ) -> Dict[int, Tuple[bool, Optional[str]]]:
        """
        Batch premium status check to eliminate N+1 queries
        Uses optimized aggregation pipeline for bulk processing
        """
        if not user_ids:
            return {}
        
        # Use batch optimization if available, fallback to individual checks
        if self.batch_ops:
            try:
                return await self.batch_ops.batch_premium_status_check(user_ids)
            except Exception as e:
                logger.warning(f"Batch premium check failed, falling back: {e}")
        
        # Fallback to individual checks
        result = {}
        for user_id in user_ids:
            user = await self.get_user(user_id)
            if user:
                status, message = await self.check_and_update_premium_status(user)
                result[user_id] = (status, message)
            else:
                result[user_id] = (False, None)
        
        return result

    async def increment_retrieval_count(self, user_id: int) -> int:
        """Increment daily retrieval count using atomic operation to prevent race conditions"""
        today = date.today()
        today_str = today.isoformat()

        logger.info(f"increment_retrieval_count called for user {user_id}, today={today_str}")

        # First check if we need to reset the count (new day)
        user = await self.get_user(user_id)
        if not user:
            logger.error(f"User {user_id} not found in database!")
            # Create the user if they don't exist
            await self.create_user(user_id, "User")
            user = await self.get_user(user_id)
            if not user:
                logger.error(f"Failed to create user {user_id}")
                return 0

        logger.info(f"User {user_id} current count: {user.daily_retrieval_count}, last_date: {user.last_retrieval_date}")

        # If it's a new day, reset the count first
        if user.last_retrieval_date != today:
            # Reset count for new day
            collection = await self.collection
            result = await collection.update_one(
                {'_id': user_id},
                {
                    '$set': {
                        'daily_retrieval_count': 1,  # Set to 1 since we're incrementing
                        'last_retrieval_date': today_str,
                        'updated_at': datetime.now(UTC)
                    }
                }
            )
            logger.info(f"New day - reset count to 1 for user {user_id}, modified: {result.modified_count}")
            # Clear cache
            await self.cache.delete(CacheKeyGenerator.user(user_id))
            return 1

        # Use atomic increment for same day to prevent race conditions
        collection = await self.collection
        result = await collection.find_one_and_update(
            {'_id': user_id},
            {
                '$inc': {'daily_retrieval_count': 1},
                '$set': {
                    'last_retrieval_date': today_str,
                    'updated_at': datetime.now(UTC)
                }
            },
            return_document=True  # Return updated document
        )

        # Clear cache to ensure next read gets updated value
        await self.cache.delete(CacheKeyGenerator.user(user_id))

        if result:
            new_count = result.get('daily_retrieval_count', 0)
            logger.info(f"Incremented count for user {user_id} to {new_count}")
            return new_count
        else:
            logger.error(f"Failed to increment count for user {user_id}")
        return 0

    async def increment_retrieval_count_batch(self, user_id: int, count: int) -> int:
        """Increment daily retrieval count by specific amount (for batch operations)"""
        if count <= 0:
            return 0

        today = date.today()
        today_str = today.isoformat()

        logger.info(f"increment_retrieval_count_batch called for user {user_id}, count={count}, today={today_str}")

        # First check if we need to reset the count (new day)
        user = await self.get_user(user_id)
        if not user:
            logger.error(f"User {user_id} not found in database!")
            # Create the user if they don't exist
            await self.create_user(user_id, "User")
            user = await self.get_user(user_id)
            if not user:
                logger.error(f"Failed to create user {user_id}")
                return 0

        logger.info(f"User {user_id} current count: {user.daily_retrieval_count}, last_date: {user.last_retrieval_date}")

        # If it's a new day, reset the count first
        if user.last_retrieval_date != today:
            # Reset count for new day and add the batch count
            collection = await self.collection
            result = await collection.update_one(
                {'_id': user_id},
                {
                    '$set': {
                        'daily_retrieval_count': count,  # Set to the batch count
                        'last_retrieval_date': today_str,
                        'updated_at': datetime.now(UTC)
                    }
                }
            )
            logger.info(f"New day - set count to {count} for user {user_id}, modified: {result.modified_count}")
            # Clear cache
            await self.cache.delete(CacheKeyGenerator.user(user_id))
            return count

        # Use atomic increment for same day with batch count
        collection = await self.collection
        result = await collection.find_one_and_update(
            {'_id': user_id},
            {
                '$inc': {'daily_retrieval_count': count},
                '$set': {
                    'last_retrieval_date': today_str,
                    'updated_at': datetime.now(UTC)
                }
            },
            return_document=True  # Return updated document
        )

        # Clear cache to ensure next read gets updated value
        await self.cache.delete(CacheKeyGenerator.user(user_id))

        if result:
            new_count = result.get('daily_retrieval_count', 0)
            logger.info(f"Batch incremented count for user {user_id} by {count} to {new_count}")
            return new_count
        else:
            logger.error(f"Failed to batch increment count for user {user_id}")
        return 0

    async def can_retrieve_file(self, user_id: int, owner_id: Optional[int] = None) -> Tuple[bool, str]:
        """Check if user can retrieve a file"""
        # Check if premium is disabled
        from bot import BotConfig
        config = BotConfig()
        if config.DISABLE_PREMIUM:
            return True, "Unlimited access (Premium disabled)"

        # Check if user is admin
        is_admin = user_id in config.ADMINS if config.ADMINS else False
        if is_admin:
            return True, "Admin access"

        # Check if user is owner
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

        results = await self.aggregate(pipeline, limit=None)  # Stats need unlimited results
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
        cutoff_date = datetime.now(UTC) - timedelta(days=self.premium_duration_days)

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
                            'updated_at': datetime.now(UTC)
                        }}
                    )
                )

            if operations:
                await self.bulk_write(operations)

        return len(users)

    async def track_request(self, user_id: int) -> Tuple[bool, str, bool]:
        """
        Track a user request and apply limits
        Returns: (is_allowed, message, should_ban)
        """
        user = await self.get_user(user_id)
        if not user:
            # Create user if doesn't exist
            await self.create_user(user_id, "Unknown")
            user = await self.get_user(user_id)

        # Get settings from config
        from bot import BotConfig
        config = BotConfig()

        REQUEST_PER_DAY = config.REQUEST_PER_DAY if hasattr(config, 'REQUEST_PER_DAY') else 3
        REQUEST_WARNING_LIMIT = config.REQUEST_WARNING_LIMIT if hasattr(config, 'REQUEST_WARNING_LIMIT') else 5

        today = date.today()

        # Reset daily count if new day
        if user.last_request_date != today:
            user.daily_request_count = 0
            user.last_request_date = today

        # Check if user has warnings that should be reset (30 days old)
        if user.warning_count > 0 and user.last_warning_date:
            days_since_warning = (datetime.now(UTC) - user.last_warning_date).days
            if days_since_warning >= 30:
                await self.reset_warnings(user_id)
                user.warning_count = 0
                user.last_warning_date = None

        # Check warning limit first
        if user.warning_count >= REQUEST_WARNING_LIMIT:
            return False, f"You have been banned for exceeding warning limit ({REQUEST_WARNING_LIMIT} warnings)", True

        # Check daily limit
        if user.daily_request_count >= REQUEST_PER_DAY:
            # Issue a warning
            user.warning_count += 1
            user.last_warning_date = datetime.now(UTC)

            update_data = {
                'warning_count': user.warning_count,
                'last_warning_date': user.last_warning_date,
                'updated_at': datetime.now(UTC)
            }
            await self.update(user_id, update_data)
            await self.cache.delete(CacheKeyGenerator.user(user_id))

            remaining_warnings = REQUEST_WARNING_LIMIT - user.warning_count

            if user.warning_count >= REQUEST_WARNING_LIMIT:
                # Auto-ban the user
                return False, f"You have been banned for exceeding warning limit ({REQUEST_WARNING_LIMIT} warnings)", True
            else:
                return False, f"⚠️ Daily request limit ({REQUEST_PER_DAY}) exceeded! Warning {user.warning_count}/{REQUEST_WARNING_LIMIT}. You have {remaining_warnings} warnings left before ban.", False

        # Allow the request and increment counters
        user.daily_request_count += 1
        user.total_requests += 1

        update_data = {
            'daily_request_count': user.daily_request_count,
            'last_request_date': today.isoformat(),
            'total_requests': user.total_requests,
            'updated_at': datetime.now(UTC)
        }

        await self.update(user_id, update_data)
        await self.cache.delete(CacheKeyGenerator.user(user_id))

        remaining = REQUEST_PER_DAY - user.daily_request_count
        return True, f"Request recorded ({user.daily_request_count}/{REQUEST_PER_DAY}). {remaining} requests remaining today.", False

    async def reset_warnings(self, user_id: int) -> bool:
        """Reset warnings for a user"""
        update_data = {
            'warning_count': 0,
            'last_warning_date': None,
            'updated_at': datetime.now(UTC)
        }

        success = await self.update(user_id, update_data)
        if success:
            await self.cache.delete(CacheKeyGenerator.user(user_id))
        return success

    async def get_request_stats(self, user_id: int) -> Dict[str, Any]:
        """Get request statistics for a user"""
        user = await self.get_user(user_id)
        if not user:
            return {
                'exists': False
            }

        from bot import BotConfig
        config = BotConfig()
        REQUEST_PER_DAY = config.REQUEST_PER_DAY if hasattr(config, 'REQUEST_PER_DAY') else 3
        REQUEST_WARNING_LIMIT = config.REQUEST_WARNING_LIMIT if hasattr(config, 'REQUEST_WARNING_LIMIT') else 5

        today = date.today()
        daily_count = user.daily_request_count if user.last_request_date == today else 0

        # Calculate warning reset time
        warning_reset_in = None
        if user.warning_count > 0 and user.last_warning_date:
            days_since_warning = (datetime.now(UTC) - user.last_warning_date).days
            warning_reset_in = max(0, 30 - days_since_warning)

        return {
            'exists': True,
            'daily_requests': daily_count,
            'daily_limit': REQUEST_PER_DAY,
            'daily_remaining': max(0, REQUEST_PER_DAY - daily_count),
            'warning_count': user.warning_count,
            'warning_limit': REQUEST_WARNING_LIMIT,
            'warnings_remaining': max(0, REQUEST_WARNING_LIMIT - user.warning_count),
            'total_requests': user.total_requests,
            'last_request_date': user.last_request_date,
            'last_warning_date': user.last_warning_date,
            'warning_reset_in_days': warning_reset_in,
            'is_at_limit': daily_count >= REQUEST_PER_DAY,
            'is_warned': user.warning_count > 0
        }

    async def auto_ban_for_request_abuse(self, user_id: int) -> Tuple[bool, Optional[User]]:
        """Auto-ban user for request abuse"""
        user = await self.get_user(user_id)
        if not user:
            return False, None

        update_data = {
            'status': UserStatus.BANNED.value,
            'ban_reason': 'Over request warning limit',
            'updated_at': datetime.now(UTC)
        }

        success = await self.update(user_id, update_data)

        if success:
            await self.cache.delete(CacheKeyGenerator.user(user_id))
            await self.refresh_banned_users_cache()
            user.status = UserStatus.BANNED
            user.ban_reason = 'Over request warning limit'
            logger.info(f"User {user_id} auto-banned for request abuse")

        return success, user

    async def reset_daily_counters(self) -> int:
        """
        Reset daily counters for all users (for scheduled maintenance)
        Returns: Number of users updated
        """
        try:
            collection = await self.collection
            
            # Update all users to reset daily counters
            # This is typically run once per day via a scheduled task
            update_result = await self.db_pool.execute_with_retry(
                collection.update_many,
                {},  # Update all users
                {
                    '$set': {
                        'daily_retrieval_count': 0,
                        'daily_request_count': 0,
                        'updated_at': datetime.now(UTC)
                    }
                }
            )
            
            # Clear all user caches since we've updated all users
            # We can't efficiently clear individual user caches, so we use cache invalidation
            if hasattr(self, 'cache_invalidator'):
                await self.cache_invalidator.invalidate_pattern("user:*")
            else:
                # Fallback: try to clear common user cache patterns
                # This is not ideal but better than stale cache
                pass
            
            updated_count = update_result.modified_count if update_result else 0
            logger.info(f"Reset daily counters for {updated_count} users")
            return updated_count
            
        except Exception as e:
            logger.error(f"Error resetting daily counters: {e}")
            return 0
