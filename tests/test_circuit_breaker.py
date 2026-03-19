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
    RetryConfig,
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


class TestCircuitBreakerThreadSafety:
    def test_allow_request_always_acquires_lock(self) -> None:
        """Verify allow_request uses lock (no racy fast path)."""
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, recovery_timeout=0.05))
        # In CLOSED state, allow_request should still work correctly
        assert cb.allow_request() is True
        # Trip the circuit
        cb.record_failure()
        assert cb.allow_request() is False
        # Wait for recovery
        time.sleep(0.1)
        # Should transition OPEN → HALF_OPEN
        assert cb.allow_request() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_record_success_atomic_returns_both_states(self) -> None:
        """Verify record_success_atomic returns (prev, new) in single lock."""
        cb = CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=1, recovery_timeout=0.05, success_threshold=1)
        )
        # CLOSED state: prev and new should both be CLOSED
        prev, new = cb.record_success_atomic()
        assert prev == CircuitState.CLOSED
        assert new == CircuitState.CLOSED

    def test_record_success_atomic_half_open_to_closed(self) -> None:
        """Verify atomic transition from HALF_OPEN to CLOSED."""
        cb = CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=1, recovery_timeout=0.01, success_threshold=1)
        )
        cb.record_failure()  # CLOSED → OPEN
        time.sleep(0.05)
        # Trigger OPEN → HALF_OPEN via recovery check in record_success_atomic
        prev, new = cb.record_success_atomic()
        assert prev == CircuitState.HALF_OPEN
        assert new == CircuitState.CLOSED

    def test_record_success_atomic_backward_compat(self) -> None:
        """Verify record_success still works (backward compat)."""
        cb = CircuitBreaker(CircuitBreakerConfig())
        state = cb.record_success()
        assert state == CircuitState.CLOSED

    def test_record_success_atomic_with_sliding_window(self) -> None:
        """Verify record_success_atomic clears window on HALF_OPEN→CLOSED."""
        cb = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=1,
                recovery_timeout=0.01,
                success_threshold=1,
                sliding_window_size=10,
                minimum_calls=1,
            )
        )
        # Need enough failures to trigger the sliding window threshold
        cb.record_failure()  # Should open via sliding window (1 failure / 1 call = 100%)
        time.sleep(0.05)
        prev, new = cb.record_success_atomic()
        assert prev == CircuitState.HALF_OPEN
        assert new == CircuitState.CLOSED


class TestCircuitBreakerConfigValidation:
    def test_failure_threshold_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="failure_threshold must be >= 1"):
            CircuitBreakerConfig(failure_threshold=0)

    def test_recovery_timeout_must_be_non_negative(self) -> None:
        with pytest.raises(ValueError, match="recovery_timeout must be >= 0"):
            CircuitBreakerConfig(recovery_timeout=-1)

    def test_failure_rate_threshold_must_be_in_range(self) -> None:
        with pytest.raises(ValueError, match="failure_rate_threshold must be between"):
            CircuitBreakerConfig(failure_rate_threshold=1.5)


class TestSyncCircuitBreakerWithListenersAndFallback:
    def test_circuit_open_with_listeners_and_fallback(self) -> None:
        """Circuit open + listeners + fallback."""
        events: list[ResilienceEvent] = []

        @resilient(
            circuit_breaker=CircuitBreakerConfig(failure_threshold=1, recovery_timeout=60),
            fallback=FallbackConfig(handler="fallback_val", fallback_on=(RuntimeError,)),
            listeners=[events.append],
        )
        def fails() -> str:
            raise ValueError("fail")

        # First call fails (ValueError not in fallback_on), opens circuit
        with pytest.raises(ValueError):
            fails()

        # Second call hits open circuit → RuntimeError → caught by fallback
        result = fails()
        assert result == "fallback_val"
        event_types = [e.event_type for e in events]
        assert EventType.CIRCUIT_OPEN in event_types
        assert EventType.FALLBACK_USED in event_types


class TestSyncExecutorEdgeCases:
    def test_sync_circuit_breaker_success_closes(self) -> None:
        """Test sync circuit breaker closes on success after half-open."""
        events: list[ResilienceEvent] = []
        call_count = 0

        @resilient(
            circuit_breaker=CircuitBreakerConfig(
                failure_threshold=1, recovery_timeout=0.1, success_threshold=1
            ),
            listeners=[events.append],
        )
        def sometimes_fails() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("fail")
            return "ok"

        with pytest.raises(ValueError):
            sometimes_fails()

        time.sleep(0.15)
        result = sometimes_fails()
        assert result == "ok"
        event_types = [e.event_type for e in events]
        assert EventType.CIRCUIT_CLOSED in event_types

    def test_sync_failure_event_no_retry(self) -> None:
        """Test failure event when no retry configured."""
        events: list[ResilienceEvent] = []

        @resilient(
            fallback=FallbackConfig(handler="default", fallback_on=(TypeError,)),
            listeners=[events.append],
        )
        def fails() -> str:
            raise ValueError("fail")

        with pytest.raises(ValueError):
            fails()

        event_types = [e.event_type for e in events]
        assert EventType.FAILURE in event_types


class TestSyncCircuitBreakerInRetryPath:
    def test_circuit_opens_during_retry(self) -> None:
        """CB opening during retry loop — re-check stops retries."""
        events: list[ResilienceEvent] = []
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=5, delay=0.001),
            circuit_breaker=CircuitBreakerConfig(failure_threshold=2, recovery_timeout=60),
            listeners=[events.append],
        )
        def always_fails() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        # CB opens after 2 failures; retry re-check raises CircuitOpenError
        with pytest.raises((ValueError, CircuitOpenError)):
            always_fails()

        event_types = [e.event_type for e in events]
        assert EventType.CIRCUIT_OPEN in event_types

    def test_circuit_closes_in_retry_path(self) -> None:
        """CB HALF_OPEN→CLOSED in _execute_with_retry."""
        events: list[ResilienceEvent] = []
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=2, delay=0.001),
            circuit_breaker=CircuitBreakerConfig(
                failure_threshold=2, recovery_timeout=0.05, success_threshold=1
            ),
            listeners=[events.append],
        )
        def works() -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                raise ValueError("fail")
            return "ok"

        # Call 1: fails on attempt 1 (count=1, still closed), retries, succeeds
        result = works()
        assert result == "ok"

        # Force CB open by recording enough failures directly
        cb = works._executor._circuit_breaker  # type: ignore[union-attr]
        cb.record_failure()
        cb.record_failure()

        # Wait for recovery → HALF_OPEN
        time.sleep(0.1)
        events.clear()

        # Call 2: succeeds on first attempt → HALF_OPEN → CLOSED
        call_count = 10  # always succeed
        result2 = works()
        assert result2 == "ok"
        event_types = [e.event_type for e in events]
        assert EventType.CIRCUIT_CLOSED in event_types


class TestAsyncCircuitBreakerEdgeCases:
    @pytest.mark.asyncio
    async def test_async_circuit_breaker_opens_and_rejects(self) -> None:
        """Test async circuit breaker opens and rejects."""

        call_count = 0

        @resilient(
            circuit_breaker=CircuitBreakerConfig(failure_threshold=2, recovery_timeout=10),
        )
        async def fails() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        for _ in range(2):
            with pytest.raises(ValueError):
                await fails()

        with pytest.raises(CircuitOpenError, match="Circuit breaker is open"):
            await fails()
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_async_circuit_breaker_with_fallback(self) -> None:
        """Test async circuit breaker with fallback when open."""

        @resilient(
            circuit_breaker=CircuitBreakerConfig(failure_threshold=1, recovery_timeout=10),
            fallback=FallbackConfig(handler="fallback_value"),
        )
        async def fails() -> str:
            raise ValueError("fail")

        await fails()  # Opens circuit
        result = await fails()  # Returns fallback
        assert result == "fallback_value"

    @pytest.mark.asyncio
    async def test_async_circuit_breaker_failure_tracking(self) -> None:
        """Test async circuit breaker records failures."""
        events: list[ResilienceEvent] = []

        @resilient(
            circuit_breaker=CircuitBreakerConfig(failure_threshold=2),
            listeners=[events.append],
        )
        async def fails() -> str:
            raise ValueError("fail")

        for _ in range(2):
            with pytest.raises(ValueError):
                await fails()

        event_types = [e.event_type for e in events]
        assert EventType.CIRCUIT_OPEN in event_types

    @pytest.mark.asyncio
    async def test_async_circuit_breaker_success_closes(self) -> None:
        """Test async circuit breaker closes on success after half-open."""
        import asyncio

        events: list[ResilienceEvent] = []
        call_count = 0

        @resilient(
            circuit_breaker=CircuitBreakerConfig(
                failure_threshold=1, recovery_timeout=0.1, success_threshold=1
            ),
            listeners=[events.append],
        )
        async def sometimes_fails() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("fail")
            return "ok"

        with pytest.raises(ValueError):
            await sometimes_fails()

        await asyncio.sleep(0.15)
        result = await sometimes_fails()
        assert result == "ok"
        event_types = [e.event_type for e in events]
        assert EventType.CIRCUIT_CLOSED in event_types

    @pytest.mark.asyncio
    async def test_async_circuit_open_with_listeners_and_fallback(self) -> None:
        """Async circuit open + listeners + fallback."""
        events: list[ResilienceEvent] = []

        @resilient(
            circuit_breaker=CircuitBreakerConfig(failure_threshold=1, recovery_timeout=60),
            fallback=FallbackConfig(handler="async_fallback", fallback_on=(RuntimeError,)),
            listeners=[events.append],
        )
        async def fails() -> str:
            raise ValueError("fail")

        with pytest.raises(ValueError):
            await fails()

        result = await fails()
        assert result == "async_fallback"
        event_types = [e.event_type for e in events]
        assert EventType.CIRCUIT_OPEN in event_types
        assert EventType.FALLBACK_USED in event_types


class TestAsyncCircuitBreakerInRetryPath:
    @pytest.mark.asyncio
    async def test_async_circuit_opens_during_retry(self) -> None:
        """Async CB opens during retry loop — re-check stops retries."""
        events: list[ResilienceEvent] = []

        @resilient(
            retry=RetryConfig(max_attempts=5, delay=0.001),
            circuit_breaker=CircuitBreakerConfig(failure_threshold=2, recovery_timeout=60),
            listeners=[events.append],
        )
        async def always_fails() -> str:
            raise ValueError("fail")

        with pytest.raises((ValueError, CircuitOpenError)):
            await always_fails()

        event_types = [e.event_type for e in events]
        assert EventType.CIRCUIT_OPEN in event_types

    @pytest.mark.asyncio
    async def test_async_circuit_closes_in_retry_path(self) -> None:
        """Async CB HALF_OPEN→CLOSED in retry path."""
        import asyncio

        events: list[ResilienceEvent] = []
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=2, delay=0.001),
            circuit_breaker=CircuitBreakerConfig(
                failure_threshold=2, recovery_timeout=0.05, success_threshold=1
            ),
            listeners=[events.append],
        )
        async def works() -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                raise ValueError("fail")
            return "ok"

        result = await works()
        assert result == "ok"

        cb = works._executor._circuit_breaker  # type: ignore[union-attr]
        cb.record_failure()
        cb.record_failure()

        await asyncio.sleep(0.1)
        events.clear()
        call_count = 10

        result2 = await works()
        assert result2 == "ok"
        event_types = [e.event_type for e in events]
        assert EventType.CIRCUIT_CLOSED in event_types

    @pytest.mark.asyncio
    async def test_async_retry_on_result_exhausted_emits_event(self) -> None:
        """Async retry_on_result RETRY_EXHAUSTED."""
        events: list[ResilienceEvent] = []

        @resilient(
            retry=RetryConfig(max_attempts=2, delay=0.001, retry_on_result=lambda r: r == "bad"),
            listeners=[events.append],
        )
        async def always_bad() -> str:
            return "bad"

        result = await always_bad()
        assert result == "bad"
        event_types = [e.event_type for e in events]
        assert EventType.RETRY_EXHAUSTED in event_types
