"""Circuit breaker implementation."""

from __future__ import annotations

import threading
import time
from typing import Optional

from pyresilience._types import CircuitBreakerConfig, CircuitState


class CircuitBreaker:
    """Thread-safe circuit breaker.

    Transitions: CLOSED -> OPEN -> HALF_OPEN -> CLOSED (or back to OPEN).
    """

    def __init__(self, config: CircuitBreakerConfig) -> None:
        self._config = config
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state

    def _maybe_transition_to_half_open(self) -> None:
        if (
            self._state == CircuitState.OPEN
            and self._last_failure_time is not None
            and time.monotonic() - self._last_failure_time >= self._config.recovery_timeout
        ):
            self._state = CircuitState.HALF_OPEN
            self._success_count = 0

    def allow_request(self) -> bool:
        """Check if a request is allowed through the circuit."""
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state != CircuitState.OPEN

    def record_success(self) -> CircuitState:
        """Record a successful call. Returns the new state."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self._config.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
            else:
                self._failure_count = 0
            return self._state

    def record_failure(self) -> CircuitState:
        """Record a failed call. Returns the new state."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._last_failure_time = time.monotonic()
                self._success_count = 0
            else:
                self._failure_count += 1
                if self._failure_count >= self._config.failure_threshold:
                    self._state = CircuitState.OPEN
                    self._last_failure_time = time.monotonic()
            return self._state
