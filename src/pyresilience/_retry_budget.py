"""Global retry budget — token bucket that limits total retries across callers."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyresilience._types import RetryBudgetConfig

_monotonic = time.monotonic


class RetryBudget:
    """Thread-safe global retry budget using a token bucket.

    Limits total retry attempts across all decorated functions.
    Tokens are consumed on each retry attempt and refilled over time.
    """

    __slots__ = ("_capacity", "_last_refill", "_lock", "_rate", "_tokens")

    def __init__(self, config: RetryBudgetConfig) -> None:
        self._capacity = float(config.max_retries)
        self._rate = config.refill_rate
        self._tokens = float(config.max_retries)
        self._last_refill = _monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        """Try to consume one retry token. Returns True if budget allows."""
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    def _refill(self) -> None:
        now = _monotonic()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_refill = now

    @property
    def available(self) -> float:
        """Current available retry tokens."""
        with self._lock:
            self._refill()
            return self._tokens

    def reset(self) -> None:
        """Reset budget to full capacity."""
        with self._lock:
            self._tokens = self._capacity
            self._last_refill = _monotonic()
