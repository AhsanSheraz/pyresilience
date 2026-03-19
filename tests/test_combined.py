"""Tests for combined resilience patterns."""

from __future__ import annotations

import time

import pytest

from pyresilience import (
    CircuitBreakerConfig,
    CircuitOpenError,
    EventType,
    FallbackConfig,
    ResilienceEvent,
    RetryConfig,
    TimeoutConfig,
    resilient,
)


class TestCombinedPatterns:
    def test_retry_with_timeout(self) -> None:
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
            timeout=TimeoutConfig(seconds=0.5),
        )
        def sometimes_slow() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                time.sleep(2)  # Trigger timeout
            return "ok"

        result = sometimes_slow()
        assert result == "ok"
        assert call_count == 2

    def test_retry_with_fallback(self) -> None:
        @resilient(
            retry=RetryConfig(max_attempts=2, delay=0.01),
            fallback=FallbackConfig(handler="fallback_value"),
        )
        def always_fails() -> str:
            raise ValueError("fail")

        assert always_fails() == "fallback_value"

    def test_circuit_breaker_with_retry(self) -> None:
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=2, delay=0.01),
            circuit_breaker=CircuitBreakerConfig(failure_threshold=3),
        )
        def fails() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        # Each call retries twice, so 2 calls = 4 failures > threshold of 3
        for _ in range(2):
            with pytest.raises(ValueError):
                fails()

        # Circuit should be open now
        with pytest.raises(CircuitOpenError, match="Circuit breaker is open"):
            fails()

    def test_all_patterns_success(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            retry=RetryConfig(max_attempts=2, delay=0.01),
            timeout=TimeoutConfig(seconds=5.0),
            circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
            fallback=FallbackConfig(handler="fallback"),
            listeners=[events.append],
        )
        def works() -> str:
            return "success"

        result = works()
        assert result == "success"
        event_types = [e.event_type for e in events]
        assert EventType.SUCCESS in event_types

    def test_all_patterns_failure_with_fallback(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            retry=RetryConfig(max_attempts=2, delay=0.01),
            timeout=TimeoutConfig(seconds=5.0),
            circuit_breaker=CircuitBreakerConfig(failure_threshold=10),
            fallback=FallbackConfig(handler=lambda e: "graceful_degradation"),
            listeners=[events.append],
        )
        def always_fails() -> str:
            raise ValueError("fail")

        result = always_fails()
        assert result == "graceful_degradation"
        event_types = [e.event_type for e in events]
        assert EventType.RETRY in event_types
        assert EventType.RETRY_EXHAUSTED in event_types
        assert EventType.FALLBACK_USED in event_types


class TestCombinedAsync:
    @pytest.mark.asyncio
    async def test_async_retry_with_fallback(self) -> None:
        @resilient(
            retry=RetryConfig(max_attempts=2, delay=0.01),
            fallback=FallbackConfig(handler="async_fallback"),
        )
        async def always_fails() -> str:
            raise ValueError("fail")

        assert await always_fails() == "async_fallback"
