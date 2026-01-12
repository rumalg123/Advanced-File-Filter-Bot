"""
Application-wide constants for the bot
"""


class ProcessingConstants:
    """Constants related to processing operations"""

    # Cleanup intervals (in seconds)
    USER_COUNT_CLEANUP_INTERVAL = 3600  # 1 hour

    # Delete handler batch processing
    DELETE_BATCH_SIZE = 50
    DELETE_BATCH_TIMEOUT = 5
    DELETE_QUEUE_MAX_SIZE = 1000

    # Queue overflow handling
    QUEUE_HEADROOM_THRESHOLD = 10  # Headroom before moving from overflow
    QUEUE_MARGIN_THRESHOLD = 5  # Margin for queue fullness check
    WARNING_INTERVAL_SECONDS = 60  # One warning per minute
    ALERT_THRESHOLD_COUNT = 10  # Alert every N warnings

    # Broadcast processing
    BROADCAST_BATCH_SIZE = 50
    BROADCAST_DELAY_BETWEEN_BATCHES = 2  # seconds
    BROADCAST_PROGRESS_UPDATE_INTERVAL = 10  # Update every N users
    BROADCAST_CACHE_EXPIRE = 3600  # 1 hour TTL
    BROADCAST_ADAPTIVE_DELAY_THRESHOLD = 0.5  # Success rate threshold for adaptive delay
    BROADCAST_ADAPTIVE_DELAY_MULTIPLIER = 2  # Delay multiplier when success rate is low

    # Indexing processing
    INDEXING_BATCH_SIZE = 50
    MESSAGE_ITERATION_BATCH_SIZE = 200  # Batch size for message iteration

    # Queue processing
    QUEUE_DEADLINE_SECONDS = 5

    # Processing delays (in seconds)
    FLOOD_CONTROL_DELAY = 1  # Delay to avoid API flooding
    SMALL_PROCESSING_DELAY = 0.1  # Small delay between operations
    BATCH_PROCESSING_DELAY = 0.5  # Delay between batch items

    # Handler update intervals
    PERIODIC_HANDLER_UPDATE_INTERVAL = 60  # 1 minute
    OVERFLOW_QUEUE_WAIT_INTERVAL = 5  # seconds
    SESSION_CLEANUP_INTERVAL = 300  # 5 minutes
    TASK_STOP_TIMEOUT = 5.0  # Timeout for graceful task stop

    # FileStore processing
    BATCH_LINK_HASH_LENGTH = 16  # MD5 hash truncation for short refs
    BATCH_ID_UUID_LENGTH = 12  # UUID truncation for batch IDs
    DUPLICATE_BATCH_CHECK_LIMIT = 5  # Limit for duplicate batch link check

    # File send progress
    FILE_SEND_PROGRESS_INTERVAL = 5  # Update progress every N files

    # Delete handler timeouts
    QUEUE_WAIT_TIMEOUT_CAP = 5.0  # Max timeout for queue wait operations
    SHUTDOWN_WAIT_TIMEOUT = 1.0  # Timeout when waiting for shutdown signal
    ERROR_RETRY_WAIT = 5.0  # Wait time before retry after error

    # Deep link file sending
    SEND_ALL_FILES_LIMIT = 100  # Max files to retrieve for "send all" operations


class TelegramConstants:
    """Constants for Telegram API limits"""

    START_PARAM_MAX_LENGTH = 64  # Max length for start parameter in deep links
    MAX_MESSAGE_LENGTH = 4096  # Maximum characters in a Telegram message
    SLEEP_THRESHOLD = 5  # Pyrogram client sleep threshold for flood wait

    # Username validation
    USERNAME_MIN_LENGTH = 5
    USERNAME_MAX_LENGTH = 32

    # Chat ID handling
    CHAT_ID_THRESHOLD = 1000000000  # IDs >= this need negation for channels
    CHANNEL_ID_PREFIX = "-100"  # Prefix for private channel IDs

    # Batch operations
    MAX_BATCH_MESSAGE_COUNT = 10000  # Maximum messages in a batch operation

    # Inline keyboard limits
    MAX_BUTTONS_PER_ROW = 8  # Maximum buttons per row in inline keyboard


class PaginationConstants:
    """Constants for pagination display"""

    # React-style pagination thresholds
    NEAR_BEGINNING_THRESHOLD = 3  # Pages considered "near beginning"
    NEAR_END_OFFSET = 2  # Offset from end considered "near end"
    MAX_BEGINNING_PAGES = 6  # Max pages to show when near beginning
    PAGES_FROM_END = 4  # Pages to show from end when near end


class RateLimitConstants:
    """Default rate limit configurations"""

    # Search rate limits
    SEARCH_MAX_REQUESTS = 30
    SEARCH_TIME_WINDOW = 60  # seconds

    # File request rate limits
    FILE_REQUEST_MAX = 10
    FILE_REQUEST_WINDOW = 60  # seconds

    # Broadcast rate limits
    BROADCAST_MAX_REQUESTS = 1
    BROADCAST_TIME_WINDOW = 3600  # 1 hour

    # Inline query rate limits
    INLINE_QUERY_MAX = 50
    INLINE_QUERY_WINDOW = 60  # seconds

    # Premium check rate limits
    PREMIUM_CHECK_MAX = 100
    PREMIUM_CHECK_WINDOW = 60  # seconds

    # Default cooldown
    DEFAULT_COOLDOWN = 60  # seconds


class TimeConstants:
    """Time conversion constants"""

    SECONDS_PER_MINUTE = 60
    SECONDS_PER_HOUR = 3600
    SECONDS_PER_DAY = 86400
    HOURS_PER_DAY = 24
    MILLISECONDS_PER_SECOND = 1000


class ActivityConstants:
    """Constants for user activity tracking"""

    DEFAULT_ACTIVITY_DAYS = 30  # Default lookback period for activity aggregation


class UserConstants:
    """Constants for user-related operations"""

    WARNING_RESET_DAYS = 30  # Days after which warnings are reset


class MaintenanceConstants:
    """Constants for maintenance tasks"""

    # Daily maintenance loop (24 hours)
    DAILY_CHECK_ITERATIONS = 240  # Number of iterations
    DAILY_CHECK_INTERVAL = 360  # 6 minutes between checks (240 * 6min = 24 hours)

    # Hourly premium cleanup (1 hour)
    HOURLY_CHECK_ITERATIONS = 60  # Number of iterations
    HOURLY_CHECK_INTERVAL = 60  # 1 minute between checks (60 * 1min = 1 hour)

    # Startup and retry delays
    STARTUP_DELAY = 300  # 5 minutes delay before first hourly cleanup
    RETRY_DELAY = 300  # 5 minutes wait before retry on error


class DisplayConstants:
    """Constants for UI display"""

    FILE_NAME_DISPLAY_LENGTH = 50  # Max length for file names in buttons
    TEXT_PREVIEW_LENGTH = 200  # Max length for text previews
    LOG_SEPARATOR_LENGTH = 60  # Length of "=" separators in logs
    MAX_ADMINS_NOTIFY = 3  # Maximum admins to notify on critical errors

    # Hash/ID truncation for display
    FALLBACK_HASH_LENGTH = 20  # MD5 hash truncation for fallback refs
    FILE_UNIQUE_ID_DISPLAY_LENGTH = 10  # Truncation for file name generation
    SESSION_ID_LENGTH = 8  # UUID truncation for session IDs
    SHORT_HASH_LENGTH = 7  # Short git commit hash length

    # File extension validation
    VALID_EXTENSION_LENGTHS = (2, 3, 4, 5)  # Valid file extension lengths

    # Database usage display thresholds (percentages)
    DB_CRITICAL_USAGE_PERCENT = 90  # Critical usage threshold for display
    DB_HIGH_USAGE_PERCENT = 75  # High usage threshold for display
    DB_LOW_USAGE_PERCENT = 25  # Low usage threshold for display
    DB_WARNING_USAGE_PERCENT = 80  # Warning threshold for recommendations

    # URI display truncation
    URI_DISPLAY_LENGTH = 50  # Max length for URI display

    # List display limits
    MAX_DUPLICATES_DISPLAY = 5  # Max duplicate entries to show
    MAX_LARGE_VALUES_DISPLAY = 3  # Max large cache values to show

    # Auto-delete delays
    SUCCESS_MESSAGE_DELETE_DELAY = 10  # Seconds before auto-deleting success messages


class ByteConstants:
    """Constants for byte size conversions"""

    KB = 1024  # Bytes per kilobyte
    MB = 1024 * 1024  # Bytes per megabyte
    GB = 1024 * 1024 * 1024  # Bytes per gigabyte
    TB = 1024 * 1024 * 1024 * 1024  # Bytes per terabyte


class LoggingConstants:
    """Constants for logging configuration"""

    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB max log file size
    BACKUP_COUNT = 5  # Number of backup log files to keep
    MAX_LOG_DOWNLOAD_SIZE = 50 * 1024 * 1024  # 50MB max size for log file download


class DatabaseConstants:
    """Constants for database operations"""

    AGGREGATE_DEFAULT_LIMIT = 1000  # Default limit for aggregation queries
    REDIS_BATCH_DELETE_SIZE = 100  # Batch size for Redis bulk deletes
    MAX_BATCH_CACHE_SIZE = 100  # Max entries in batch cache
    DEFAULT_TTL_FALLBACK = 300  # 5 minutes default TTL
    DEFAULT_USER_BATCH_LINKS_LIMIT = 10  # Default limit for user batch links query

    # Connection pool settings (with uvloop)
    POOL_SIZE_UVLOOP = 200
    POOL_SIZE_DEFAULT = 100
    MIN_POOL_SIZE_UVLOOP = 20
    MIN_POOL_SIZE_DEFAULT = 10
    MAX_IDLE_TIME_UVLOOP = 600000  # 10 minutes in ms
    MAX_IDLE_TIME_DEFAULT = 300000  # 5 minutes in ms

    # Timeout settings (in milliseconds)
    SERVER_SELECTION_TIMEOUT = 15000
    CONNECT_TIMEOUT = 20000
    SOCKET_TIMEOUT = 20000
    WAIT_QUEUE_TIMEOUT_UVLOOP = 10000
    WAIT_QUEUE_TIMEOUT_DEFAULT = 5000
    WAIT_QUEUE_MULTIPLE_UVLOOP = 4
    WAIT_QUEUE_MULTIPLE_DEFAULT = 2

    # Retry settings
    MAX_RETRIES = 3
    CLOSE_SLEEP_DELAY = 0.1

    # Multi-database settings
    DEFAULT_SIZE_LIMIT_GB = 0.5
    DEFAULT_SEARCH_LIMIT = 10
    STATS_CACHE_DURATION = 30  # seconds

    # Circuit breaker defaults
    CIRCUIT_BREAKER_MAX_FAILURES = 5
    CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 300  # seconds
    CIRCUIT_BREAKER_HALF_OPEN_CALLS = 3


class DatabaseScoringWeights:
    """Weights and thresholds for database selection scoring algorithm"""

    # Score weights (must sum to ~1.0 with current bonus)
    STORAGE_WEIGHT = 0.40
    HEALTH_WEIGHT = 0.30
    STABILITY_WEIGHT = 0.15
    CURRENT_DB_BONUS = 0.15

    # Storage usage thresholds
    CRITICAL_USAGE_THRESHOLD = 0.9  # 90%
    HIGH_USAGE_THRESHOLD = 0.8  # 80%
    LOW_USAGE_THRESHOLD = 0.25  # 25%

    # Penalties and bonuses
    CRITICAL_USAGE_PENALTY = 0.3
    HIGH_USAGE_PENALTY = 0.7
    LOW_USAGE_BONUS = 0.1
    HEALTH_PENALTY_FACTOR = 0.7

    # Health scores by state
    HALF_OPEN_HEALTH_SCORE = 0.5
    OPEN_HEALTH_SCORE = 0.0
    MIN_HEALTH_SCORE = 0.3

    # Stability scores
    DEFAULT_STABILITY = 0.8
    HIGH_STABILITY = 1.0
    LOW_STABILITY = 0.3
    STABILITY_PENALTY = 0.4
    STABILITY_BONUS = 0.2


class CacheConstants:
    """Constants for cache operations"""

    # Serialization
    COMPRESSION_THRESHOLD = 1024  # 1KB - minimum size before considering compression
    DEFAULT_COMPRESSION_LEVEL = 6  # zlib compression level (1-9)
    COMPRESSION_MIN_SAVINGS = 0.9  # Only compress if result is < 90% of original

    # Cache monitoring thresholds
    LARGE_VALUE_THRESHOLD = 10240  # 10KB - threshold for "large" cache values
    EXPIRING_SOON_THRESHOLD = 60  # 60 seconds - threshold for "expiring soon"
    DEFAULT_SAMPLE_SIZE = 100  # Default sample size for cache analysis
    SERIALIZATION_SAMPLE_SIZE = 20  # Sample size for serialization analysis

    # Size categories (in bytes)
    SIZE_1KB = 1024
    SIZE_10KB = 10240
    SIZE_100KB = 102400
    SIZE_1MB = 1048576

    # Redis connection settings
    REDIS_MAX_CONNECTIONS_UVLOOP = 40  # Max connections when using uvloop
    REDIS_MAX_CONNECTIONS_DEFAULT = 20  # Max connections with standard asyncio
    REDIS_SOCKET_TIMEOUT = 30.0  # Socket operations timeout (seconds)
    REDIS_CONNECT_TIMEOUT = 10.0  # Initial connection timeout (seconds)

    # Key generator cache
    KEY_CACHE_MAX_SIZE = 1000  # Max cached keys in CacheKeyGenerator

    # Cache invalidation
    FULL_INVALIDATION_COOLDOWN = 5.0  # Seconds between full invalidations


class ConcurrencyDefaults:
    """Default concurrency limits for semaphore operations"""

    TELEGRAM_SEND = 10
    TELEGRAM_FETCH = 15
    TELEGRAM_GENERAL = 10
    DATABASE_WRITE = 20
    DATABASE_READ = 30
    FILE_PROCESSING = 5
    BROADCAST = 3
    INDEXING = 8
    DEFAULT_FALLBACK = 10  # Fallback limit for unknown domains


class APIRetryConstants:
    """Constants for API retry and backoff settings"""

    # Retry settings
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_BASE_DELAY = 1.0  # seconds

    # Jitter range for flood wait handling
    JITTER_MIN = 0.1
    JITTER_MAX = 0.5

    # Exponential backoff base
    BACKOFF_BASE = 2

    # Fallback flood wait value when retries exhausted
    FALLBACK_FLOOD_WAIT = 60  # seconds


class ValidationLimits:
    """Constants for input validation limits"""

    # Pagination limits
    MIN_PAGE_NUMBER = 1
    MIN_ITEMS_PER_PAGE = 1
    MAX_ITEMS_PER_PAGE = 100

    # Input length limits
    MAX_FILENAME_LENGTH = 255
    MAX_SEARCH_QUERY_LENGTH = 100
    MAX_CAPTION_LENGTH = 1024

    # Command argument limits
    DEFAULT_MIN_ARGS = 0
    DEFAULT_MAX_ARGS = 10

    # Callback data format
    MIN_CALLBACK_PARTS = 2  # Minimum parts for valid callback (action#data)
    CALLBACK_PARTS_WITH_USER = 3  # Callback parts including user ID


class SettingsConstants:
    """Constants for bot settings UI"""

    SETTINGS_PER_PAGE = 8  # Number of settings per page
    SETTINGS_PER_ROW = 2  # Number of setting buttons per row
    MAX_PAGE_BUTTONS = 11  # Maximum number of page buttons to show
    BUTTONS_PER_NAV_ROW = 5  # Buttons per navigation row
    NEAR_BEGINNING_PAGES = 4  # Pages considered "near beginning"
    NEAR_END_PAGES = 4  # Pages considered "near end"
    VISIBLE_PAGES_RANGE = 7  # Number of visible pages when not at edges
    MIDDLE_RANGE_OFFSET = 2  # Pages before current in middle view
    MIDDLE_RANGE_SIZE = 5  # Total pages shown in middle (page-2 to page+2)


class ShellConstants:
    """Constants for shell command execution"""

    COMMAND_TIMEOUT = 300  # 5 minutes max for shell commands
    CACHE_ANALYSIS_SAMPLE_SIZE = 15  # Sample size for cache serialization analysis


class HealthCheckConstants:
    """Constants for health check and alignment verification"""

    # Health score settings
    BASE_HEALTH_SCORE = 50
    MAX_HEALTH_SCORE = 100
    MIN_HEALTH_SCORE = 0

    # Scoring multipliers
    ISSUE_PENALTY = 10
    WARNING_PENALTY = 3
    SUCCESS_BONUS = 5

    # Health thresholds
    GOOD_HEALTH_THRESHOLD = 80
    WARNING_HEALTH_THRESHOLD = 60

    # Display limits
    MAX_SUCCESSES_DISPLAY = 10
    MAX_WARNINGS_DISPLAY = 5

    # Task thresholds
    EXPECTED_MAX_ACTIVE_TASKS = 50


class HandlerPriorityConstants:
    """Constants for Pyrogram handler group priorities"""

    # Lower numbers = higher priority (processed first)
    CANCEL_HANDLER = -10  # Highest priority for cancel commands
    EDIT_INPUT_HANDLER = -5  # High priority for settings input
    DEFAULT_HANDLER = 0  # Default handler group
    SEARCH_HANDLER = 10  # Lower priority for search handlers


class ManagerConstants:
    """Constants for handler manager operations"""

    LOG_SEPARATOR_WIDTH = 60  # Width of separator lines in logs
    CLEANUP_TIMEOUT = 5.0  # Timeout for cleanup operations


class SystemConstants:
    """Constants for system-level configuration"""

    FILE_DESCRIPTOR_LIMIT = 100000  # File descriptor limit for Linux systems


class SearchConstants:
    """Constants for search functionality"""

    # Search query limits
    MIN_QUERY_LENGTH = 2  # Minimum characters required for search
    INLINE_RESULTS_LIMIT = 10  # Max results to show in inline mode

    # Commands to exclude from text search
    EXCLUDED_COMMANDS = [
        'start', 'help', 'about', 'stats', 'plans',
        'broadcast', 'users', 'ban', 'unban', 'addpremium', 'removepremium',
        'add_channel', 'remove_channel', 'list_channels', 'toggle_channel',
        'connect', 'disconnect', 'connections', 'setskip',
        'delete', 'deleteall', 'link', 'plink', 'batch', 'pbatch',
        'batch_premium', 'pbatch_premium', 'bprem', 'pbprem',
        'viewfilters', 'filters', 'del', 'delall', 'delallf', 'deleteallf',
        'delf', 'deletef', 'add', 'filter', 'bsetting', 'restart', 'shell',
        'cache_stats', 'cache_analyze', 'cache_cleanup', 'log', 'performance',
        'cancel', 'dbstats', 'dbinfo', 'dbswitch', 'verify', 'request_stats',
        'stop_broadcast', 'reset_broadcast_limit'
    ]
