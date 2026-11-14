"""Rate limiter — token bucket algorithm for call rate limiting.

One limit, one token per call, integer nanosecond arithmetic. Configurations that
need several limits, weighted costs or server feedback use
``pyresilience._weighted_limiter`` instead.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pyresilience._types import RateLimiterConfig

_monotonic_ns = time.monotonic_ns
_NS_PER_SEC = 1_000_000_000

from pyresilience._exceptions import RateLimitExceededError as RateLimitExceededError  # noqa: E402


class RateLimiter:
    """Thread-safe token bucket rate limiter for sync code.

    Uses integer nanosecond arithmetic to avoid floating point overhead.
    """

    __slots__ = ("_capacity_ns", "_last_refill_ns", "_lock", "_max_wait", "_rate_ns", "_tokens_ns")

    def __init__(self, config: RateLimiterConfig) -> None:
        self._capacity_ns = config.max_calls * _NS_PER_SEC
        self._rate_ns = int(config.max_calls * _NS_PER_SEC / config.period)
        self._max_wait = config.max_wait
        self._lock = threading.Lock()
        self._tokens_ns = self._capacity_ns
        self._last_refill_ns = _monotonic_ns()

    def _refill(self) -> None:
        now = _monotonic_ns()
        elapsed = now - self._last_refill_ns
        if elapsed > 0:
            added = elapsed * self._rate_ns // _NS_PER_SEC
            self._tokens_ns = min(self._capacity_ns, self._tokens_ns + added)
            self._last_refill_ns = now

    def try_acquire(self) -> bool:
        """Take a token if one is available right now. Never waits."""
        with self._lock:
            self._refill()
            if self._tokens_ns >= _NS_PER_SEC:
                self._tokens_ns -= _NS_PER_SEC
                return True
            return False

    def acquire(self) -> bool:
        """Try to acquire a token. Returns True if acquired, False if rejected."""
        deadline = _monotonic_ns() + int(self._max_wait * _NS_PER_SEC)

        while True:
            with self._lock:
                self._refill()
                if self._tokens_ns >= _NS_PER_SEC:
                    self._tokens_ns -= _NS_PER_SEC
                    return True

            if self._max_wait <= 0:
                return False

            remaining = deadline - _monotonic_ns()
            if remaining <= 0:
                return False

            time.sleep(min(0.01, remaining / _NS_PER_SEC))

    def reset(self) -> None:
        """Reset the rate limiter to full capacity."""
        with self._lock:
            self._tokens_ns = self._capacity_ns
            self._last_refill_ns = _monotonic_ns()


class AsyncRateLimiter:
    """Async token bucket rate limiter.

    Uses integer nanosecond arithmetic to avoid floating point overhead.

    Args:
        config: Rate limiter configuration.
        shared: Optional sync ``RateLimiter`` whose bucket this limiter draws from,
            so sync and async callers consume one common limit.
    """

    __slots__ = (
        "_capacity_ns",
        "_last_refill_ns",
        "_max_wait",
        "_rate_ns",
        "_shared",
        "_tokens_ns",
    )

    def __init__(self, config: RateLimiterConfig, shared: Optional[RateLimiter] = None) -> None:
        self._capacity_ns = config.max_calls * _NS_PER_SEC
        self._rate_ns = int(config.max_calls * _NS_PER_SEC / config.period)
        self._max_wait = config.max_wait
        self._tokens_ns = self._capacity_ns
        self._last_refill_ns = _monotonic_ns()
        self._shared = shared

    def _refill(self) -> None:
        now = _monotonic_ns()
        elapsed = now - self._last_refill_ns
        if elapsed > 0:
            added = elapsed * self._rate_ns // _NS_PER_SEC
            self._tokens_ns = min(self._capacity_ns, self._tokens_ns + added)
            self._last_refill_ns = now

    async def acquire(self) -> bool:
        """Try to acquire a token. Returns True if acquired, False if rejected."""
        shared = self._shared
        if shared is not None:
            return await self._acquire_shared(shared)

        deadline = _monotonic_ns() + int(self._max_wait * _NS_PER_SEC)

        while True:
            self._refill()
            if self._tokens_ns >= _NS_PER_SEC:
                self._tokens_ns -= _NS_PER_SEC
                return True

            if self._max_wait <= 0:
                return False

            remaining = deadline - _monotonic_ns()
            if remaining <= 0:
                return False

            await asyncio.sleep(min(0.01, remaining / _NS_PER_SEC))

    async def _acquire_shared(self, shared: RateLimiter) -> bool:
        """Draw from the bucket of a sync limiter, waiting on the event loop."""
        deadline = _monotonic_ns() + int(self._max_wait * _NS_PER_SEC)

        while True:
            if shared.try_acquire():
                return True

            if self._max_wait <= 0:
                return False

            remaining = deadline - _monotonic_ns()
            if remaining <= 0:
                return False

            await asyncio.sleep(min(0.01, remaining / _NS_PER_SEC))

    def reset(self) -> None:
        """Reset the rate limiter to full capacity."""
        if self._shared is not None:
            self._shared.reset()
            return
        self._tokens_ns = self._capacity_ns
        self._last_refill_ns = _monotonic_ns()
