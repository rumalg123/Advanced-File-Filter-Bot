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
