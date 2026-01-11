"""
Custom exceptions for the bot application
"""


class BotException(Exception):
    """Base exception for all bot-related errors"""
    pass


class ConfigurationError(BotException):
    """Raised when there's a configuration issue"""
    pass


class DatabaseError(BotException):
    """Raised when there's a database operation error"""
    pass


class CacheError(BotException):
    """Raised when there's a cache operation error"""
    pass


class RateLimitError(BotException):
    """Raised when rate limit is exceeded"""

    def __init__(self, message: str = "Rate limit exceeded", cooldown: int = 0):
        self.cooldown = cooldown
        super().__init__(message)


class FileNotFoundError(BotException):
    """Raised when a requested file is not found"""
    pass


class AccessDeniedError(BotException):
    """Raised when user doesn't have access to a resource"""
    pass


class PremiumRequiredError(AccessDeniedError):
    """Raised when premium subscription is required"""
    pass


class SubscriptionRequiredError(AccessDeniedError):
    """Raised when channel subscription is required"""
    pass


class UserBannedError(AccessDeniedError):
    """Raised when a banned user tries to access the bot"""
    pass


class ValidationError(BotException):
    """Raised when input validation fails"""
    pass


class IndexingError(BotException):
    """Raised when there's an error during channel indexing"""
    pass


class BroadcastError(BotException):
    """Raised when there's an error during broadcast"""
    pass
