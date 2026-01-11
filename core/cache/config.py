from dataclasses import dataclass
from typing import Optional, List


@dataclass
class CacheTTLConfig:
    """Centralized TTL configuration for all cached data"""

    # User related
    USER_DATA: int = 300  # 5 minutes
    BANNED_USERS_LIST: int = 3600  # 1 hour
    USER_STATS: int = 600  # 10 minutes

    # Media related
    MEDIA_FILE: int = 300  # 5 minutes
    SEARCH_RESULTS: int = 300  # 5 minutes
    FILE_STATS: int = 1800  # 30 minutes

    # Connection related
    USER_CONNECTIONS: int = 300  # 5 minutes
    CONNECTION_STATS: int = 1800  # 30 minutes

    # Channel related
    ACTIVE_CHANNELS: int = 600  # 10 minutes
    CHANNEL_STATS: int = 1800  # 30 minutes

    # Filter related
    FILTER_DATA: int = 300  # 5 minutes
    FILTER_LIST: int = 600  # 10 minutes

    # Bot settings
    BOT_SETTINGS: int = 1800  # 30 minutes

    # Rate limiting
    RATE_LIMIT_WINDOW: int = 60  # 1 minute

    # Session data
    EDIT_SESSION: int = 60  # 1 minute
    SEARCH_SESSION: int = 3600  # 1 hour

    # Temporary flags
    RECENT_EDIT_FLAG: int = 2  # 2 seconds
    OPERATION_LOCK: int = 10  # 10 seconds for operation locks
    
    # Batch links
    BATCH_LINK: int = 86400  # 24 hours for batch links
    
    # Rate limiting
    RATE_LIMIT_COOLDOWN: int = 3600  # 1 hour for rate limit cooldowns
    
    # Timing delays (in seconds)
    CHANNEL_INDEX_DELAY: int = 5  # Channel indexing delay
    INDEXING_FLOOD_DELAY: int = 2  # Anti-flood delay during indexing
    FILE_OPERATION_DELAY: int = 1  # File operation delay
    MAINTENANCE_CHECK_INTERVAL: int = 360  # 6 minutes
    MAINTENANCE_RETRY_DELAY: int = 3600  # 1 hour on error
    MAINTENANCE_RESET_DAILY_COUNTERS: int = 90000  # 25 hours


class CacheKeyGenerator:
    """Centralized cache key generation to ensure consistency"""
    
    # Cache for frequently used keys to reduce string operations
    _key_cache = {}
    _max_cache_size = 1000
    
    @classmethod
    def _get_cached_key(cls, key_type: str, *args) -> str:
        """Get cached key or generate and cache it"""
        cache_key = f"{key_type}:{':'.join(map(str, args))}"
        
        if cache_key in cls._key_cache:
            return cls._key_cache[cache_key]
        
        # Generate the actual key
        if key_type == 'user':
            result = f"user:{args[0]}"
        elif key_type == 'media':
            result = f"media:{args[0]}"
        elif key_type == 'search':
            result = f"search:{args[0]}:{args[1]}:{args[2]}:{args[3]}:{args[4]}"
        elif key_type == 'rate_limit':
            result = f"rate_limit:{args[0]}:{args[1]}"
        else:
            # Fallback to original generation
            return cache_key
        
        # Cache the result if we have space
        if len(cls._key_cache) < cls._max_cache_size:
            cls._key_cache[cache_key] = result
        
        return result

    # User keys
    @staticmethod
    def user(user_id: int) -> str:
        return CacheKeyGenerator._get_cached_key('user', user_id)

    @staticmethod
    def banned_users() -> str:
        return "banned_users"

    @staticmethod
    def user_stats() -> str:
        return "user_stats"

    # Media keys
    @staticmethod
    def media(identifier: str) -> str:
        return CacheKeyGenerator._get_cached_key('media', identifier)

    @staticmethod
    def search_results(query: str, file_type: Optional[str], offset: int,
                       limit: int, use_caption: bool = True) -> str:
        # Normalize query for consistent caching
        normalized_query = query.lower().strip()
        return CacheKeyGenerator._get_cached_key('search', normalized_query, file_type, offset, limit, use_caption)

    @staticmethod
    def search_results_versioned(query: str, file_type: Optional[str], offset: int,
                                  limit: int, use_caption: bool, cache_version: int) -> str:
        """Generate versioned search results cache key"""
        base_key = CacheKeyGenerator.search_results(query, file_type, offset, limit, use_caption)
        return f"{base_key}:v{cache_version}"

    @staticmethod
    def file_stats() -> str:
        return "file_stats"

    # Connection keys
    @staticmethod
    def user_connections(user_id: str) -> str:
        return f"connections:{user_id}"

    # Channel keys
    @staticmethod
    def active_channels() -> str:
        return "active_channels_list"

    @staticmethod
    def channel(channel_id: int) -> str:
        return f"channel:{channel_id}"

    # Filter keys
    @staticmethod
    def filter(group_id: str, text: str) -> str:
        return f"filter:{group_id}:{text}"

    @staticmethod
    def filter_generic(identifier: str) -> str:
        """Generic filter key for non-standard identifiers"""
        return f"filter:{identifier}"

    @staticmethod
    def filter_list(group_id: str) -> str:
        return f"filters_list:{group_id}"

    # Bot settings keys
    @staticmethod
    def bot_setting(key: str) -> str:
        return f"bot_setting:{key}"

    @staticmethod
    def all_settings() -> str:
        return "all_bot_settings"

    # Rate limit keys
    @staticmethod
    def rate_limit(user_id: int, action: str) -> str:
        return CacheKeyGenerator._get_cached_key('rate_limit', user_id, action)

    @staticmethod
    def rate_limit_cooldown(user_id: int, action: str) -> str:
        return f"rate_limit:{user_id}:{action}:cooldown"

    # Session keys
    @staticmethod
    def search_session(user_id: int, session_id: str) -> str:
        return f"search_results_{user_id}_{session_id}"

    # Temporary flags
    @staticmethod
    def recent_settings_edit(user_id: int) -> str:
        return f"recent_settings_edit:{user_id}"

    # Counter reset data
    @staticmethod
    def last_counter_reset_date() -> str:
        return "last_counter_reset_date"
    
    # Batch link keys
    @staticmethod
    def batch_link(batch_id: str) -> str:
        return f"batch_link:{batch_id}"

    # Delete operation keys
    @staticmethod
    def deleteall_pending(user_id: int) -> str:
        return f"deleteall_pending:{user_id}"

    # Premium status keys
    @staticmethod
    def premium_status(user_id: int) -> str:
        return f"premium_status:{user_id}"

    # Broadcast keys
    @staticmethod
    def broadcast_state() -> str:
        return "broadcast:state"

    # Session keys
    @staticmethod
    def session(session_type: str, user_id: int, session_id: str = None) -> str:
        if session_id:
            return f"session:{session_type}:{user_id}:{session_id}"
        return f"session:{session_type}:{user_id}"

    # Token bucket keys (for distributed rate limiting)
    @staticmethod
    def token_bucket(key: str) -> str:
        return f"token_bucket:{key}"

    # Subscription session keys
    @staticmethod
    def subscription_session(session_id: str) -> str:
        return f"checksub_session:{session_id}"


# Cache patterns to identify related keys for bulk operations
class CachePatterns:
    """Patterns for bulk cache operations"""

    # Pattern constants
    ALL_SESSIONS = "session:*"
    ALL_RATE_LIMITS = "rate_limit:*"
    ALL_SEARCH_RESULTS = "search_results_*"
    ALL_FILTERS = "filter:*"
    ALL_FILTER_LISTS = "filters_list:*"
    ALL_USERS = "user:*"
    ALL_CHANNELS = "channel:*"
    ALL_SUBSCRIPTIONS = "subscription:*"
    ALL_FILESTORE = "filestore:*"
    ALL_SEARCH_CACHE = "search:*"
    ALL_MEDIA = "media:*"
    ALL_CONNECTIONS = "connections:*"
    ALL_BOT_SETTINGS = "bot_setting:*"
    ANY_SESSION = "*session*"

    @staticmethod
    def rate_limit_pattern(user_id: int) -> str:
        """Pattern for all rate limits for a user"""
        return f"rate_limit:{user_id}:*"

    @staticmethod
    def search_results_pattern(user_id: int) -> str:
        """Pattern for all search results for a user"""
        return f"search_results_{user_id}_*"

    @staticmethod
    def user_related(user_id: int) -> List[str]:
        """Get all cache keys related to a user"""
        return [
            CacheKeyGenerator.user(user_id),
            CacheKeyGenerator.user_connections(str(user_id)),
            CachePatterns.rate_limit_pattern(user_id),
            CachePatterns.search_results_pattern(user_id),
            CacheKeyGenerator.recent_settings_edit(user_id)
        ]

