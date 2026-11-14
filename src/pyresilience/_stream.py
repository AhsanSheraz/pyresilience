"""Idle-timeout wrappers for streamed results (iterators and async iterators)."""

from __future__ import annotations

import asyncio
import contextvars
import queue
import threading
from typing import Any, Optional

from pyresilience._events import _emit
from pyresilience._exceptions import ResilienceTimeoutError
from pyresilience._types import EventType, ResilienceListener

_DONE: Any = object()
_STOP: Any = object()


def _wrap_stream(
    result: Any,
    idle: float,
    func_name: str,
    listeners: list[ResilienceListener],
) -> Any:
    """Wrap an iterator or async iterator so that each item must arrive within *idle*.

    Any other result is returned unchanged.
    """
    if hasattr(result, "__anext__"):
        return _IdleTimeoutAsyncIterator(result, idle, func_name, listeners)
    if hasattr(result, "__next__"):
        return _IdleTimeoutIterator(result, idle, func_name, listeners)
    return result


def _idle_error(func_name: str, idle: float, listeners: list[ResilienceListener]) -> Exception:
    if listeners:
        _emit(listeners, EventType.TIMEOUT, func_name, detail=f"stream idle for more than {idle}s")
    return ResilienceTimeoutError(f"{func_name} stream was idle for more than {idle}s")


class _IdleTimeoutIterator:
    """Iterator that raises ResilienceTimeoutError when the next item is too slow.

    The wrapped iterator is read by one dedicated daemon thread, started with the
    first ``next()``. The caller hands it a request and waits at most *idle*
    seconds for the answer, so streams never queue behind each other and the
    shared timeout pool is not involved. A read that is abandoned keeps that one
    thread busy until the underlying iterator returns; the caller is released
    immediately.
    """

    __slots__ = (
        "_done",
        "_func_name",
        "_idle",
        "_it",
        "_listeners",
        "_requests",
        "_results",
        "_thread",
    )

    def __init__(
        self,
        it: Any,
        idle: float,
        func_name: str,
        listeners: list[ResilienceListener],
    ) -> None:
        self._it = it
        self._idle = idle
        self._func_name = func_name
        self._listeners = listeners
        self._done = False
        self._requests: queue.Queue[Any] = queue.Queue()
        self._results: queue.Queue[tuple[bool, Any]] = queue.Queue()
        self._thread: Optional[threading.Thread] = None

    @staticmethod
    def _read(it: Any, requests: queue.Queue[Any], results: queue.Queue[tuple[bool, Any]]) -> None:
        """Reader thread: answer each request with ``(ok, item_or_exception)``."""
        while requests.get() is not _STOP:
            try:
                results.put((True, next(it, _DONE)))
            except BaseException as exc:
                results.put((False, exc))
                return

    def _finish(self) -> None:
        """Mark the stream finished and let the reader thread exit."""
        if not self._done:
            self._done = True
            self._requests.put(_STOP)

    def __iter__(self) -> _IdleTimeoutIterator:
        return self

    def __next__(self) -> Any:
        if self._done:
            raise StopIteration
        if self._thread is None:
            # The thread holds the queues and the wrapped iterator, not this
            # wrapper, so an abandoned wrapper can still be collected
            # The stream body runs in a copy of the caller's context, so
            # context variables set by the caller are visible to it
            self._thread = threading.Thread(
                target=contextvars.copy_context().run,
                args=(self._read, self._it, self._requests, self._results),
                name="pyresilience-stream",
                daemon=True,
            )
            self._thread.start()
        self._requests.put(None)
        try:
            ok, value = self._results.get(timeout=self._idle)
        except queue.Empty:
            self._finish()
            raise _idle_error(self._func_name, self._idle, self._listeners) from None
        if not ok:
            self._done = True
            raise value
        if value is _DONE:
            self._finish()
            raise StopIteration
        return value

    def close(self) -> None:
        """Stop reading and close the wrapped stream when it can be closed."""
        self._finish()
        close = getattr(self._it, "close", None)
        if close is not None:
            close()

    def __enter__(self) -> Any:
        enter = getattr(self._it, "__enter__", None)
        if enter is None:
            raise TypeError(
                f"{type(self._it).__name__!r} object does not support the context manager protocol"
            )
        inner = enter()
        if inner is self._it:
            return self
        return _wrap_stream(inner, self._idle, self._func_name, self._listeners)

    def __exit__(self, *exc_info: Any) -> Any:
        self._finish()
        return self._it.__exit__(*exc_info)

    def __del__(self) -> None:
        self._finish()

    def __getattr__(self, name: str) -> Any:
        # Delegate send() and client-specific attributes to the wrapped stream
        return getattr(self._it, name)


class _IdleTimeoutAsyncIterator:
    """Async iterator that raises ResilienceTimeoutError when the next item is too slow."""

    __slots__ = ("_done", "_func_name", "_idle", "_it", "_listeners")

    def __init__(
        self,
        it: Any,
        idle: float,
        func_name: str,
        listeners: list[ResilienceListener],
    ) -> None:
        self._it = it
        self._idle = idle
        self._func_name = func_name
        self._listeners = listeners
        self._done = False

    def __aiter__(self) -> _IdleTimeoutAsyncIterator:
        return self

    async def __anext__(self) -> Any:
        if self._done:
            raise StopAsyncIteration
        try:
            return await asyncio.wait_for(self._it.__anext__(), timeout=self._idle)
        except asyncio.TimeoutError as exc:
            self._done = True
            raise _idle_error(self._func_name, self._idle, self._listeners) from exc
        except BaseException:
            self._done = True
            raise

    async def __aenter__(self) -> Any:
        enter = getattr(self._it, "__aenter__", None)
        if enter is None:
            raise TypeError(
                f"{type(self._it).__name__!r} object does not support the "
                "asynchronous context manager protocol"
            )
        inner = await enter()
        if inner is self._it:
            return self
        return _wrap_stream(inner, self._idle, self._func_name, self._listeners)

    async def __aexit__(self, *exc_info: Any) -> Any:
        return await self._it.__aexit__(*exc_info)

    def __getattr__(self, name: str) -> Any:
        # Delegate aclose(), asend() and client-specific attributes to the wrapped stream
        return getattr(self._it, name)
