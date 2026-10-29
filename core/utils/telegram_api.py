"""Telegram API retries with per-attempt concurrency and bounded flood cooldowns."""
import asyncio
import random
import time
from typing import Any, Callable, Optional

from pyrogram.errors import FloodWait, RPCError

from core.concurrency.semaphore_manager import semaphore_manager
from core.utils.logger import get_logger

logger = get_logger(__name__)


class TelegramAPIWrapper:
    """Respect FloodWait while releasing send slots before retry delays.

    Cooldowns are shared among callers of this wrapper in one process. This
    is NOT a distributed Telegram account limiter across independent replicas.
    """

    MAX_COOLDOWN_SCOPES = 2048

    def __init__(self, max_retries: int = 3, base_delay: float = 1.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self._cooldowns: dict[tuple[str, int | None], float] = {
            ('telegram_send', None): 0.0,
            ('telegram_fetch', None): 0.0,
            ('telegram_general', None): 0.0,
        }
        self._flood_wait_events = 0
        self._cooldown_scope_overflows = 0

    def _domain(self, api_func: Callable) -> str:
        name = getattr(api_func, '__name__', 'unknown').lower()
        if any(word in name for word in ('send', 'copy', 'forward')):
            return 'telegram_send'
        if 'get' in name or 'fetch' in name:
            return 'telegram_fetch'
        return 'telegram_general'

    def _scope(self, domain: str, chat_id: Optional[int]) -> tuple[str, int | None]:
        # Telegram slow mode may be chat-specific. Isolate chat sends where an
        # explicit destination is known; unknown destinations share a domain
        # cooldown. Telegram may also issue account-wide waits, so staging
        # must verify domain scope and official retry-after behavior.
        return domain, chat_id if domain == 'telegram_send' and chat_id is not None else None

    def _remaining_delay(self, scope: tuple[str, int | None]) -> float:
        now = time.monotonic()
        # Overflow fallback and unknown-chat flood waits use a domain-wide key.
        shared = (scope[0], None)
        deadline = max(
            self._cooldowns.get(scope, 0),
            self._cooldowns.get(shared, 0),
        )
        return max(0.0, deadline - now)

    def _record_flood(self, scope: tuple[str, int | None], duration: float) -> None:
        now = time.monotonic()
        deadline = now + duration
        if scope not in self._cooldowns and len(self._cooldowns) >= self.MAX_COOLDOWN_SCOPES:
            # Remove only expired entries; do not discard a live cooldown in
            # order to admit a retry stampede from different chat identities.
            expired = [key for key, value in self._cooldowns.items()
                       if key[1] is not None and value <= now]
            for key in expired:
                self._cooldowns.pop(key, None)
            if len(self._cooldowns) >= self.MAX_COOLDOWN_SCOPES:
                self._cooldown_scope_overflows += 1
                scope = (scope[0], None)
        self._cooldowns[scope] = max(self._cooldowns.get(scope, 0), deadline)
        self._flood_wait_events += 1

    def flood_metrics(self) -> dict:
        return {
            "flood_wait_events": self._flood_wait_events,
            "cooldown_scopes": len(self._cooldowns),
            "cooldown_scope_overflows": self._cooldown_scope_overflows,
        }

    async def call_api(
        self,
        api_func: Callable,
        *args,
        chat_id: Optional[int] = None,
        **kwargs
    ) -> Any:
        """Execute one Telegram attempt per semaphore admission.

        No FloodWait or 5xx backoff sleep occurs inside the Telegram
        semaphore. Only active network attempts consume the global budget.
        """
        domain = self._domain(api_func)
        return await self._execute_with_retry(
            api_func, *args, _domain=domain, _chat_id=chat_id, **kwargs
        )

    async def _execute_with_retry(
        self, api_func: Callable, *args,
        _domain: Optional[str] = None, _chat_id: Optional[int] = None,
        **kwargs
    ) -> Any:
        """Retry network attempts, parking without holding a semaphore slot."""
        domain = _domain or self._domain(api_func)
        scope = self._scope(domain, _chat_id)
        retries = 0
        while retries < self.max_retries:
            delay = self._remaining_delay(scope)
            if delay > 0:
                await asyncio.sleep(delay)

            try:
                async with semaphore_manager.acquire(domain):
                    # Re-check after queueing: another operation may have
                    # entered FloodWait while this task waited for admission.
                    # We never sleep under a permit. A new cooldown is
                    # rechecked by the next loop iteration instead.
                    if self._remaining_delay(scope) > 0:
                        postpone = True
                    else:
                        postpone = False
                        result = await api_func(*args, **kwargs)
                if postpone:
                    continue
                logger.debug("Telegram API call successful: %s",
                             getattr(api_func, '__name__', 'unknown'))
                return result

            except FloodWait as error:
                retries += 1
                retry_after = max(0.0, float(error.value))
                wait = retry_after + random.uniform(0.1, 0.5)
                self._record_flood(scope, wait)
                logger.warning(
                    "Telegram FloodWait action=%s wait=%.2f attempt=%d/%d",
                    getattr(api_func, '__name__', 'unknown'),
                    wait, retries, self.max_retries
                )
                if retries >= self.max_retries:
                    # Preserve Telegram's original retry-after rather than
                    # raising an invented 60-second exception.
                    raise

            except RPCError as error:
                code = getattr(error, 'CODE', 0) or 0
                if 400 <= code < 500:
                    raise
                retries += 1
                if retries >= self.max_retries:
                    raise
                # The backoff is intentionally outside the semaphore.
                await asyncio.sleep(
                    self.base_delay * (2 ** (retries - 1))
                    + random.uniform(0.1, 0.5)
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                raise

        raise RuntimeError("Telegram retry budget exhausted")
    

telegram_api = TelegramAPIWrapper()
