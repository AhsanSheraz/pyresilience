"""Tests for bulkhead functionality."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from pyresilience import (
    BulkheadConfig,
    FallbackConfig,
    resilient,
)
from pyresilience._bulkhead import AsyncBulkhead, Bulkhead
from pyresilience._exceptions import BulkheadFullError


class TestBulkheadSync:
    def test_allows_within_limit(self) -> None:
        @resilient(bulkhead=BulkheadConfig(max_concurrent=2))
        def fast() -> str:
            return "ok"

        assert fast() == "ok"

    def test_rejects_over_limit(self) -> None:
        results: list[str] = []
        errors: list[Exception] = []

        @resilient(bulkhead=BulkheadConfig(max_concurrent=1, max_wait=0))
        def slow() -> str:
            time.sleep(0.3)
            return "done"

        def run() -> None:
            try:
                results.append(slow())
            except BulkheadFullError as e:
                errors.append(e)

        t1 = threading.Thread(target=run)
        t2 = threading.Thread(target=run)
        t1.start()
        time.sleep(0.05)  # Ensure t1 starts first
        t2.start()
        t1.join()
        t2.join()

        assert len(results) == 1
        assert len(errors) == 1

    def test_bulkhead_with_fallback(self) -> None:
        @resilient(
            bulkhead=BulkheadConfig(max_concurrent=1, max_wait=0),
            fallback=FallbackConfig(handler="busy"),
        )
        def slow() -> str:
            time.sleep(0.3)
            return "done"

        results: list[str] = []

        def run() -> None:
            results.append(slow())

        t1 = threading.Thread(target=run)
        t2 = threading.Thread(target=run)
        t1.start()
        time.sleep(0.05)
        t2.start()
        t1.join()
        t2.join()

        assert "done" in results
        assert "busy" in results


class TestBulkheadAsync:
    @pytest.mark.asyncio
    async def test_async_allows_within_limit(self) -> None:
        @resilient(bulkhead=BulkheadConfig(max_concurrent=2))
        async def fast() -> str:
            return "ok"

        assert await fast() == "ok"

    @pytest.mark.asyncio
    async def test_async_rejects_over_limit(self) -> None:
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


class TestSyncBulkheadWithListenersAndFallback:
    def test_bulkhead_rejected_with_listeners_and_fallback(self) -> None:
        """Bulkhead rejection with listeners and fallback."""
        from pyresilience import EventType, ResilienceEvent

        events: list[ResilienceEvent] = []

        @resilient(
            bulkhead=BulkheadConfig(max_concurrent=1, max_wait=0),
            fallback=FallbackConfig(handler="busy_val"),
            listeners=[events.append],
        )
        def slow() -> str:
            time.sleep(0.3)
            return "done"

        results: list[str] = [None, None]  # type: ignore[list-item]

        def run(idx: int) -> None:
            results[idx] = slow()

        t1 = threading.Thread(target=run, args=(0,))
        t2 = threading.Thread(target=run, args=(1,))
        t1.start()
        time.sleep(0.05)
        t2.start()
        t1.join()
        t2.join()

        assert "done" in results
        assert "busy_val" in results
        event_types = [e.event_type for e in events]
        assert EventType.BULKHEAD_REJECTED in event_types
        assert EventType.FALLBACK_USED in event_types


class TestBulkheadConfigValidation:
    def test_max_concurrent_must_be_positive(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="max_concurrent must be >= 1"):
            BulkheadConfig(max_concurrent=0)
