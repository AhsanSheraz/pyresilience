"""Circuit breaker implementation.

Supports two modes:
- **Consecutive count** (default): CLOSED -> OPEN after N consecutive failures.
- **Sliding window**: CLOSED -> OPEN when failure rate exceeds threshold within
  the last N calls. Also supports slow call rate detection.

Thread-safe state machine: CLOSED -> OPEN -> HALF_OPEN -> CLOSED (or back to OPEN).
Uses monotonic clock for recovery timing and a single lock for all state transitions.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Optional

from pyresilience._types import CircuitBreakerConfig, CircuitState

# Cache enum members to avoid attribute lookups in hot path
_CLOSED = CircuitState.CLOSED
_OPEN = CircuitState.OPEN
_HALF_OPEN = CircuitState.HALF_OPEN

_monotonic = time.monotonic


class CircuitBreaker:
    """Thread-safe circuit breaker with configurable thresholds.

    When ``sliding_window_size > 0``, uses a count-based sliding window that
    tracks the last N call outcomes. The circuit opens when:
    - failure rate >= ``failure_rate_threshold``, OR
    - slow call rate >= ``slow_call_rate_threshold`` (if slow_call_duration > 0)

    When ``sliding_window_size == 0`` (default), uses the legacy consecutive
    failure count mode for backward compatibility and minimal overhead.
    """

    __slots__ = (
        "_failure_count",
        "_failure_rate_threshold",
        "_failure_threshold",
        "_last_failure_time",
        "_lock",
        "_minimum_calls",
        "_recovery_timeout",
        "_slow_call_duration",
        "_slow_call_rate_threshold",
        "_state",
        "_success_count",
        "_success_threshold",
        "_window",
        "_window_size",
    )

    def __init__(self, config: CircuitBreakerConfig) -> None:
        self._failure_threshold = config.failure_threshold
        self._recovery_timeout = config.recovery_timeout
        self._success_threshold = config.success_threshold
        self._state = _CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._lock = threading.Lock()

        # Sliding window config
        self._window_size = config.sliding_window_size
        self._failure_rate_threshold = config.failure_rate_threshold
        self._minimum_calls = config.minimum_calls or config.sliding_window_size
        self._slow_call_duration = config.slow_call_duration
        self._slow_call_rate_threshold = config.slow_call_rate_threshold

        # Sliding window: deque of (is_failure: bool, is_slow: bool) tuples
        # Only allocated when sliding window mode is enabled
        self._window: Optional[deque[tuple[bool, bool]]] = (
            deque(maxlen=config.sliding_window_size) if config.sliding_window_size > 0 else None
        )

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._check_recovery()
            return self._state

    @property
    def failure_count(self) -> int:
        """Current consecutive failure count (consecutive count mode)."""
        with self._lock:
            return self._failure_count

    def _check_recovery(self) -> None:
        """Transition OPEN -> HALF_OPEN when recovery timeout has elapsed."""
        if (
            self._state is _OPEN
            and self._last_failure_time is not None
            and _monotonic() - self._last_failure_time >= self._recovery_timeout
        ):
            self._state = _HALF_OPEN
            self._success_count = 0

    def allow_request(self) -> bool:
        """Check if a request is allowed through the circuit."""
        with self._lock:
            self._check_recovery()
            return self._state is not _OPEN

    def record_success_atomic(self, duration: float = 0.0) -> tuple[CircuitState, CircuitState]:
        """Record a successful call and return (previous_state, new_state) atomically.

        This avoids the race condition where ``.state`` and ``.record_success()`` are
        called separately with two lock acquisitions, potentially allowing another
        thread to change state between the two calls.

        Args:
            duration: Call duration in seconds (for slow call detection).

        Returns:
            Tuple of (state_before_recording, state_after_recording).
        """
        with self._lock:
            self._check_recovery()
            prev_state = self._state
            if self._state is _HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self._success_threshold:
                    self._state = _CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    if self._window is not None:
                        self._window.clear()
                return prev_state, self._state

            if self._window is not None:
                is_slow = self._slow_call_duration > 0 and duration >= self._slow_call_duration
                self._window.append((False, is_slow))
                self._maybe_open_from_window()
            else:
                self._failure_count = 0
            return prev_state, self._state

    def record_success(self, duration: float = 0.0) -> CircuitState:
        """Record a successful call. Returns the new state.

        Args:
            duration: Call duration in seconds (for slow call detection).
        """
        with self._lock:
            if self._state is _HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self._success_threshold:
                    self._state = _CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    if self._window is not None:
                        self._window.clear()
                return self._state

            # Sliding window mode
            if self._window is not None:
                is_slow = self._slow_call_duration > 0 and duration >= self._slow_call_duration
                self._window.append((False, is_slow))
                self._maybe_open_from_window()
            else:
                # Consecutive count mode: reset failure count on success
                self._failure_count = 0
            return self._state

    def record_failure(self, duration: float = 0.0) -> CircuitState:
        """Record a failed call. Returns the new state.

        Args:
            duration: Call duration in seconds (for slow call detection).
        """
        with self._lock:
            if self._state is _HALF_OPEN:
                self._state = _OPEN
                self._last_failure_time = _monotonic()
                self._success_count = 0
                return self._state

            # Sliding window mode
            if self._window is not None:
                is_slow = self._slow_call_duration > 0 and duration >= self._slow_call_duration
                self._window.append((True, is_slow))
                self._maybe_open_from_window()
            else:
                # Consecutive count mode
                self._failure_count += 1
                if self._failure_count >= self._failure_threshold:
                    self._state = _OPEN
                    self._last_failure_time = _monotonic()
            return self._state

    def _maybe_open_from_window(self) -> None:
        """Check sliding window rates and open circuit if thresholds exceeded.

        Must be called while holding self._lock.
        """
        window = self._window
        if window is None:
            return  # pragma: no cover

        total = len(window)
        if total < self._minimum_calls:
            return

        failures = sum(1 for is_fail, _ in window if is_fail)
        failure_rate = failures / total

        if failure_rate >= self._failure_rate_threshold:
            self._state = _OPEN
            self._last_failure_time = _monotonic()
            return

        # Check slow call rate
        if self._slow_call_duration > 0:
            slow_calls = sum(1 for _, is_slow in window if is_slow)
            slow_rate = slow_calls / total
            if slow_rate >= self._slow_call_rate_threshold:
                self._state = _OPEN
                self._last_failure_time = _monotonic()

    def reset(self) -> None:
        """Reset circuit breaker to CLOSED state, clearing all counters."""
        with self._lock:
            self._state = _CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
            if self._window is not None:
                self._window.clear()

    def force_open(self) -> None:
        """Force circuit to OPEN state."""
        with self._lock:
            self._state = _OPEN
            self._last_failure_time = _monotonic()

    def force_close(self) -> None:
        """Force circuit to CLOSED state, clearing all counters."""
        with self._lock:
            self._state = _CLOSED
            self._failure_count = 0
            self._success_count = 0
            if self._window is not None:
                self._window.clear()

    @property
    def metrics(self) -> dict[str, Any]:
        """Get current circuit breaker metrics.

        Returns dict with failure_rate, slow_call_rate, total_calls, and state
        from the sliding window (or 0s if using consecutive count mode).
        """
        with self._lock:
            if self._window is None or len(self._window) == 0:
                return {
                    "failure_rate": 0.0,
                    "slow_call_rate": 0.0,
                    "total_calls": 0,
                    "state": self._state.value,
                }
            total = len(self._window)
            failures = sum(1 for is_fail, _ in self._window if is_fail)
            slow = sum(1 for _, is_slow in self._window if is_slow)
            return {
                "failure_rate": failures / total,
                "slow_call_rate": slow / total,
                "total_calls": total,
                "state": self._state.value,
            }
