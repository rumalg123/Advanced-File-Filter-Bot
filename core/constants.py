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


class SearchConstants:
    """Constants for search functionality"""

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
