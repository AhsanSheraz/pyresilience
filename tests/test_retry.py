"""Tests for retry functionality."""

from __future__ import annotations

import pytest

from pyresilience import EventType, ResilienceEvent, RetryConfig, resilient


class TestRetrySync:
    def test_succeeds_on_first_attempt(self) -> None:
        @resilient(retry=RetryConfig(max_attempts=3, delay=0.01))
        def always_ok() -> str:
            return "ok"

        assert always_ok() == "ok"

    def test_retries_on_failure_then_succeeds(self) -> None:
        call_count = 0

        @resilient(retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False))
        def fails_twice() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "ok"

        assert fails_twice() == "ok"
        assert call_count == 3

    def test_exhausts_retries(self) -> None:
        @resilient(retry=RetryConfig(max_attempts=2, delay=0.01))
        def always_fails() -> str:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            always_fails()

    def test_retry_on_specific_exceptions(self) -> None:
        call_count = 0

        @resilient(retry=RetryConfig(max_attempts=3, delay=0.01, retry_on=(ValueError,)))
        def fails_with_type_error() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TypeError("wrong type")
            return "ok"

        with pytest.raises(TypeError, match="wrong type"):
            fails_with_type_error()
        assert call_count == 1  # No retry for TypeError

    def test_backoff_factor(self) -> None:
        import time

        call_count = 0
        start = time.monotonic()

        @resilient(retry=RetryConfig(max_attempts=3, delay=0.05, backoff_factor=2.0, jitter=False))
        def fails_then_ok() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("retry")
            return "done"

        result = fails_then_ok()
        elapsed = time.monotonic() - start
        assert result == "done"
        # delay=0.05 + delay=0.1 = 0.15s minimum (use 0.13 for Windows timer precision)
        assert elapsed >= 0.13

    def test_events_emitted(self) -> None:
        events: list[ResilienceEvent] = []
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=2, delay=0.01),
            listeners=[events.append],
        )
        def fails_once() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("fail")
            return "ok"

        fails_once()
        event_types = [e.event_type for e in events]
        assert EventType.RETRY in event_types
        assert EventType.SUCCESS in event_types


class TestRetryAsync:
    @pytest.mark.asyncio
    async def test_async_retry(self) -> None:
        call_count = 0

        @resilient(retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False))
        async def async_fails_twice() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "async ok"

        result = await async_fails_twice()
        assert result == "async ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_async_exhausted(self) -> None:
        @resilient(retry=RetryConfig(max_attempts=2, delay=0.01))
        async def always_fails() -> str:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await always_fails()


class TestBareDecorator:
    def test_bare_decorator_no_retry(self) -> None:
        """Bare @resilient is a passthrough — no patterns enabled."""
        call_count = 0

        @resilient
        def fails() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("no retry")

        with pytest.raises(ValueError, match="no retry"):
            fails()
        assert call_count == 1
