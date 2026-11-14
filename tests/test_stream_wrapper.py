"""Tests for the stream wrapper: concurrency, context managers and reader threads."""

from __future__ import annotations

import contextvars
import gc
import threading
import time
from typing import Any, AsyncIterator, Iterator

import pytest

from pyresilience import ResilienceTimeoutError, TimeoutConfig, resilient

STREAM = TimeoutConfig(seconds=5.0, stream_idle_seconds=5.0)
REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="unset")


class ManagedStream:
    """An iterator that is also a context manager, like SDK stream objects."""

    def __init__(self) -> None:
        self.items = iter([1, 2, 3])
        self.entered = False
        self.exited = False
        self.closed = False

    def __iter__(self) -> ManagedStream:
        return self

    def __next__(self) -> int:
        return next(self.items)

    def __enter__(self) -> ManagedStream:
        self.entered = True
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.exited = True

    def close(self) -> None:
        self.closed = True


class AsyncManagedStream:
    def __init__(self) -> None:
        self.items = [1, 2, 3]
        self.entered = False
        self.exited = False

    def __aiter__(self) -> AsyncManagedStream:
        return self

    async def __anext__(self) -> int:
        if not self.items:
            raise StopAsyncIteration
        return self.items.pop(0)

    async def __aenter__(self) -> AsyncManagedStream:
        self.entered = True
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        self.exited = True


def _wait_until(condition: Any, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


class TestSyncStreamConcurrency:
    def test_many_concurrent_streams_all_finish(self) -> None:
        @resilient(timeout=TimeoutConfig(seconds=5.0, pool_size=2, stream_idle_seconds=5.0))
        def stream() -> Iterator[int]:
            def chunks() -> Iterator[int]:
                for index in range(3):
                    time.sleep(0.1)
                    yield index

            return chunks()

        results: list[Any] = []
        lock = threading.Lock()

        def consume() -> None:
            try:
                value: Any = list(stream())
            except Exception as exc:
                value = exc
            with lock:
                results.append(value)

        # More streams than timeout-pool workers: each has its own reader thread
        threads = [threading.Thread(target=consume) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert results == [[0, 1, 2]] * 12

    def test_reader_thread_ends_with_the_stream(self) -> None:
        @resilient(timeout=STREAM)
        def stream() -> Iterator[int]:
            return iter([1, 2])

        wrapped = stream()
        assert list(wrapped) == [1, 2]
        reader = wrapped._thread
        assert reader is not None
        assert reader.daemon is True
        assert _wait_until(lambda: not reader.is_alive())

    def test_reader_thread_ends_when_the_wrapper_is_dropped(self) -> None:
        @resilient(timeout=STREAM)
        def stream() -> Iterator[int]:
            return iter(range(100))

        wrapped = stream()
        assert next(wrapped) == 0
        reader = wrapped._thread
        del wrapped
        gc.collect()
        assert _wait_until(lambda: not reader.is_alive())

    def test_stream_body_sees_the_callers_context_variables(self) -> None:
        @resilient(timeout=STREAM)
        def stream() -> Iterator[str]:
            def items() -> Iterator[str]:
                yield REQUEST_ID.get()
                yield REQUEST_ID.get()

            return items()

        token = REQUEST_ID.set("req-123")
        try:
            assert list(stream()) == ["req-123", "req-123"]
        finally:
            REQUEST_ID.reset(token)

    def test_no_thread_before_the_first_item_is_requested(self) -> None:
        @resilient(timeout=STREAM)
        def stream() -> Iterator[int]:
            return iter([1])

        assert stream()._thread is None

    def test_close_stops_reading_and_closes_the_stream(self) -> None:
        inner = ManagedStream()

        @resilient(timeout=STREAM)
        def stream() -> ManagedStream:
            return inner

        wrapped = stream()
        assert next(wrapped) == 1
        wrapped.close()
        assert inner.closed is True
        with pytest.raises(StopIteration):
            next(wrapped)

    def test_close_on_a_stream_without_close(self) -> None:
        @resilient(timeout=STREAM)
        def stream() -> Iterator[int]:
            return iter([1, 2])

        wrapped = stream()
        wrapped.close()
        with pytest.raises(StopIteration):
            next(wrapped)


class TestSyncStreamContextManager:
    def test_with_statement_is_forwarded(self) -> None:
        inner = ManagedStream()

        @resilient(timeout=STREAM)
        def stream() -> ManagedStream:
            return inner

        with stream() as managed:
            assert inner.entered is True
            assert list(managed) == [1, 2, 3]
        assert inner.exited is True

    def test_stream_without_context_manager_support(self) -> None:
        @resilient(timeout=STREAM)
        def stream() -> Iterator[int]:
            return iter([1])

        wrapped = stream()
        with pytest.raises(TypeError, match="does not support the context manager protocol"):
            wrapped.__enter__()

    def test_inner_stream_returned_by_enter_is_guarded_too(self) -> None:
        class Opener:
            """Iterator whose __enter__ hands out a different, slow iterator."""

            def __iter__(self) -> Opener:
                return self

            def __next__(self) -> int:
                raise StopIteration

            def __enter__(self) -> Iterator[int]:
                def chunks() -> Iterator[int]:
                    yield 1
                    time.sleep(3.0)
                    yield 2

                return chunks()

            def __exit__(self, *exc_info: Any) -> None:
                return None

        @resilient(timeout=TimeoutConfig(seconds=5.0, stream_idle_seconds=0.5))
        def stream() -> Opener:
            return Opener()

        with stream() as chunks:
            assert next(chunks) == 1
            with pytest.raises(ResilienceTimeoutError):
                next(chunks)


class TestAsyncStreamContextManager:
    async def test_async_with_statement_is_forwarded(self) -> None:
        inner = AsyncManagedStream()

        @resilient(timeout=STREAM)
        async def stream() -> AsyncManagedStream:
            return inner

        async with await stream() as managed:
            assert inner.entered is True
            assert [item async for item in managed] == [1, 2, 3]
        assert inner.exited is True

    async def test_stream_without_async_context_manager_support(self) -> None:
        async def chunks() -> AsyncIterator[int]:
            yield 1

        @resilient(timeout=STREAM)
        async def stream() -> AsyncIterator[int]:
            return chunks()

        wrapped = await stream()
        with pytest.raises(TypeError, match="asynchronous context manager protocol"):
            async with wrapped:
                pass

    async def test_inner_stream_returned_by_aenter_is_guarded_too(self) -> None:
        async def chunks() -> AsyncIterator[int]:
            yield 1
            yield 2

        class Opener:
            def __aiter__(self) -> Opener:
                return self

            async def __anext__(self) -> int:
                raise StopAsyncIteration

            async def __aenter__(self) -> AsyncIterator[int]:
                return chunks()

            async def __aexit__(self, *exc_info: Any) -> None:
                return None

        @resilient(timeout=STREAM)
        async def stream() -> Opener:
            return Opener()

        async with await stream() as inner:
            assert [item async for item in inner] == [1, 2]
