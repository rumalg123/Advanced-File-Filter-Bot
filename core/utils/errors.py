"""
Unified error response schema and utilities
"""
import uuid
from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass

from core.utils.logger import get_logger

logger = get_logger(__name__)


class ErrorCode(Enum):
    """Standardized error codes across the application"""
    # Authentication & Authorization
    AUTH_REQUIRED = "AUTH_REQUIRED"
    INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"
    BANNED_USER = "BANNED_USER"
    PREMIUM_REQUIRED = "PREMIUM_REQUIRED"
    
    # Rate Limiting
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    FLOOD_WAIT = "FLOOD_WAIT"
    
    # Validation
    INVALID_INPUT = "INVALID_INPUT"
    INVALID_LINK = "INVALID_LINK"
    INVALID_FILE_TYPE = "INVALID_FILE_TYPE"
    
    # Database
    DATABASE_ERROR = "DATABASE_ERROR"
    NOT_FOUND = "NOT_FOUND"
    DUPLICATE_ENTRY = "DUPLICATE_ENTRY"
    
    # External Services
    TELEGRAM_API_ERROR = "TELEGRAM_API_ERROR"
    CHANNEL_ACCESS_DENIED = "CHANNEL_ACCESS_DENIED"
    
    # System
    SYSTEM_ERROR = "SYSTEM_ERROR"
    TIMEOUT = "TIMEOUT"
    MAINTENANCE_MODE = "MAINTENANCE_MODE"


@dataclass
class ErrorResponse:
    """Unified error response format"""
    ok: bool = False
    code: str = ""
    message: str = ""
    correlation_id: str = ""
    details: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses"""
        result = {
            "ok": self.ok,
            "code": self.code,
            "message": self.message,
            "correlation_id": self.correlation_id
        }
        if self.details:
            result["details"] = self.details
        return result


@dataclass 
class SuccessResponse:
    """Unified success response format"""
    ok: bool = True
    data: Optional[Any] = None
    correlation_id: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses"""
        result = {
            "ok": self.ok,
            "correlation_id": self.correlation_id
        }
        if self.data is not None:
            result["data"] = self.data
        return result


class ErrorFactory:
    """Factory for creating standardized error responses"""
    
    @staticmethod
    def create_error(
        code: ErrorCode,
        message: str,
        correlation_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None
    ) -> ErrorResponse:
        """Create a standardized error response"""
        if not correlation_id:
            correlation_id = str(uuid.uuid4())[:8]
            
        error = ErrorResponse(
            ok=False,
            code=code.value,
            message=message,
            correlation_id=correlation_id,
            details=details or {}
        )
        
        # Structured logging
        logger.warning(
            f"Error response created: {code.value}",
            extra={
                "event": "error_response",
                "error_code": code.value,
                "correlation_id": correlation_id,
                "user_id": user_id,
                "message": message,
                "outcome": "error"
            }
        )
        
        return error
    
    @staticmethod
    def create_success(
        data: Optional[Any] = None,
        correlation_id: Optional[str] = None,
        user_id: Optional[int] = None
    ) -> SuccessResponse:
        """Create a standardized success response"""
        if not correlation_id:
            correlation_id = str(uuid.uuid4())[:8]
            
        response = SuccessResponse(
            ok=True,
            data=data,
            correlation_id=correlation_id
        )
        
        # Structured logging for success
        logger.info(
            "Success response created",
            extra={
                "event": "success_response",
                "correlation_id": correlation_id,
                "user_id": user_id,
                "outcome": "success"
            }
        )
        
        return response


# Common error responses for quick access
ERRORS = {
    "auth_required": lambda: ErrorFactory.create_error(
        ErrorCode.AUTH_REQUIRED,
        "Authentication required"
    ),
    "premium_required": lambda: ErrorFactory.create_error(
        ErrorCode.PREMIUM_REQUIRED,
        "Premium membership required"
    ),
    "banned_user": lambda: ErrorFactory.create_error(
        ErrorCode.BANNED_USER,
        "User is banned from using this bot"
    ),
    "invalid_input": lambda msg: ErrorFactory.create_error(
        ErrorCode.INVALID_INPUT,
        msg
    ),
    "system_error": lambda: ErrorFactory.create_error(
        ErrorCode.SYSTEM_ERROR,
        "An internal error occurred. Please try again."
    )
}