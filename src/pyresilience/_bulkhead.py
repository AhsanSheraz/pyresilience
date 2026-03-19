"""Bulkhead (concurrency limiter) implementation."""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pyresilience._types import BulkheadConfig


class BulkheadFullError(Exception):
    """Raised when the bulkhead has no available slots."""


class Bulkhead:
    """Thread-safe bulkhead for sync code."""

    def __init__(self, config: BulkheadConfig) -> None:
        self._semaphore = threading.Semaphore(config.max_concurrent)
        self._max_wait = config.max_wait

    def acquire(self) -> bool:
        """Try to acquire a slot. Returns True if successful."""
        timeout: Optional[float] = self._max_wait if self._max_wait > 0 else None
        if timeout is None:
            # Try without blocking
            return self._semaphore.acquire(blocking=False)
        return self._semaphore.acquire(timeout=timeout)

    def release(self) -> None:
        """Release a slot."""
        self._semaphore.release()


class AsyncBulkhead:
    """Async bulkhead for async code."""

    def __init__(self, config: BulkheadConfig) -> None:
        self._config = config
        self._semaphore: Optional[asyncio.Semaphore] = None

    def _get_semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._config.max_concurrent)
        return self._semaphore

    async def acquire(self) -> bool:
        """Try to acquire a slot. Returns True if successful.

        Note: In asyncio's cooperative scheduling model, the check-then-acquire
        pattern is safe when max_wait=0 because no other coroutine can run
        between locked() and the synchronous part of acquire() — there's no
        await point in between. The semaphore's acquire() only suspends if the
        value is 0, which we've already checked.
        """
        sem = self._get_semaphore()
        if self._config.max_wait <= 0:
            if sem.locked():
                return False
            await sem.acquire()
            return True
        try:
            await asyncio.wait_for(sem.acquire(), timeout=self._config.max_wait)
            return True
        except asyncio.TimeoutError:
            return False

    def release(self) -> None:
        """Release a slot."""
        if self._semaphore is not None:
            self._semaphore.release()
