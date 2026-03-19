"""Tests for circuit breaker functionality."""

from __future__ import annotations

import time

import pytest

from pyresilience import (
    CircuitBreakerConfig,
    CircuitOpenError,
    CircuitState,
    EventType,
    FallbackConfig,
    ResilienceEvent,
    resilient,
)
from pyresilience._circuit_breaker import CircuitBreaker


class TestCircuitBreakerUnit:
    def test_starts_closed(self) -> None:
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3))
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold(self) -> None:
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3))
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_blocks_when_open(self) -> None:
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=2, recovery_timeout=10))
        cb.record_failure()
        cb.record_failure()
        assert not cb.allow_request()

    def test_half_open_after_recovery(self) -> None:
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, recovery_timeout=0.1))
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request()

    def test_closes_after_success_in_half_open(self) -> None:
        cb = CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=1, recovery_timeout=0.1, success_threshold=2)
        )
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_reopens_on_failure_in_half_open(self) -> None:
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, recovery_timeout=0.1))
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_success_resets_failure_count(self) -> None:
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3))
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        # Only 1 failure after reset, should still be closed
        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerDecorator:
    def test_circuit_opens_and_rejects(self) -> None:
        call_count = 0

        @resilient(
            circuit_breaker=CircuitBreakerConfig(failure_threshold=2, recovery_timeout=10),
        )
        def fails() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        # Fail twice to open circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                fails()

        # Circuit is now open — should get RuntimeError
        with pytest.raises(CircuitOpenError, match="Circuit breaker is open"):
            fails()
        assert call_count == 2  # Not called a third time

    def test_circuit_with_fallback(self) -> None:
        @resilient(
            circuit_breaker=CircuitBreakerConfig(failure_threshold=1, recovery_timeout=10),
            fallback=FallbackConfig(handler=lambda e: "fallback_value"),
        )
        def fails() -> str:
            raise ValueError("fail")

        fails()  # Opens circuit
        result = fails()  # Returns fallback
        assert result == "fallback_value"

    def test_circuit_events(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            circuit_breaker=CircuitBreakerConfig(failure_threshold=2),
            listeners=[events.append],
        )
        def fails() -> str:
            raise ValueError("fail")

        for _ in range(2):
            with pytest.raises(ValueError):
                fails()

        event_types = [e.event_type for e in events]
        assert EventType.CIRCUIT_OPEN in event_types
