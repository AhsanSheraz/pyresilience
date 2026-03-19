"""Rate limiter — token bucket algorithm for call rate limiting."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyresilience._types import RateLimiterConfig

_monotonic = time.monotonic


class RateLimitExceededError(Exception):
    """Raised when a call is rejected by the rate limiter."""


class RateLimiter:
    """Thread-safe token bucket rate limiter for sync code."""

    __slots__ = ("_capacity", "_last_refill", "_lock", "_max_wait", "_rate", "_tokens")

    def __init__(self, config: RateLimiterConfig) -> None:
        self._capacity = float(config.max_calls)
        self._rate = config.max_calls / config.period  # tokens per second
        self._max_wait = config.max_wait
        self._lock = threading.Lock()
        self._tokens = self._capacity
        self._last_refill = _monotonic()

    def _refill(self) -> None:
        now = _monotonic()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_refill = now

    def acquire(self) -> bool:
        """Try to acquire a token. Returns True if acquired, False if rejected."""
        deadline = _monotonic() + self._max_wait

        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True

            if self._max_wait <= 0:
                return False

            remaining = deadline - _monotonic()
            if remaining <= 0:
                return False

            time.sleep(min(0.01, remaining))

    def reset(self) -> None:
        """Reset the rate limiter to full capacity."""
        with self._lock:
            self._tokens = self._capacity
            self._last_refill = _monotonic()


class AsyncRateLimiter:
    """Async token bucket rate limiter."""

    __slots__ = ("_capacity", "_last_refill", "_max_wait", "_rate", "_tokens")

    def __init__(self, config: RateLimiterConfig) -> None:
        self._capacity = float(config.max_calls)
        self._rate = config.max_calls / config.period
        self._max_wait = config.max_wait
        self._tokens = self._capacity
        self._last_refill = _monotonic()

    def _refill(self) -> None:
        now = _monotonic()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_refill = now

    async def acquire(self) -> bool:
        """Try to acquire a token. Returns True if acquired, False if rejected."""
        deadline = _monotonic() + self._max_wait

        while True:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True

            if self._max_wait <= 0:
                return False

            remaining = deadline - _monotonic()
            if remaining <= 0:
                return False

            await asyncio.sleep(min(0.01, remaining))

    def reset(self) -> None:
        """Reset the rate limiter to full capacity."""
        self._tokens = self._capacity
        self._last_refill = _monotonic()
