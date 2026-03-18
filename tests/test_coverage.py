"""Additional tests to cover edge cases and boost coverage."""

from __future__ import annotations

import asyncio
import time

import pytest

from pyresilience import (
    BulkheadConfig,
    CircuitBreakerConfig,
    EventType,
    FallbackConfig,
    ResilienceEvent,
    RetryConfig,
    resilient,
)
from pyresilience._bulkhead import AsyncBulkhead, Bulkhead, BulkheadFullError


class TestBulkheadEdgeCases:
    def test_sync_bulkhead_with_wait(self) -> None:
        """Test sync bulkhead with max_wait > 0."""
        bulkhead = Bulkhead(BulkheadConfig(max_concurrent=1, max_wait=0.5))
        assert bulkhead.acquire()
        bulkhead.release()

    def test_sync_bulkhead_wait_timeout(self) -> None:
        """Test sync bulkhead times out waiting for slot."""
        bulkhead = Bulkhead(BulkheadConfig(max_concurrent=1, max_wait=0.1))
        assert bulkhead.acquire()
        # Second acquire should timeout
        assert not bulkhead.acquire()
        bulkhead.release()

    @pytest.mark.asyncio
    async def test_async_bulkhead_with_wait(self) -> None:
        """Test async bulkhead with max_wait > 0."""
        config = BulkheadConfig(max_concurrent=1, max_wait=0.5)
        bulkhead = AsyncBulkhead(config)
        assert await bulkhead.acquire()
        bulkhead.release()

    @pytest.mark.asyncio
    async def test_async_bulkhead_wait_timeout(self) -> None:
        """Test async bulkhead times out waiting for slot."""
        config = BulkheadConfig(max_concurrent=1, max_wait=0.1)
        bulkhead = AsyncBulkhead(config)
        assert await bulkhead.acquire()
        # Second acquire should timeout
        assert not await bulkhead.acquire()
        bulkhead.release()

    @pytest.mark.asyncio
    async def test_async_bulkhead_release_without_acquire(self) -> None:
        """Test releasing async bulkhead when semaphore is None."""
        config = BulkheadConfig(max_concurrent=1)
        bulkhead = AsyncBulkhead(config)
        # Release without acquiring — semaphore is None, should not crash
        bulkhead.release()


class TestAsyncExecutorEdgeCases:
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

        with pytest.raises(RuntimeError, match="Circuit breaker is open"):
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
    async def test_async_bulkhead_rejects_with_fallback(self) -> None:
        """Test async bulkhead rejection with fallback."""

        @resilient(
            bulkhead=BulkheadConfig(max_concurrent=1, max_wait=0),
            fallback=FallbackConfig(handler="busy"),
        )
        async def slow() -> str:
            await asyncio.sleep(0.3)
            return "done"

        async def run_both() -> tuple[str, str]:
            t1 = asyncio.create_task(slow())
            await asyncio.sleep(0.05)
            t2 = asyncio.create_task(slow())
            r1 = await t1
            r2 = await t2
            return r1, r2

        r1, r2 = await run_both()
        assert r1 == "done"
        assert r2 == "busy"

    @pytest.mark.asyncio
    async def test_async_bulkhead_rejects_without_fallback(self) -> None:
        """Test async bulkhead rejection raises error."""

        @resilient(bulkhead=BulkheadConfig(max_concurrent=1, max_wait=0))
        async def slow() -> str:
            await asyncio.sleep(0.3)
            return "done"

        async def run_both() -> tuple[str, str]:
            t1 = asyncio.create_task(slow())
            await asyncio.sleep(0.05)
            t2 = asyncio.create_task(slow())
            r1 = await t1
            try:
                r2 = await t2
            except BulkheadFullError:
                r2 = "rejected"
            return r1, r2

        r1, r2 = await run_both()
        assert r1 == "done"
        assert r2 == "rejected"

    @pytest.mark.asyncio
    async def test_async_retry_exhausted_event(self) -> None:
        """Test async retry exhausted event is emitted."""
        events: list[ResilienceEvent] = []

        @resilient(
            retry=RetryConfig(max_attempts=2, delay=0.01),
            listeners=[events.append],
        )
        async def always_fails() -> str:
            raise ValueError("fail")

        with pytest.raises(ValueError):
            await always_fails()

        event_types = [e.event_type for e in events]
        assert EventType.RETRY_EXHAUSTED in event_types
        assert EventType.FAILURE in event_types

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

        # First call fails, opens circuit
        with pytest.raises(ValueError):
            await sometimes_fails()

        # Wait for recovery
        await asyncio.sleep(0.15)

        # Next call succeeds, closes circuit
        result = await sometimes_fails()
        assert result == "ok"
        event_types = [e.event_type for e in events]
        assert EventType.CIRCUIT_CLOSED in event_types


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
