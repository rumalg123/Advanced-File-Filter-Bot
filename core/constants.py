"""
Application-wide constants for the bot
These are magic numbers extracted from the codebase for maintainability
"""


class ProcessingConstants:
    """Constants related to processing operations"""

    # Cleanup intervals (in seconds)
    USER_COUNT_CLEANUP_INTERVAL = 3600  # 1 hour - cleanup old user message counts
    HANDLER_UPDATE_INTERVAL = 60  # 1 minute - periodic handler updates

    # Delete handler batch processing
    DELETE_BATCH_SIZE = 50  # Maximum items to process in a single delete batch
    DELETE_BATCH_TIMEOUT = 5  # Seconds to wait for batch to fill
    DELETE_INTER_ITEM_DELAY = 0.1  # Delay between deleting items

    # Queue warning throttling
    QUEUE_WARNING_INTERVAL = 60  # Seconds between queue overflow warnings
    QUEUE_WARNING_LOG_THRESHOLD = 10  # Log to channel every N warnings


class FileSizeConstants:
    """File size limits in bytes"""

    # Log file size limits
    LOG_FILE_MAX_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

    # Telegram file size limits
    TELEGRAM_MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB (Telegram limit)
    TELEGRAM_PHOTO_MAX_SIZE = 10 * 1024 * 1024  # 10 MB for photos


class ShellCommandConstants:
    """Shell command execution constants"""

    # Timeout in seconds for shell commands
    DEFAULT_TIMEOUT = 300  # 5 minutes
    MAX_TIMEOUT = 3600  # 1 hour maximum

    # Output limits
    MAX_OUTPUT_LENGTH = 4096  # Telegram message limit
    MAX_FILE_OUTPUT_LINES = 1000  # Max lines to capture for file output


class CacheConstants:
    """Cache-related constants (supplements CacheTTLConfig)"""

    # Search session limits
    MAX_SEARCH_RESULTS_CACHED = 100  # Maximum search results to cache per session

    # Rate limiting
    RATE_LIMIT_WINDOW = 60  # Seconds for rate limit window


class PaginationConstants:
    """Pagination-related constants"""

    # Button layout
    MAX_BUTTONS_PER_ROW = 8
    DEFAULT_PAGE_SIZE = 10

    # File name display
    MAX_FILENAME_DISPLAY_LENGTH = 50


class IndexingConstants:
    """Indexing-related constants"""

    # Progress update frequency
    PROGRESS_UPDATE_INTERVAL = 100  # Update every N messages

    # Batch sizes for indexing
    INDEX_BATCH_SIZE = 50

    # Delays
    INTER_MESSAGE_DELAY = 0.5  # Seconds between processing messages
