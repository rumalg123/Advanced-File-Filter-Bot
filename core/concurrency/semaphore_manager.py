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


class ResizableSemaphore(asyncio.Semaphore):
    """A single stable permit budget across live concurrency-limit changes.

    The available-permit balance may temporarily be negative after a limit
    reduction. A negative balance represents running operations that must
    finish before another waiter can enter. Unlike a new Semaphore object,
    existing holders and waiters remain part of the SAME permit budget.

    asyncio.Semaphore's FIFO waiting and cancellation handling are retained.
    Only the predicates and release/resize wake-up decisions differ. The
    implementation intentionally uses asyncio's documented single-loop
    synchronization model and its private _wake_up_next hook. Test each
    supported Python version before upgrading the runtime (PH-020).
    """

    def __init__(self, limit: int):
        super().__init__(limit)
        self._limit = limit

    @property
    def limit(self) -> int:
        return self._limit

    def locked(self) -> bool:
        # asyncio.Semaphore.locked() checks for == 0. A downsized domain can
        # have negative debt, which MUST still block new acquisitions.
        return self._value <= 0 or any(
            not waiter.cancelled() for waiter in (self._waiters or ())
        )

    def _wake_available(self) -> None:
        # Never wake a waiter while the domain still owes old permits.
        while self._value > 0 and self._wake_up_next():
            pass

    def release(self) -> None:
        # The stdlib release() wakes a waiter unconditionally; that is
        # incorrect when downsizing left outstanding negative permit debt.
        self._value += 1
        self._wake_available()

    def resize(self, limit: int) -> None:
        if type(limit) is not int or limit < 1:
            raise ValueError("Semaphore limit must be a positive integer")
        # No await here: updates and releases cannot interleave halfway
        # through the arithmetic on a single asyncio event loop.
        self._value += limit - self._limit
        self._limit = limit
        self._wake_available()


class SemaphoreManager:
    """Manages asyncio.Semaphore instances for different operation domains"""
    
    # Default concurrency limits by domain
    DEFAULT_LIMITS = {
        'telegram_send': 10,      # Telegram API sends
        'telegram_fetch': 15,     # Telegram API fetches
        'telegram_general': 10,   # Other Telegram API operations
        'broadcast': 3,           # Concurrent broadcast deliveries
        'database_write': 20,     # Database writes
        'file_processing': 5,     # File processing operations
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
        
        self._semaphores: Dict[str, ResizableSemaphore] = {}
        self._metrics: Dict[str, ConcurrencyMetrics] = {}
        self._lock = asyncio.Lock()
        
        # Initialize semaphores and metrics
        for domain, limit in self.limits.items():
            self._semaphores[domain] = ResizableSemaphore(limit)
            self._metrics[domain] = ConcurrencyMetrics(
                domain=domain,
                max_concurrent=limit
            )
    
    def get_semaphore(self, domain: str) -> ResizableSemaphore:
        """Get semaphore for domain, create if doesn't exist"""
        if domain not in self._semaphores:
            limit = self.limits.get(domain, 10)  # Default limit
            self._semaphores[domain] = ResizableSemaphore(limit)
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
        # asyncio primitives are used on the owning event loop only. A waiter
        # is not an active operation until __aenter__ actually succeeds.
        started_waiting = time.monotonic()
        operation_id = operation_id or f"op_{time.time_ns()}"
        waiting = False
        acquired = False

        async with self._lock:
            metrics.queue_length += 1
            waiting = True

        try:
            # If a task is cancelled while this waits for a permit, the
            # semaphore does not enter its body and no active count is added.
            async with semaphore:
                waited = time.monotonic() - started_waiting

                # This lock acquisition is also cancellable. It must not
                # falsely mark a waiter as active or leave a stale waiter.
                async with self._lock:
                    metrics.queue_length -= 1
                    waiting = False
                    metrics.current_active += 1
                    acquired = True
                    metrics.total_requests += 1
                    metrics.peak_concurrent = max(
                        metrics.peak_concurrent, metrics.current_active
                    )
                    metrics.avg_wait_time += (
                        waited - metrics.avg_wait_time
                    ) / metrics.total_requests
                    metrics.start_times[operation_id] = time.monotonic()

                logger.debug(f"Acquired {domain} semaphore", extra={
                    "domain": domain,
                    "operation_id": operation_id,
                    "current_active": metrics.current_active,
                    "wait_time": waited
                })

                try:
                    yield
                finally:
                    # Runs only after successful semaphore admission and
                    # metric registration, including body errors/cancellation.
                    if acquired:
                        async with self._lock:
                            metrics.current_active -= 1
                            started = metrics.start_times.pop(operation_id, None)
                            duration = (
                                time.monotonic() - started
                                if started is not None else None
                            )
                        logger.debug(f"Released {domain} semaphore", extra={
                            "domain": domain,
                            "operation_id": operation_id,
                            "current_active": metrics.current_active,
                            "operation_duration": duration
                        })
        finally:
            if waiting:
                # Cancelled/error before acquisition: remove only the queue
                # reservation. Do not release or decrement an unheld permit.
                async with self._lock:
                    metrics.queue_length -= 1

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
        """Resize one domain without abandoning old holders or pending waiters.

        Shrinking below the active count creates permit debt. No new waiter
        is admitted until old holders release enough permits. Raising the
        budget wakes pending waiters up to the new available capacity.
        Domain metrics and configured limit change in the same manager lock.
        """
        if type(new_limit) is not int or new_limit < 1:
            return False

        async with self._lock:
            try:
                semaphore = self.get_semaphore(domain)
                # Preserve stable identity: all previously admitted or
                # queued tasks must keep using this same semaphore.
                semaphore.resize(new_limit)
                self.limits[domain] = new_limit
                self._metrics[domain].max_concurrent = new_limit
                logger.info(
                    "Updated %s concurrency limit to %s without replacing permits",
                    domain, new_limit
                )
                return True
            except Exception as error:
                logger.error("Failed to resize %s semaphore: %s", domain, error)
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
