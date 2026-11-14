"""Token-bucket state behind the weighted rate limiter.

Holds the buckets (one per limit), a single lock and the pause imposed by server
feedback. The sync and async weighted limiters are thin waiting loops around it.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Any, Callable, Optional

from pyresilience._types import PRIMARY_LIMIT_NAME

if TYPE_CHECKING:
    from pyresilience._types import RateLimiterConfig, RateLimitFeedback

_monotonic = time.monotonic
_INF = float("inf")

_logger = logging.getLogger("pyresilience")


class _Bucket:
    """One limit of a weighted limiter."""

    __slots__ = ("actual_cost", "capacity", "cost", "name", "period", "rate", "tokens")

    def __init__(
        self,
        name: str,
        capacity: float,
        period: float,
        cost: Optional[Callable[..., float]],
        actual_cost: Optional[Callable[[Any], Optional[float]]],
    ) -> None:
        self.name = name
        self.capacity = capacity
        self.period = period
        self.rate = capacity / period
        self.tokens = capacity
        self.cost = cost
        self.actual_cost = actual_cost


class _LimiterCore:
    """State of a weighted limiter: the buckets, one lock and the server-imposed pause.

    One core can back a sync and an async limiter at once, which is how a registry
    name shares its limits between sync and async functions. Critical sections are
    a few arithmetic operations, so taking the lock on the event loop does not block it.
    """

    __slots__ = (
        "_last_refill",
        "_lock",
        "_pause_until",
        "buckets",
        "charge_retries",
        "feedback",
        "max_wait",
        "observes",
        "shared",
    )

    def __init__(self, config: RateLimiterConfig) -> None:
        buckets = [
            _Bucket(
                PRIMARY_LIMIT_NAME,
                float(config.max_calls),
                config.period,
                config.cost,
                config.actual_cost,
            )
        ]
        for index, limit in enumerate(config.limits, start=1):
            buckets.append(
                _Bucket(
                    limit.name or f"limit{index}",
                    float(limit.max_units),
                    limit.period,
                    limit.cost,
                    limit.actual_cost,
                )
            )
        self.buckets = buckets
        self.max_wait = config.max_wait
        self.feedback: Optional[Callable[[Any], Optional[RateLimitFeedback]]] = config.feedback
        self.charge_retries = config.charge_retries
        # True when the wrapped call must be observed (result, error or retries)
        self.observes = bool(
            config.feedback is not None
            or config.charge_retries
            or any(bucket.actual_cost is not None for bucket in buckets)
        )
        # Optional cross-process windows (pyresilience._shared._SharedWindows)
        self.shared: Any = None
        self._lock = threading.Lock()
        self._pause_until = 0.0
        self._last_refill = _monotonic()

    def costs(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> list[float]:
        """Units each limit would consume for a call with these arguments."""
        result: list[float] = []
        for bucket in self.buckets:
            cost_fn = bucket.cost
            if cost_fn is None:
                result.append(1.0)
            else:
                cost = float(cost_fn(*args, **kwargs))
                result.append(cost if cost > 0 else 0.0)
        return result

    def _refill(self, now: float) -> None:
        elapsed = now - self._last_refill
        if elapsed > 0:
            for bucket in self.buckets:
                tokens = bucket.tokens + elapsed * bucket.rate
                bucket.tokens = tokens if tokens < bucket.capacity else bucket.capacity
            self._last_refill = now

    def try_reserve(self, costs: list[float]) -> tuple[bool, float, str]:
        """Take ``costs`` from every limit, or from none.

        Returns ``(ok, wait, blocker)``: on rejection ``wait`` is how long until the
        call could pass (infinity when it never can) and ``blocker`` names the limit.
        """
        with self._lock:
            now = _monotonic()
            self._refill(now)
            if now < self._pause_until:
                return False, self._pause_until - now, "server feedback"
            wait = 0.0
            blocker = ""
            for bucket, cost in zip(self.buckets, costs):
                if cost > bucket.capacity:
                    return False, _INF, bucket.name
                if bucket.tokens < cost:
                    needed = (cost - bucket.tokens) / bucket.rate
                    if needed > wait:
                        wait = needed
                        blocker = bucket.name
            if blocker:
                return False, wait, blocker
            for bucket, cost in zip(self.buckets, costs):
                bucket.tokens -= cost
            return True, 0.0, ""

    def give_back(self, costs: list[float]) -> None:
        """Return units taken by ``try_reserve`` (used when a shared window refuses)."""
        with self._lock:
            for bucket, cost in zip(self.buckets, costs):
                tokens = bucket.tokens + cost
                bucket.tokens = tokens if tokens < bucket.capacity else bucket.capacity

    def charge(self, costs: list[float]) -> None:
        """Debit ``costs`` without waiting; a limit may go into debt."""
        with self._lock:
            self._refill(_monotonic())
            for bucket, cost in zip(self.buckets, costs):
                bucket.tokens -= cost

    def observe(self, reserved: list[float], outcome: Any, is_error: bool) -> Optional[list[float]]:
        """Settle reserved units against real usage and apply server feedback.

        ``outcome`` is the attempt's result, or the raised exception when
        ``is_error`` is True. ``reserved`` holds the units still reserved for the
        call; each limit that reports its real usage is settled against it and its
        entry is set to 0, so a reservation is settled exactly once. A failed
        attempt settles nothing.

        Returns the per-limit corrections (positive = given back) or None when no
        limit reported usage. Errors raised by the user's callables are logged and
        never reach the caller.
        """
        actuals: Optional[list[Optional[float]]] = None
        if not is_error:
            for index, bucket in enumerate(self.buckets):
                actual_fn = bucket.actual_cost
                if actual_fn is None:
                    continue
                try:
                    actual = actual_fn(outcome)
                except Exception:
                    _logger.warning(
                        "actual_cost for rate limit %r raised an exception",
                        bucket.name,
                        exc_info=True,
                    )
                    continue
                if actual is not None:
                    if actuals is None:
                        actuals = [None] * len(self.buckets)
                    actuals[index] = float(actual)

        feedback: Optional[RateLimitFeedback] = None
        feedback_fn = self.feedback
        if feedback_fn is not None:
            try:
                feedback = feedback_fn(outcome)
            except Exception:
                _logger.warning("Rate limiter feedback raised an exception", exc_info=True)

        if actuals is None and feedback is None:
            return None

        deltas: Optional[list[float]] = None
        with self._lock:
            now = _monotonic()
            self._refill(now)
            if actuals is not None:
                deltas = [0.0] * len(self.buckets)
                for index, bucket in enumerate(self.buckets):
                    actual = actuals[index]
                    if actual is None:
                        continue
                    # Settle and close this limit's reservation in one step, so a
                    # late result of an abandoned attempt cannot settle it twice
                    delta = reserved[index] - actual
                    reserved[index] = 0.0
                    deltas[index] = delta
                    tokens = bucket.tokens + delta
                    bucket.tokens = tokens if tokens < bucket.capacity else bucket.capacity
            if feedback is not None:
                retry_after = feedback.retry_after
                if retry_after is not None and retry_after > 0:
                    until = now + retry_after
                    if until > self._pause_until:
                        self._pause_until = until
                remaining = feedback.remaining
                if remaining:
                    for bucket in self.buckets:
                        left = remaining.get(bucket.name)
                        if left is not None and left < bucket.tokens:
                            bucket.tokens = float(left)

        return deltas

    def levels(self) -> dict[str, float]:
        """Units currently available per limit."""
        with self._lock:
            self._refill(_monotonic())
            return {bucket.name: bucket.tokens for bucket in self.buckets}

    def paused_for(self) -> float:
        """Seconds the limiter stays paused by server feedback (0.0 when not paused)."""
        with self._lock:
            remaining = self._pause_until - _monotonic()
            return remaining if remaining > 0 else 0.0

    def reset(self) -> None:
        """Refill every limit and lift any pause."""
        with self._lock:
            for bucket in self.buckets:
                bucket.tokens = bucket.capacity
            self._pause_until = 0.0
            self._last_refill = _monotonic()
