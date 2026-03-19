"""Bulkhead (concurrency limiter) implementation."""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pyresilience._types import BulkheadConfig


class Bulkhead:
    """Thread-safe bulkhead for sync code.

    Uses a lightweight lock + counter for non-waiting mode (max_wait=0),
    falling back to Semaphore only when waiting is needed.
    """

    def __init__(self, config: BulkheadConfig) -> None:
        self._max_concurrent = config.max_concurrent
        self._max_wait = config.max_wait
        if config.max_wait > 0:
            self._semaphore: Optional[threading.Semaphore] = threading.Semaphore(
                config.max_concurrent
            )
            self._lock: Optional[threading.Lock] = None
            self._count = 0
        else:
            self._semaphore = None
            self._lock = threading.Lock()
            self._count = 0

    def acquire(self) -> bool:
        """Try to acquire a slot. Returns True if successful."""
        if self._lock is not None:
            with self._lock:
                if self._count >= self._max_concurrent:
                    return False
                self._count += 1
                return True
        assert self._semaphore is not None
        return self._semaphore.acquire(timeout=self._max_wait)

    def release(self) -> None:
        """Release a slot."""
        if self._lock is not None:
            with self._lock:
                self._count -= 1
        else:
            assert self._semaphore is not None
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
        """Try to acquire a slot. Returns True if successful."""
        sem = self._get_semaphore()
        if self._config.max_wait <= 0:
            # locked() returns True when no slots available (_value == 0).
            # Safe in asyncio's cooperative model: no other coroutine runs between
            # locked() and acquire() since there's no yield point in between.
            # When _value > 0, acquire() completes immediately without suspending.
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
