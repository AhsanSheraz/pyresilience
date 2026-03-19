"""Tests for sliding window circuit breaker, failure rate threshold, and slow call detection."""

from __future__ import annotations

import time

import pytest

from pyresilience import (
    CircuitBreakerConfig,
    CircuitState,
    EventType,
    ResilienceEvent,
    resilient,
)
from pyresilience._circuit_breaker import CircuitBreaker


class TestSlidingWindowUnit:
    """Unit tests for sliding window circuit breaker."""

    def test_sliding_window_stays_closed_below_threshold(self) -> None:
        cb = CircuitBreaker(
            CircuitBreakerConfig(
                sliding_window_size=10,
                failure_rate_threshold=0.5,
                minimum_calls=5,
            )
        )
        # 4 successes, 1 failure = 20% failure rate < 50%
        for _ in range(4):
            cb.record_success()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_sliding_window_opens_at_threshold(self) -> None:
        cb = CircuitBreaker(
            CircuitBreakerConfig(
                sliding_window_size=10,
                failure_rate_threshold=0.5,
                minimum_calls=4,
            )
        )
        # 2 successes, 2 failures = 50% failure rate >= 50%
        cb.record_success()
        cb.record_success()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_sliding_window_respects_minimum_calls(self) -> None:
        cb = CircuitBreaker(
            CircuitBreakerConfig(
                sliding_window_size=10,
                failure_rate_threshold=0.5,
                minimum_calls=5,
            )
        )
        # 3 failures out of 3 calls = 100% rate, but only 3 < minimum_calls=5
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_sliding_window_evicts_old_entries(self) -> None:
        """Old entries are evicted from the deque as new ones are added."""
        cb = CircuitBreaker(
            CircuitBreakerConfig(
                sliding_window_size=5,
                failure_rate_threshold=0.5,
                minimum_calls=5,
            )
        )
        # Start with 4 successes + 1 failure = 20% rate (below 50%), stays closed
        for _ in range(4):
            cb.record_success()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

        # Add 5 more successes — old entries evicted, window: [S, S, S, S, S]
        for _ in range(5):
            cb.record_success()
        # The single failure was evicted
        metrics = cb.metrics
        assert metrics["failure_rate"] == 0.0
        assert metrics["total_calls"] == 5

    def test_sliding_window_recovery_clears_window(self) -> None:
        cb = CircuitBreaker(
            CircuitBreakerConfig(
                sliding_window_size=5,
                failure_rate_threshold=0.5,
                minimum_calls=3,
                recovery_timeout=0.05,
                success_threshold=1,
            )
        )
        # Open the circuit
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Wait for recovery
        time.sleep(0.1)
        assert cb.state == CircuitState.HALF_OPEN

        # Success in half-open closes circuit and clears window
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_metrics_property(self) -> None:
        cb = CircuitBreaker(
            CircuitBreakerConfig(
                sliding_window_size=10,
                failure_rate_threshold=0.8,  # High threshold so it doesn't trip
                minimum_calls=2,
            )
        )
        cb.record_success()
        cb.record_failure()
        cb.record_success()

        metrics = cb.metrics
        assert metrics["total_calls"] == 3
        assert abs(metrics["failure_rate"] - 1 / 3) < 0.01
        assert metrics["state"] == "closed"

    def test_metrics_empty_window(self) -> None:
        cb = CircuitBreaker(CircuitBreakerConfig(sliding_window_size=10))
        metrics = cb.metrics
        assert metrics["total_calls"] == 0
        assert metrics["failure_rate"] == 0.0

    def test_metrics_consecutive_mode(self) -> None:
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=5))
        metrics = cb.metrics
        assert metrics["total_calls"] == 0


class TestSlowCallDetection:
    """Tests for slow call rate detection."""

    def test_slow_call_opens_circuit(self) -> None:
        cb = CircuitBreaker(
            CircuitBreakerConfig(
                sliding_window_size=5,
                failure_rate_threshold=1.0,  # Won't trip on failures
                minimum_calls=3,
                slow_call_duration=0.1,
                slow_call_rate_threshold=0.5,
            )
        )
        # 3 slow successes out of 3 = 100% slow rate >= 50%
        cb.record_success(duration=0.2)
        cb.record_success(duration=0.2)
        cb.record_success(duration=0.2)
        assert cb.state == CircuitState.OPEN

    def test_slow_call_below_threshold_stays_closed(self) -> None:
        cb = CircuitBreaker(
            CircuitBreakerConfig(
                sliding_window_size=10,
                failure_rate_threshold=1.0,
                minimum_calls=4,
                slow_call_duration=0.1,
                slow_call_rate_threshold=0.5,
            )
        )
        # 1 slow + 3 fast = 25% slow rate < 50%
        cb.record_success(duration=0.2)
        cb.record_success(duration=0.01)
        cb.record_success(duration=0.01)
        cb.record_success(duration=0.01)
        assert cb.state == CircuitState.CLOSED

    def test_slow_call_metrics(self) -> None:
        cb = CircuitBreaker(
            CircuitBreakerConfig(
                sliding_window_size=10,
                minimum_calls=2,
                slow_call_duration=0.1,
                slow_call_rate_threshold=1.0,
            )
        )
        cb.record_success(duration=0.2)  # slow
        cb.record_success(duration=0.01)  # fast
        metrics = cb.metrics
        assert metrics["slow_call_rate"] == 0.5

    def test_slow_call_event_emitted(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            circuit_breaker=CircuitBreakerConfig(
                sliding_window_size=10,
                minimum_calls=1,
                slow_call_duration=0.01,
                slow_call_rate_threshold=1.0,
            ),
            listeners=[events.append],
        )
        def slow_func() -> str:
            time.sleep(0.02)
            return "ok"

        slow_func()
        event_types = [e.event_type for e in events]
        assert EventType.SLOW_CALL in event_types


class TestSlidingWindowDecorator:
    """Integration tests with @resilient decorator."""

    def test_sliding_window_with_decorator(self) -> None:
        call_count = 0

        @resilient(
            circuit_breaker=CircuitBreakerConfig(
                sliding_window_size=4,
                failure_rate_threshold=0.5,
                minimum_calls=4,
                recovery_timeout=10,
            ),
        )
        def maybe_fail(should_fail: bool) -> str:
            nonlocal call_count
            call_count += 1
            if should_fail:
                raise ValueError("fail")
            return "ok"

        # 2 successes, then 2 failures = 50% rate -> opens
        maybe_fail(False)
        maybe_fail(False)
        with pytest.raises(ValueError):
            maybe_fail(True)
        with pytest.raises(ValueError):
            maybe_fail(True)

        # Now circuit should be open
        with pytest.raises(RuntimeError, match="Circuit breaker is open"):
            maybe_fail(False)
        assert call_count == 4

    @pytest.mark.asyncio
    async def test_sliding_window_async(self) -> None:
        call_count = 0

        @resilient(
            circuit_breaker=CircuitBreakerConfig(
                sliding_window_size=4,
                failure_rate_threshold=0.5,
                minimum_calls=4,
                recovery_timeout=10,
            ),
        )
        async def maybe_fail(should_fail: bool) -> str:
            nonlocal call_count
            call_count += 1
            if should_fail:
                raise ValueError("fail")
            return "ok"

        await maybe_fail(False)
        await maybe_fail(False)
        with pytest.raises(ValueError):
            await maybe_fail(True)
        with pytest.raises(ValueError):
            await maybe_fail(True)

        with pytest.raises(RuntimeError, match="Circuit breaker is open"):
            await maybe_fail(False)
        assert call_count == 4


class TestBackwardCompatibility:
    """Ensure consecutive count mode still works exactly as before."""

    def test_consecutive_mode_unchanged(self) -> None:
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3))
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_success_resets_consecutive_count(self) -> None:
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3))
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_default_config_uses_consecutive_mode(self) -> None:
        config = CircuitBreakerConfig()
        assert config.sliding_window_size == 0
        assert config.failure_threshold == 5
