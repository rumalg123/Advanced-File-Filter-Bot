"""
Centralized concurrency control using asyncio.Semaphore
Provides bounded concurrency for different operation domains
"""

import asyncio
import time
from typing import Dict, Optional, Any
from dataclasses import dataclass, field
from contextlib import asynccontextmanager

from core.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ConcurrencyMetrics:
    """Metrics for concurrency monitoring"""
    domain: str
    max_concurrent: int
    current_active: int = 0
    peak_concurrent: int = 0
    total_requests: int = 0
    queue_length: int = 0
    avg_wait_time: float = 0.0
    start_times: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "max_concurrent": self.max_concurrent,
            "current_active": self.current_active,
            "peak_concurrent": self.peak_concurrent,
            "total_requests": self.total_requests,
            "queue_length": self.queue_length,
            "avg_wait_time": self.avg_wait_time
        }


class SemaphoreManager:
    """Manages asyncio.Semaphore instances for different operation domains"""
    
    # Default concurrency limits by domain
    DEFAULT_LIMITS = {
        'telegram_send': 10,      # Telegram API sends
        'telegram_fetch': 15,     # Telegram API fetches  
        'database_write': 20,     # Database writes
        'database_read': 30,      # Database reads
        'file_processing': 5,     # File processing operations
        'broadcast': 3,           # Broadcasting operations
        'indexing': 8,            # Channel indexing
        'cache_operations': 25,   # Cache operations
    }
    
    def __init__(self, custom_limits: Optional[Dict[str, int]] = None):
        """
        Initialize semaphore manager with custom limits
        
        Args:
            custom_limits: Override default limits for specific domains
        """
        self.limits = {**self.DEFAULT_LIMITS}
        if custom_limits:
            self.limits.update(custom_limits)
        
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
        self._metrics: Dict[str, ConcurrencyMetrics] = {}
        self._lock = asyncio.Lock()
        
        # Initialize semaphores and metrics
        for domain, limit in self.limits.items():
            self._semaphores[domain] = asyncio.Semaphore(limit)
            self._metrics[domain] = ConcurrencyMetrics(
                domain=domain,
                max_concurrent=limit
            )
    
    def get_semaphore(self, domain: str) -> asyncio.Semaphore:
        """Get semaphore for domain, create if doesn't exist"""
        if domain not in self._semaphores:
            limit = self.limits.get(domain, 10)  # Default limit
            self._semaphores[domain] = asyncio.Semaphore(limit)
            self._metrics[domain] = ConcurrencyMetrics(
                domain=domain,
                max_concurrent=limit
            )
        return self._semaphores[domain]
    
    @asynccontextmanager
    async def acquire(self, domain: str, operation_id: Optional[str] = None):
        """
        Acquire semaphore with metrics tracking
        
        Args:
            domain: Operation domain (e.g., 'telegram_send', 'database_write')
            operation_id: Optional unique ID for tracking individual operations
        """
        semaphore = self.get_semaphore(domain)
        metrics = self._metrics[domain]
        
        # Track queue length and wait time
        start_wait = time.time()
        operation_id = operation_id or f"op_{int(time.time() * 1000)}"
        
        # Update queue length (approximate)
        async with self._lock:
            metrics.queue_length = max(0, metrics.total_requests - metrics.current_active)
        
        try:
            # Acquire semaphore (this may block if at limit)
            async with semaphore:
                wait_time = time.time() - start_wait
                
                # Update metrics on acquire
                async with self._lock:
                    metrics.current_active += 1
                    metrics.total_requests += 1
                    metrics.peak_concurrent = max(metrics.peak_concurrent, metrics.current_active)
                    
                    # Update average wait time
                    if metrics.total_requests > 1:
                        metrics.avg_wait_time = (
                            (metrics.avg_wait_time * (metrics.total_requests - 1) + wait_time) /
                            metrics.total_requests
                        )
                    else:
                        metrics.avg_wait_time = wait_time
                    
                    metrics.start_times[operation_id] = time.time()
                    metrics.queue_length = max(0, metrics.queue_length - 1)
                
                logger.debug(f"Acquired {domain} semaphore", extra={
                    "domain": domain,
                    "operation_id": operation_id,
                    "current_active": metrics.current_active,
                    "wait_time": wait_time
                })
                
                yield
                
        finally:
            # Update metrics on release
            async with self._lock:
                metrics.current_active -= 1
                if operation_id in metrics.start_times:
                    operation_duration = time.time() - metrics.start_times[operation_id]
                    del metrics.start_times[operation_id]
                    
                    logger.debug(f"Released {domain} semaphore", extra={
                        "domain": domain,
                        "operation_id": operation_id,
                        "current_active": metrics.current_active,
                        "operation_duration": operation_duration
                    })
    
    async def get_metrics(self, domain: Optional[str] = None) -> Dict[str, Any]:
        """Get concurrency metrics for domain or all domains"""
        async with self._lock:
            if domain:
                if domain in self._metrics:
                    return self._metrics[domain].to_dict()
                return {}
            else:
                return {
                    domain: metrics.to_dict() 
                    for domain, metrics in self._metrics.items()
                }
    
    async def update_limit(self, domain: str, new_limit: int) -> bool:
        """
        Update concurrency limit for domain
        
        Args:
            domain: Operation domain
            new_limit: New concurrency limit
            
        Returns:
            True if updated successfully
        """
        if new_limit <= 0:
            return False
        
        async with self._lock:
            try:
                # Create new semaphore with updated limit
                self._semaphores[domain] = asyncio.Semaphore(new_limit)
                self.limits[domain] = new_limit
                
                # Update metrics
                if domain in self._metrics:
                    self._metrics[domain].max_concurrent = new_limit
                else:
                    self._metrics[domain] = ConcurrencyMetrics(
                        domain=domain,
                        max_concurrent=new_limit
                    )
                
                logger.info(f"Updated {domain} concurrency limit to {new_limit}")
                return True
                
            except Exception as e:
                logger.error(f"Failed to update {domain} concurrency limit: {e}")
                return False
    
    async def reset_metrics(self, domain: Optional[str] = None):
        """Reset metrics for domain or all domains"""
        async with self._lock:
            if domain:
                if domain in self._metrics:
                    metrics = self._metrics[domain]
                    metrics.total_requests = 0
                    metrics.peak_concurrent = 0
                    metrics.avg_wait_time = 0.0
                    metrics.start_times.clear()
            else:
                for metrics in self._metrics.values():
                    metrics.total_requests = 0
                    metrics.peak_concurrent = 0
                    metrics.avg_wait_time = 0.0
                    metrics.start_times.clear()


# Global semaphore manager instance
semaphore_manager = SemaphoreManager()


# Convenience decorators for common use cases
def with_concurrency_limit(domain: str, operation_id: Optional[str] = None):
    """Decorator to add concurrency limiting to async functions"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            async with semaphore_manager.acquire(domain, operation_id):
                return await func(*args, **kwargs)
        return wrapper
    return decorator


# Domain-specific decorators
def telegram_send_limit(func):
    """Decorator for Telegram send operations"""
    return with_concurrency_limit('telegram_send')(func)


def database_write_limit(func):
    """Decorator for database write operations"""
    return with_concurrency_limit('database_write')(func)


def file_processing_limit(func):
    """Decorator for file processing operations"""
    return with_concurrency_limit('file_processing')(func)


@asynccontextmanager
async def bounded_gather(*awaitables, domain: str = 'general', max_concurrent: Optional[int] = None):
    """
    Bounded version of asyncio.gather with concurrency control
    
    Args:
        *awaitables: Coroutines to execute
        domain: Concurrency domain for tracking
        max_concurrent: Override default domain limit
    """
    if max_concurrent:
        # Temporarily update domain limit
        original_limit = semaphore_manager.limits.get(domain, 10)
        await semaphore_manager.update_limit(domain, max_concurrent)
    
    try:
        # Execute all awaitables with concurrency control
        async def execute_with_limit(awaitable):
            async with semaphore_manager.acquire(domain):
                return await awaitable
        
        # Use asyncio.gather with semaphore-wrapped coroutines
        results = await asyncio.gather(*[
            execute_with_limit(awaitable) for awaitable in awaitables
        ], return_exceptions=True)
        
        yield results
        
    finally:
        if max_concurrent:
            # Restore original limit
            await semaphore_manager.update_limit(domain, original_limit)