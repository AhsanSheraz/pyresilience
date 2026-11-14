"""Tests for the overall deadline (total_seconds)."""

from __future__ import annotations

import asyncio
import time

import pytest

from pyresilience import (
    EventType,
    FallbackConfig,
    ResilienceEvent,
    ResilienceTimeoutError,
    RetryConfig,
    TimeoutConfig,
    resilient,
)


class TestTotalDeadlineSync:
    def test_stops_retrying_when_budget_cannot_cover_next_delay(self) -> None:
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=10, delay=0.05, jitter=False),
            timeout=TimeoutConfig(seconds=5.0, total_seconds=0.5),
        )
        def always_fails() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("boom")

        start = time.monotonic()
        with pytest.raises(ResilienceTimeoutError, match="total timeout budget") as info:
            always_fails()
        elapsed = time.monotonic() - start

        assert isinstance(info.value.__cause__, ValueError)
        # Delays 0.05 + 0.1 + 0.2 fit in 0.5s; the next 0.4s delay does not.
        assert 1 <= call_count < 10
        # Generous bound for Windows timer precision: never sleeps the 0.4s delay
        assert elapsed < 0.9

    def test_attempt_is_clamped_to_remaining_budget(self) -> None:
        @resilient(timeout=TimeoutConfig(seconds=5.0, total_seconds=0.2))
        def slow() -> str:
            time.sleep(1.0)
            return "late"

        start = time.monotonic()
        with pytest.raises(ResilienceTimeoutError):
            slow()
        # The 5s per-attempt limit must not apply: the 0.2s total wins
        assert time.monotonic() - start < 0.9

    def test_per_attempt_limit_still_applies_inside_total(self) -> None:
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
            timeout=TimeoutConfig(seconds=0.1, total_seconds=5.0),
        )
        def slow_then_fast() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                time.sleep(0.5)
            return "ok"

        assert slow_then_fast() == "ok"
        assert call_count == 2

    def test_fallback_applies_when_budget_is_spent(self) -> None:
        @resilient(
            retry=RetryConfig(max_attempts=5, delay=1.0, jitter=False),
            timeout=TimeoutConfig(seconds=1.0, total_seconds=0.2),
            fallback=FallbackConfig(handler=lambda exc: type(exc).__name__),
        )
        def always_fails() -> str:
            raise ValueError("boom")

        assert always_fails() == "ResilienceTimeoutError"

    def test_events_on_total_timeout(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            retry=RetryConfig(max_attempts=5, delay=1.0, jitter=False),
            timeout=TimeoutConfig(seconds=1.0, total_seconds=0.2),
            listeners=[events.append],
        )
        def always_fails() -> str:
            raise ValueError("boom")

        with pytest.raises(ResilienceTimeoutError):
            always_fails()

        timeouts = [e for e in events if e.event_type == EventType.TIMEOUT]
        assert len(timeouts) == 1
        assert "total" in timeouts[0].detail
        assert events[-1].event_type == EventType.FAILURE
        assert isinstance(events[-1].error, ResilienceTimeoutError)
        assert not [e for e in events if e.event_type == EventType.RETRY]

    def test_fallback_event_on_total_timeout(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            retry=RetryConfig(max_attempts=5, delay=1.0, jitter=False),
            timeout=TimeoutConfig(seconds=1.0, total_seconds=0.2),
            fallback=FallbackConfig(handler="fallback"),
            listeners=[events.append],
        )
        def always_fails() -> str:
            raise ValueError("boom")

        assert always_fails() == "fallback"
        assert events[-1].event_type == EventType.FALLBACK_USED

    def test_result_predicate_returns_last_result_when_budget_is_spent(self) -> None:
        events: list[ResilienceEvent] = []
        call_count = 0

        @resilient(
            retry=RetryConfig(
                max_attempts=5, delay=1.0, jitter=False, retry_on_result=lambda r: True
            ),
            timeout=TimeoutConfig(seconds=1.0, total_seconds=0.2),
            listeners=[events.append],
        )
        def pending() -> int:
            nonlocal call_count
            call_count += 1
            return call_count

        assert pending() == 1
        assert call_count == 1
        exhausted = [e for e in events if e.event_type == EventType.RETRY_EXHAUSTED]
        assert len(exhausted) == 1
        assert exhausted[0].detail == "total timeout budget exhausted"

    def test_result_predicate_without_listeners(self) -> None:
        @resilient(
            retry=RetryConfig(
                max_attempts=5, delay=1.0, jitter=False, retry_on_result=lambda r: True
            ),
            timeout=TimeoutConfig(seconds=1.0, total_seconds=0.2),
        )
        def pending() -> str:
            return "pending"

        assert pending() == "pending"

    def test_per_attempt_false_does_not_sleep_past_deadline(self) -> None:
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=2.0, jitter=False),
            timeout=TimeoutConfig(seconds=0.3, per_attempt=False),
        )
        def always_fails() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("boom")

        start = time.monotonic()
        with pytest.raises(ResilienceTimeoutError, match="total timeout budget"):
            always_fails()
        assert call_count == 1
        # The 2s retry delay is skipped because it cannot fit in the 0.3s budget
        assert time.monotonic() - start < 1.0

    def test_succeeds_within_budget(self) -> None:
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
            timeout=TimeoutConfig(seconds=1.0, total_seconds=5.0),
        )
        def fails_once() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("boom")
            return "ok"

        assert fails_once() == "ok"
        assert call_count == 2


class TestTotalDeadlineAsync:
    async def test_stops_retrying_when_budget_cannot_cover_next_delay(self) -> None:
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=10, delay=0.05, jitter=False),
            timeout=TimeoutConfig(seconds=5.0, total_seconds=0.5),
        )
        async def always_fails() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("boom")

        start = time.monotonic()
        with pytest.raises(ResilienceTimeoutError, match="total timeout budget") as info:
            await always_fails()
        elapsed = time.monotonic() - start

        assert isinstance(info.value.__cause__, ValueError)
        assert 1 <= call_count < 10
        assert elapsed < 0.9

    async def test_attempt_is_clamped_to_remaining_budget(self) -> None:
        @resilient(timeout=TimeoutConfig(seconds=5.0, total_seconds=0.2))
        async def slow() -> str:
            await asyncio.sleep(1.0)
            return "late"

        start = time.monotonic()
        with pytest.raises(ResilienceTimeoutError):
            await slow()
        assert time.monotonic() - start < 0.9

    async def test_per_attempt_limit_still_applies_inside_total(self) -> None:
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
            timeout=TimeoutConfig(seconds=0.1, total_seconds=5.0),
        )
        async def slow_then_fast() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await asyncio.sleep(0.5)
            return "ok"

        assert await slow_then_fast() == "ok"
        assert call_count == 2

    async def test_fallback_applies_when_budget_is_spent(self) -> None:
        async def handler(exc: BaseException) -> str:
            return type(exc).__name__

        @resilient(
            retry=RetryConfig(max_attempts=5, delay=1.0, jitter=False),
            timeout=TimeoutConfig(seconds=1.0, total_seconds=0.2),
            fallback=FallbackConfig(handler=handler),
        )
        async def always_fails() -> str:
            raise ValueError("boom")

        assert await always_fails() == "ResilienceTimeoutError"

    async def test_events_on_total_timeout(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            retry=RetryConfig(max_attempts=5, delay=1.0, jitter=False),
            timeout=TimeoutConfig(seconds=1.0, total_seconds=0.2),
            listeners=[events.append],
        )
        async def always_fails() -> str:
            raise ValueError("boom")

        with pytest.raises(ResilienceTimeoutError):
            await always_fails()

        timeouts = [e for e in events if e.event_type == EventType.TIMEOUT]
        assert len(timeouts) == 1
        assert "total" in timeouts[0].detail
        assert events[-1].event_type == EventType.FAILURE

    async def test_fallback_event_on_total_timeout(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            retry=RetryConfig(max_attempts=5, delay=1.0, jitter=False),
            timeout=TimeoutConfig(seconds=1.0, total_seconds=0.2),
            fallback=FallbackConfig(handler="fallback"),
            listeners=[events.append],
        )
        async def always_fails() -> str:
            raise ValueError("boom")

        assert await always_fails() == "fallback"
        assert events[-1].event_type == EventType.FALLBACK_USED

    async def test_result_predicate_returns_last_result_when_budget_is_spent(self) -> None:
        events: list[ResilienceEvent] = []
        call_count = 0

        @resilient(
            retry=RetryConfig(
                max_attempts=5, delay=1.0, jitter=False, retry_on_result=lambda r: True
            ),
            timeout=TimeoutConfig(seconds=1.0, total_seconds=0.2),
            listeners=[events.append],
        )
        async def pending() -> int:
            nonlocal call_count
            call_count += 1
            return call_count

        assert await pending() == 1
        exhausted = [e for e in events if e.event_type == EventType.RETRY_EXHAUSTED]
        assert len(exhausted) == 1
        assert exhausted[0].detail == "total timeout budget exhausted"

    async def test_result_predicate_without_listeners(self) -> None:
        @resilient(
            retry=RetryConfig(
                max_attempts=5, delay=1.0, jitter=False, retry_on_result=lambda r: True
            ),
            timeout=TimeoutConfig(seconds=1.0, total_seconds=0.2),
        )
        async def pending() -> str:
            return "pending"

        assert await pending() == "pending"

    async def test_per_attempt_false_does_not_sleep_past_deadline(self) -> None:
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=2.0, jitter=False),
            timeout=TimeoutConfig(seconds=0.3, per_attempt=False),
        )
        async def always_fails() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("boom")

        start = time.monotonic()
        with pytest.raises(ResilienceTimeoutError, match="total timeout budget"):
            await always_fails()
        assert call_count == 1
        assert time.monotonic() - start < 1.0

    async def test_succeeds_within_budget(self) -> None:
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
            timeout=TimeoutConfig(seconds=1.0, total_seconds=5.0),
        )
        async def fails_once() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("boom")
            return "ok"

        assert await fails_once() == "ok"
        assert call_count == 2


class TestDeadlineConfigValidation:
    def test_total_seconds_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="total_seconds must be > 0"):
            TimeoutConfig(total_seconds=0)

    def test_total_seconds_requires_per_attempt(self) -> None:
        with pytest.raises(ValueError, match="total_seconds requires per_attempt=True"):
            TimeoutConfig(seconds=1.0, per_attempt=False, total_seconds=5.0)

    def test_stream_idle_seconds_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="stream_idle_seconds must be > 0"):
            TimeoutConfig(stream_idle_seconds=0)

    def test_defaults_keep_new_limits_off(self) -> None:
        config = TimeoutConfig()
        assert config.total_seconds is None
        assert config.stream_idle_seconds is None
