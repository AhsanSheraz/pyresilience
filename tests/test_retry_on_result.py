"""Tests for retry_on_result predicate feature."""

from __future__ import annotations

import pytest

from pyresilience import EventType, ResilienceEvent, RetryConfig, resilient


class TestRetryOnResultSync:
    """Sync tests for retry_on_result."""

    def test_retries_when_predicate_returns_true(self) -> None:
        call_count = 0

        @resilient(
            retry=RetryConfig(
                max_attempts=3,
                delay=0.001,
                jitter=False,
                retry_on_result=lambda r: r == "not_ready",
            )
        )
        def sometimes_not_ready() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return "not_ready"
            return "ready"

        result = sometimes_not_ready()
        assert result == "ready"
        assert call_count == 3

    def test_no_retry_when_predicate_returns_false(self) -> None:
        call_count = 0

        @resilient(
            retry=RetryConfig(
                max_attempts=3,
                delay=0.001,
                retry_on_result=lambda r: r == "not_ready",
            )
        )
        def always_ready() -> str:
            nonlocal call_count
            call_count += 1
            return "ready"

        result = always_ready()
        assert result == "ready"
        assert call_count == 1

    def test_exhausts_retries_on_result(self) -> None:
        """When all attempts return a retryable result, returns the last result."""
        call_count = 0

        @resilient(
            retry=RetryConfig(
                max_attempts=3,
                delay=0.001,
                jitter=False,
                retry_on_result=lambda r: r == "pending",
            )
        )
        def always_pending() -> str:
            nonlocal call_count
            call_count += 1
            return "pending"

        # Should not raise — just returns the last result
        always_pending()
        # The function ran max_attempts times but always returned "pending"
        assert call_count == 3

    def test_retry_on_http_status(self) -> None:
        """Real-world pattern: retry on HTTP 429 or 503."""
        call_count = 0

        @resilient(
            retry=RetryConfig(
                max_attempts=3,
                delay=0.001,
                jitter=False,
                retry_on_result=lambda r: r.get("status") in (429, 503),
            )
        )
        def call_api() -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"status": 429, "body": "rate limited"}
            if call_count == 2:
                return {"status": 503, "body": "unavailable"}
            return {"status": 200, "body": "ok"}

        result = call_api()
        assert result["status"] == 200
        assert call_count == 3

    def test_retry_events_emitted_for_result_predicate(self) -> None:
        events: list[ResilienceEvent] = []
        call_count = 0

        @resilient(
            retry=RetryConfig(
                max_attempts=3,
                delay=0.001,
                jitter=False,
                retry_on_result=lambda r: r == "not_ready",
            ),
            listeners=[events.append],
        )
        def not_ready_then_ready() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return "not_ready"
            return "ready"

        not_ready_then_ready()
        event_types = [e.event_type for e in events]
        assert EventType.RETRY in event_types
        assert EventType.SUCCESS in event_types

    def test_retry_on_result_combined_with_exception_retry(self) -> None:
        """Both retry_on_result and retry_on exception types should work together."""
        call_count = 0

        @resilient(
            retry=RetryConfig(
                max_attempts=4,
                delay=0.001,
                jitter=False,
                retry_on=(ValueError,),
                retry_on_result=lambda r: r == "pending",
            )
        )
        def mixed_failures() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("transient")
            if call_count == 2:
                return "pending"
            return "done"

        result = mixed_failures()
        assert result == "done"
        assert call_count == 3

    def test_no_retry_on_result_by_default(self) -> None:
        """Default RetryConfig should not have retry_on_result."""
        config = RetryConfig()
        assert config.retry_on_result is None


class TestRetryOnResultAsync:
    """Async tests for retry_on_result."""

    @pytest.mark.asyncio
    async def test_async_retries_on_result(self) -> None:
        call_count = 0

        @resilient(
            retry=RetryConfig(
                max_attempts=3,
                delay=0.001,
                jitter=False,
                retry_on_result=lambda r: r == "not_ready",
            )
        )
        async def async_not_ready() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return "not_ready"
            return "ready"

        result = await async_not_ready()
        assert result == "ready"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_async_no_retry_when_predicate_false(self) -> None:
        call_count = 0

        @resilient(
            retry=RetryConfig(
                max_attempts=3,
                delay=0.001,
                retry_on_result=lambda r: r == "not_ready",
            )
        )
        async def async_ready() -> str:
            nonlocal call_count
            call_count += 1
            return "ready"

        result = await async_ready()
        assert result == "ready"
        assert call_count == 1
