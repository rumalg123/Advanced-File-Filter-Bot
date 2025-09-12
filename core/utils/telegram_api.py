"""
Centralized Telegram API wrapper with robust flood handling and rate limiting
"""
import asyncio
import random
from typing import Any, Callable, Dict, Optional
from functools import wraps

from pyrogram import Client
from pyrogram.errors import FloodWait, RPCError
from core.utils.logger import get_logger

# Import concurrency control
try:
    from core.concurrency.semaphore_manager import semaphore_manager
    CONCURRENCY_CONTROL_AVAILABLE = True
except ImportError:
    CONCURRENCY_CONTROL_AVAILABLE = False

logger = get_logger(__name__)


class TelegramAPIWrapper:
    """Wrapper for Telegram API calls with flood control and rate limiting"""
    
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        # Per-chat semaphores to prevent overwhelming specific chats
        self._chat_semaphores: Dict[int, asyncio.Semaphore] = {}
        # Global semaphore for overall API rate limiting
        self._global_semaphore = asyncio.Semaphore(10)  # Max 10 concurrent API calls
        
    def get_chat_semaphore(self, chat_id: int) -> asyncio.Semaphore:
        """Get or create a semaphore for specific chat"""
        if chat_id not in self._chat_semaphores:
            self._chat_semaphores[chat_id] = asyncio.Semaphore(3)  # Max 3 concurrent per chat
        return self._chat_semaphores[chat_id]
    
    async def call_api(
        self, 
        api_func: Callable,
        *args,
        chat_id: Optional[int] = None,
        **kwargs
    ) -> Any:
        """
        Execute API call with flood protection and rate limiting
        
        Args:
            api_func: The API function to call
            chat_id: Optional chat ID for per-chat rate limiting
            *args, **kwargs: Arguments passed to the API function
        """
        retries = 0
        last_exception = None
        
        # Determine operation domain for concurrency control
        func_name = getattr(api_func, '__name__', 'unknown')
        if 'send' in func_name.lower():
            domain = 'telegram_send'
        elif 'get' in func_name.lower() or 'fetch' in func_name.lower():
            domain = 'telegram_fetch'
        else:
            domain = 'telegram_general'
        
        # Use global semaphore manager if available, fallback to local semaphores
        if CONCURRENCY_CONTROL_AVAILABLE:
            async with semaphore_manager.acquire(domain, f"{func_name}_{chat_id or 'global'}"):
                return await self._execute_with_retry(api_func, *args, **kwargs)
        else:
            # Fallback to original semaphore logic
            async with self._global_semaphore:
                if chat_id:
                    chat_sem = self.get_chat_semaphore(chat_id)
                    async with chat_sem:
                        return await self._execute_with_retry(api_func, *args, **kwargs)
                else:
                    return await self._execute_with_retry(api_func, *args, **kwargs)
    
    async def _execute_with_retry(self, api_func: Callable, *args, **kwargs) -> Any:
        """Execute API call with retry logic"""
        retries = 0
        
        while retries < self.max_retries:
            try:
                result = await api_func(*args, **kwargs)
                
                # Log successful API call for monitoring
                logger.debug(f"API call successful: {api_func.__name__}")
                return result
                
            except FloodWait as e:
                # Honor Telegram's retry_after with jitter
                retry_after = e.value
                jitter = random.uniform(0.1, 0.5)  # Add small random delay
                wait_time = retry_after + jitter
                
                logger.warning(
                    f"FloodWait received for {api_func.__name__}: "
                    f"waiting {wait_time:.2f}s (retry {retries + 1}/{self.max_retries})"
                )
                
                # Structured logging for monitoring
                logger.info(f"FloodWait handling", extra={
                    "event": "flood_wait",
                    "api_function": api_func.__name__,
                    "retry_after": retry_after,
                    "wait_time": wait_time,
                    "retry_count": retries + 1
                })
                
                await asyncio.sleep(wait_time)
                retries += 1
                
            except RPCError as e:
                # Log RPC errors but don't retry for client errors (4xx)
                if str(e.ID).startswith('4'):
                    logger.error(f"Client error in {api_func.__name__}: {e}")
                    raise e
                
                # Retry for server errors (5xx) with exponential backoff
                if retries < self.max_retries - 1:
                    delay = self.base_delay * (2 ** retries) + random.uniform(0.1, 0.5)
                    logger.warning(f"Server error in {api_func.__name__}: {e}, retrying in {delay:.2f}s")
                    await asyncio.sleep(delay)
                    retries += 1
                else:
                    logger.error(f"Max retries exceeded for {api_func.__name__}: {e}")
                    raise e
                    
            except Exception as e:
                logger.error(f"Unexpected error in {api_func.__name__}: {e}")
                raise e
        
        # If we get here, all retries were flood waits
        logger.error(f"All retries exhausted due to flood waits for {api_func.__name__}")
        raise FloodWait(value=60)  # Give up with a 60-second flood wait


# Global instance
telegram_api = TelegramAPIWrapper()


def with_flood_protection(chat_id_param: Optional[str] = None):
    """
    Decorator to add flood protection to API calls
    
    Args:
        chat_id_param: Name of the parameter containing chat_id for per-chat limiting
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract chat_id if specified
            chat_id = None
            if chat_id_param:
                if chat_id_param in kwargs:
                    chat_id = kwargs[chat_id_param]
                elif len(args) > 0 and hasattr(args[0], chat_id_param):
                    chat_id = getattr(args[0], chat_id_param)
            
            return await telegram_api.call_api(func, *args, chat_id=chat_id, **kwargs)
        return wrapper
    return decorator