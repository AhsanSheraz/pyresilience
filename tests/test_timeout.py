"""Tests for timeout functionality."""

from __future__ import annotations

import asyncio
import time

import pytest

from pyresilience import EventType, ResilienceEvent, TimeoutConfig, resilient


class TestTimeoutSync:
    def test_completes_within_timeout(self) -> None:
        @resilient(timeout=TimeoutConfig(seconds=1.0))
        def fast_func() -> str:
            return "fast"

        assert fast_func() == "fast"

    def test_exceeds_timeout(self) -> None:
        @resilient(timeout=TimeoutConfig(seconds=0.1))
        def slow_func() -> str:
            time.sleep(2)
            return "slow"

        with pytest.raises(TimeoutError):
            slow_func()

    def test_timeout_event_emitted(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            timeout=TimeoutConfig(seconds=0.1),
            listeners=[events.append],
        )
        def slow_func() -> str:
            time.sleep(2)
            return "slow"

        with pytest.raises(TimeoutError):
            slow_func()

        event_types = [e.event_type for e in events]
        assert EventType.TIMEOUT in event_types


class TestTimeoutAsync:
    @pytest.mark.asyncio
    async def test_async_completes_within_timeout(self) -> None:
        @resilient(timeout=TimeoutConfig(seconds=1.0))
        async def fast_func() -> str:
            return "fast"

        assert await fast_func() == "fast"

    @pytest.mark.asyncio
    async def test_async_exceeds_timeout(self) -> None:
        @resilient(timeout=TimeoutConfig(seconds=0.1))
        async def slow_func() -> str:
            await asyncio.sleep(2)
            return "slow"

        with pytest.raises(TimeoutError):
            await slow_func()
