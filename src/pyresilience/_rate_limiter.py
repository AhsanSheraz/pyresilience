"""Rate limiter — token bucket algorithm for call rate limiting."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyresilience._types import RateLimiterConfig


class RateLimitExceededError(Exception):
    """Raised when a call is rejected by the rate limiter."""


class RateLimiter:
    """Thread-safe token bucket rate limiter for sync code."""

    def __init__(self, config: RateLimiterConfig) -> None:
        self._max_calls = config.max_calls
        self._period = config.period
        self._max_wait = config.max_wait
        self._lock = threading.Lock()
        self._tokens = float(config.max_calls)
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        new_tokens = elapsed * (self._max_calls / self._period)
        self._tokens = min(self._max_calls, self._tokens + new_tokens)
        self._last_refill = now

    def acquire(self) -> bool:
        """Try to acquire a token. Returns True if acquired, False if rejected."""
        deadline = time.monotonic() + self._max_wait

        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True

            if self._max_wait <= 0:
                return False

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False

            # Sleep a small amount before retrying
            wait = min(0.01, remaining)
            time.sleep(wait)

    def reset(self) -> None:
        """Reset the rate limiter to full capacity."""
        with self._lock:
            self._tokens = float(self._max_calls)
            self._last_refill = time.monotonic()


class AsyncRateLimiter:
    """Async token bucket rate limiter."""

    def __init__(self, config: RateLimiterConfig) -> None:
        self._max_calls = config.max_calls
        self._period = config.period
        self._max_wait = config.max_wait
        self._tokens = float(config.max_calls)
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        new_tokens = elapsed * (self._max_calls / self._period)
        self._tokens = min(self._max_calls, self._tokens + new_tokens)
        self._last_refill = now

    async def acquire(self) -> bool:
        """Try to acquire a token. Returns True if acquired, False if rejected."""
        deadline = time.monotonic() + self._max_wait

        while True:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True

            if self._max_wait <= 0:
                return False

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False

            wait = min(0.01, remaining)
            await asyncio.sleep(wait)

    def reset(self) -> None:
        """Reset the rate limiter to full capacity."""
        self._tokens = float(self._max_calls)
        self._last_refill = time.monotonic()
