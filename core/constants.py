"""
Application-wide constants for the bot
"""


class ProcessingConstants:
    """Constants related to processing operations"""

    # Cleanup intervals (in seconds)
    USER_COUNT_CLEANUP_INTERVAL = 3600  # 1 hour
    HANDLER_UPDATE_INTERVAL = 60  # 1 minute

    # Delete handler batch processing
    DELETE_BATCH_SIZE = 50
    DELETE_BATCH_TIMEOUT = 5
    DELETE_INTER_ITEM_DELAY = 0.1

    # Queue warning throttling
    QUEUE_WARNING_INTERVAL = 60
    QUEUE_WARNING_LOG_THRESHOLD = 10
