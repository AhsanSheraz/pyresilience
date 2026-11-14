"""Tests for the stream idle timeout (stream_idle_seconds)."""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator, Iterator

import pytest

from pyresilience import (
    EventType,
    ResilienceEvent,
    ResilienceTimeoutError,
    TimeoutConfig,
    resilient,
)


class TestStreamIdleTimeoutSync:
    def test_fast_stream_passes_through(self) -> None:
        @resilient(timeout=TimeoutConfig(seconds=1.0, stream_idle_seconds=5.0))
        def stream() -> Iterator[int]:
            return iter([1, 2, 3])

        assert list(stream()) == [1, 2, 3]

    def test_gap_between_items_times_out(self) -> None:
        events: list[ResilienceEvent] = []

        def chunks() -> Iterator[int]:
            yield 1
            time.sleep(3.0)
            yield 2

        @resilient(
            timeout=TimeoutConfig(seconds=1.0, stream_idle_seconds=0.5),
            listeners=[events.append],
        )
        def stream() -> Iterator[int]:
            return chunks()

        it = stream()
        assert next(it) == 1
        with pytest.raises(ResilienceTimeoutError, match=r"idle for more than 0\.5s"):
            next(it)
        # A stream that timed out is finished
        with pytest.raises(StopIteration):
            next(it)
        idle = [e for e in events if e.event_type == EventType.TIMEOUT]
        assert len(idle) == 1
        assert "stream idle" in idle[0].detail

    def test_slow_first_item_times_out(self) -> None:
        def chunks() -> Iterator[int]:
            time.sleep(3.0)
            yield 1

        @resilient(timeout=TimeoutConfig(seconds=1.0, stream_idle_seconds=0.5))
        def stream() -> Iterator[int]:
            return chunks()

        with pytest.raises(ResilienceTimeoutError):
            next(stream())

    def test_non_stream_result_is_returned_unchanged(self) -> None:
        @resilient(timeout=TimeoutConfig(seconds=1.0, stream_idle_seconds=0.5))
        def not_a_stream() -> list[int]:
            return [1, 2, 3]

        result = not_a_stream()
        assert result == [1, 2, 3]
        assert isinstance(result, list)

    def test_stream_errors_propagate(self) -> None:
        def chunks() -> Iterator[int]:
            yield 1
            raise ValueError("stream broke")

        @resilient(timeout=TimeoutConfig(seconds=1.0, stream_idle_seconds=5.0))
        def stream() -> Iterator[int]:
            return chunks()

        it = stream()
        assert next(it) == 1
        with pytest.raises(ValueError, match="stream broke"):
            next(it)
        with pytest.raises(StopIteration):
            next(it)

    def test_timeout_error_raised_by_the_stream_is_not_relabelled(self) -> None:
        def chunks() -> Iterator[int]:
            yield 1
            raise TimeoutError("socket timed out")

        @resilient(timeout=TimeoutConfig(seconds=1.0, stream_idle_seconds=5.0))
        def stream() -> Iterator[int]:
            return chunks()

        it = stream()
        assert next(it) == 1
        with pytest.raises(TimeoutError, match="socket timed out") as info:
            next(it)
        assert not isinstance(info.value, ResilienceTimeoutError)

    def test_attributes_delegate_to_the_wrapped_stream(self) -> None:
        closed = False

        def chunks() -> Iterator[int]:
            nonlocal closed
            try:
                yield 1
                yield 2
            finally:
                closed = True

        @resilient(timeout=TimeoutConfig(seconds=1.0, stream_idle_seconds=5.0))
        def stream() -> Iterator[int]:
            return chunks()

        it = stream()
        assert iter(it) is it
        assert next(it) == 1
        it.close()  # type: ignore[attr-defined]
        assert closed

    async def test_sync_function_returning_async_iterator_is_wrapped(self) -> None:
        @resilient(timeout=TimeoutConfig(seconds=1.0, stream_idle_seconds=0.5))
        async def stream() -> AsyncIterator[int]:
            yield 1
            await asyncio.sleep(3.0)
            yield 2

        # An async generator function is not a coroutine function: it runs on the sync path
        it = stream()
        assert await it.__anext__() == 1
        with pytest.raises(ResilienceTimeoutError):
            await it.__anext__()


class TestStreamIdleTimeoutAsync:
    async def test_fast_stream_passes_through(self) -> None:
        async def chunks() -> AsyncIterator[int]:
            for i in (1, 2, 3):
                yield i

        @resilient(timeout=TimeoutConfig(seconds=1.0, stream_idle_seconds=5.0))
        async def stream() -> AsyncIterator[int]:
            return chunks()

        assert [item async for item in await stream()] == [1, 2, 3]

    async def test_gap_between_items_times_out(self) -> None:
        events: list[ResilienceEvent] = []

        async def chunks() -> AsyncIterator[int]:
            yield 1
            await asyncio.sleep(3.0)
            yield 2

        @resilient(
            timeout=TimeoutConfig(seconds=1.0, stream_idle_seconds=0.5),
            listeners=[events.append],
        )
        async def stream() -> AsyncIterator[int]:
            return chunks()

        it = await stream()
        assert await it.__anext__() == 1
        with pytest.raises(ResilienceTimeoutError, match=r"idle for more than 0\.5s"):
            await it.__anext__()
        with pytest.raises(StopAsyncIteration):
            await it.__anext__()
        idle = [e for e in events if e.event_type == EventType.TIMEOUT]
        assert len(idle) == 1

    async def test_slow_first_item_times_out(self) -> None:
        async def chunks() -> AsyncIterator[int]:
            await asyncio.sleep(3.0)
            yield 1

        @resilient(timeout=TimeoutConfig(seconds=1.0, stream_idle_seconds=0.5))
        async def stream() -> AsyncIterator[int]:
            return chunks()

        it = await stream()
        with pytest.raises(ResilienceTimeoutError):
            await it.__anext__()

    async def test_non_stream_result_is_returned_unchanged(self) -> None:
        @resilient(timeout=TimeoutConfig(seconds=1.0, stream_idle_seconds=0.5))
        async def not_a_stream() -> dict[str, int]:
            return {"a": 1}

        assert await not_a_stream() == {"a": 1}

    async def test_stream_errors_propagate(self) -> None:
        async def chunks() -> AsyncIterator[int]:
            yield 1
            raise ValueError("stream broke")

        @resilient(timeout=TimeoutConfig(seconds=1.0, stream_idle_seconds=5.0))
        async def stream() -> AsyncIterator[int]:
            return chunks()

        it = await stream()
        assert it.__aiter__() is it
        assert await it.__anext__() == 1
        with pytest.raises(ValueError, match="stream broke"):
            await it.__anext__()
        with pytest.raises(StopAsyncIteration):
            await it.__anext__()

    async def test_attributes_delegate_to_the_wrapped_stream(self) -> None:
        closed = False

        async def chunks() -> AsyncIterator[int]:
            nonlocal closed
            try:
                yield 1
                yield 2
            finally:
                closed = True

        @resilient(timeout=TimeoutConfig(seconds=1.0, stream_idle_seconds=5.0))
        async def stream() -> AsyncIterator[int]:
            return chunks()

        it = await stream()
        assert await it.__anext__() == 1
        await it.aclose()
        assert closed

    async def test_async_function_returning_sync_iterator_is_wrapped(self) -> None:
        def chunks() -> Iterator[int]:
            yield 1
            time.sleep(3.0)
            yield 2

        @resilient(timeout=TimeoutConfig(seconds=1.0, stream_idle_seconds=0.5))
        async def stream() -> Any:
            return chunks()

        it = await stream()
        assert next(it) == 1
        with pytest.raises(ResilienceTimeoutError):
            next(it)
