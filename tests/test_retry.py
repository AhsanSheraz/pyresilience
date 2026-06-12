"""Tests for retry functionality."""

from __future__ import annotations

import pytest

from pyresilience import (
    EventType,
    FallbackConfig,
    ResilienceEvent,
    RetryConfig,
    resilient,
)


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
        """Bare @resilient is a passthrough - no patterns enabled."""
        call_count = 0

        @resilient
        def fails() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("no retry")

        with pytest.raises(ValueError, match="no retry"):
            fails()
        assert call_count == 1


class TestMaxDelayCap:
    def test_max_delay_caps_computed_delay(self) -> None:
        """Verify max_delay caps the computed backoff delay."""
        call_count = 0

        @resilient(
            retry=RetryConfig(
                max_attempts=3,
                delay=10.0,
                backoff_factor=10.0,
                max_delay=0.01,
                jitter=False,
            ),
        )
        def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "ok"

        result = flaky()
        assert result == "ok"
        assert call_count == 3


class TestSyncRetryOnResultRetries:
    def test_retry_on_result_retries_then_succeeds(self) -> None:
        """Test retry_on_result retries and eventually returns good result."""
        events: list[ResilienceEvent] = []
        call_count = 0

        @resilient(
            retry=RetryConfig(
                max_attempts=3,
                delay=0.001,
                retry_on_result=lambda r: r == "bad",
            ),
            listeners=[events.append],
        )
        def eventually_good() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return "bad"
            return "good"

        result = eventually_good()
        assert result == "good"
        assert call_count == 3
        event_types = [e.event_type for e in events]
        assert EventType.RETRY in event_types

    def test_retry_on_result_exhausted_emits_event(self) -> None:
        """On last attempt, if predicate matches, RETRY_EXHAUSTED is emitted."""
        events: list[ResilienceEvent] = []

        @resilient(
            retry=RetryConfig(
                max_attempts=2,
                delay=0.001,
                retry_on_result=lambda r: r == "bad",
            ),
            listeners=[events.append],
        )
        def always_bad() -> str:
            return "bad"

        result = always_bad()
        assert result == "bad"
        event_types = [e.event_type for e in events]
        assert EventType.RETRY_EXHAUSTED in event_types


class TestRetryIgnoreOn:
    def test_ignore_on_exception_raises_immediately(self) -> None:
        """ignore_on exception raises verbatim on first attempt, no retry."""
        call_count = 0

        @resilient(retry=RetryConfig(max_attempts=3, delay=0.01, ignore_on=[ValueError]))
        def fails_with_ignored_error() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("ignored error")

        with pytest.raises(ValueError, match="ignored error"):
            fails_with_ignored_error()
        assert call_count == 1

    def test_ignore_on_takes_precedence_over_retry_on(self) -> None:
        """When class is in both ignore_on and retry_on, it is ignored."""
        call_count = 0

        @resilient(
            retry=RetryConfig(
                max_attempts=3,
                delay=0.01,
                retry_on=[ValueError],
                ignore_on=[ValueError],
            )
        )
        def fails_with_both() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("should not retry")

        with pytest.raises(ValueError, match="should not retry"):
            fails_with_both()
        assert call_count == 1

    def test_ignore_on_bypasses_fallback(self) -> None:
        """ignore_on exception is never caught by fallback_on handler."""
        call_count = 0
        fallback_calls = []

        def fallback_handler(e: BaseException) -> str:
            fallback_calls.append(e)
            return "fallback"

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, ignore_on=[ValueError]),
            fallback=FallbackConfig(
                handler=fallback_handler,
                fallback_on=[ValueError],
            ),
        )
        def fails_with_ignored_error() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("ignored error")

        with pytest.raises(ValueError, match="ignored error"):
            fails_with_ignored_error()
        assert call_count == 1
        assert len(fallback_calls) == 0

    def test_ignore_on_exception_emits_single_failure_event(self) -> None:
        """ignore_on exception emits exactly one FAILURE event, no RETRY."""
        events: list[ResilienceEvent] = []

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, ignore_on=[ValueError]),
            listeners=[events.append],
        )
        def fails_with_ignored_error() -> str:
            raise ValueError("ignored error")

        with pytest.raises(ValueError, match="ignored error"):
            fails_with_ignored_error()

        event_types = [e.event_type for e in events]
        failure_events = [e for e in events if e.event_type == EventType.FAILURE]
        assert len(failure_events) == 1
        assert failure_events[0].attempt == 1
        assert isinstance(failure_events[0].error, ValueError)
        assert EventType.RETRY not in event_types

    def test_ignore_on_empty_tuple_allows_retry(self) -> None:
        """ignore_on=() (default) allows normal retry behavior."""
        call_count = 0

        @resilient(retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False, ignore_on=()))
        def fails_twice() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "ok"

        result = fails_twice()
        assert result == "ok"
        assert call_count == 3

    def test_ignore_on_non_matching_uses_retry(self) -> None:
        """When raised exception doesn't match ignore_on, normal retry applies."""
        call_count = 0

        @resilient(retry=RetryConfig(max_attempts=3, delay=0.01, ignore_on=[KeyError]))
        def fails_with_value_error() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not ignored")
            return "ok"

        result = fails_with_value_error()
        assert result == "ok"
        assert call_count == 3


class TestRetryIgnoreOnAsync:
    async def test_ignore_on_exception_raises_immediately(self) -> None:
        """ignore_on exception raises verbatim on first attempt, no retry."""
        call_count = 0

        @resilient(retry=RetryConfig(max_attempts=3, delay=0.01, ignore_on=[ValueError]))
        async def fails_with_ignored_error() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("ignored error")

        with pytest.raises(ValueError, match="ignored error"):
            await fails_with_ignored_error()
        assert call_count == 1

    async def test_ignore_on_takes_precedence_over_retry_on(self) -> None:
        """When class is in both ignore_on and retry_on, it is ignored."""
        call_count = 0

        @resilient(
            retry=RetryConfig(
                max_attempts=3,
                delay=0.01,
                retry_on=[ValueError],
                ignore_on=[ValueError],
            )
        )
        async def fails_with_both() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("should not retry")

        with pytest.raises(ValueError, match="should not retry"):
            await fails_with_both()
        assert call_count == 1

    async def test_ignore_on_bypasses_fallback(self) -> None:
        """ignore_on exception is never caught by fallback_on handler."""
        call_count = 0

        def fallback_handler(e: BaseException) -> str:
            return "fallback"

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, ignore_on=[ValueError]),
            fallback=FallbackConfig(
                handler=fallback_handler,
                fallback_on=[ValueError],
            ),
        )
        async def fails_with_ignored_error() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("ignored error")

        with pytest.raises(ValueError, match="ignored error"):
            await fails_with_ignored_error()
        assert call_count == 1

    async def test_ignore_on_exception_emits_single_failure_event(self) -> None:
        """ignore_on exception emits exactly one FAILURE event, no RETRY."""
        events: list[ResilienceEvent] = []

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, ignore_on=[ValueError]),
            listeners=[events.append],
        )
        async def fails_with_ignored_error() -> str:
            raise ValueError("ignored error")

        with pytest.raises(ValueError, match="ignored error"):
            await fails_with_ignored_error()

        event_types = [e.event_type for e in events]
        failure_events = [e for e in events if e.event_type == EventType.FAILURE]
        assert len(failure_events) == 1
        assert failure_events[0].attempt == 1
        assert isinstance(failure_events[0].error, ValueError)
        assert EventType.RETRY not in event_types

    async def test_ignore_on_empty_tuple_allows_retry(self) -> None:
        """ignore_on=() (default) allows normal retry behavior."""
        call_count = 0

        @resilient(retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False, ignore_on=()))
        async def fails_twice() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "ok"

        result = await fails_twice()
        assert result == "ok"
        assert call_count == 3

    async def test_ignore_on_non_matching_uses_retry(self) -> None:
        """When raised exception doesn't match ignore_on, normal retry applies."""
        call_count = 0

        @resilient(retry=RetryConfig(max_attempts=3, delay=0.01, ignore_on=[KeyError]))
        async def fails_with_value_error() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not ignored")
            return "ok"

        result = await fails_with_value_error()
        assert result == "ok"
        assert call_count == 3


class TestRetryConfigValidation:
    def test_max_attempts_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="max_attempts must be >= 1"):
            RetryConfig(max_attempts=0)

    def test_delay_must_be_non_negative(self) -> None:
        with pytest.raises(ValueError, match="delay must be >= 0"):
            RetryConfig(delay=-1)

    def test_max_delay_must_be_non_negative(self) -> None:
        with pytest.raises(ValueError, match="max_delay must be >= 0"):
            RetryConfig(max_delay=-1)
