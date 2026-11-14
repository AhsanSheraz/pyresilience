"""Tests for shared rate limits while the state backend is unreachable."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Optional

import pytest

from pyresilience import (
    InMemoryBackend,
    RateLimiterConfig,
    RateLimitExceededError,
    SharedStateConfig,
    resilient,
)
from pyresilience._shared import _SharedWindows

LONG = 3600.0


class DownBackend(InMemoryBackend):
    """Counts the increments it is asked for and fails them while ``down`` is True.

    With a ``gate``, the next increment answers only when the test opens the gate,
    like a client that takes long to give up.
    """

    def __init__(self) -> None:
        super().__init__()
        self.down = True
        self.attempts = 0
        self.gate: Optional[threading.Event] = None
        self.waiting = threading.Event()

    def incr(self, key: str, amount: float, ttl: Optional[float] = None) -> float:
        self.attempts += 1
        gate, self.gate = self.gate, None
        if gate is not None:
            self.waiting.set()
            gate.wait(10.0)
        if self.down:
            raise ConnectionError("backend down")
        return super().incr(key, amount, ttl)


def _shared(backend: Any, **kwargs: Any) -> SharedStateConfig:
    kwargs.setdefault("sync_interval", 0)
    return SharedStateConfig(backend=backend, key="svc", **kwargs)


def _windows(call: Any) -> _SharedWindows:
    windows = call._executor._weighted_limiter._core.shared
    assert isinstance(windows, _SharedWindows)
    return windows


def _end_pause(windows: _SharedWindows) -> None:
    """Let the next call try the backend again without waiting for the pause."""
    windows._down_until = time.monotonic() - 0.001


def _age(windows: _SharedWindows, seconds: float) -> None:
    """Pretend that *seconds* have passed since the pause or the retry began."""
    windows._down_until -= seconds


def _unit_windows(backend: Any, **kwargs: Any) -> _SharedWindows:
    return _SharedWindows(backend, "svc", ["calls"], [10.0], [LONG], True, **kwargs)


class TestBackendOutageSync:
    def test_backend_is_left_alone_after_a_failure(self) -> None:
        backend = DownBackend()

        @resilient(
            rate_limiter=RateLimiterConfig(max_calls=10, period=LONG),
            shared_state=_shared(backend),
        )
        def call() -> str:
            return "ok"

        for _ in range(5):
            assert call() == "ok"
        # Only the first call paid for the unreachable backend
        assert backend.attempts == 1

    def test_fail_closed_rejects_at_once_during_the_pause(self) -> None:
        backend = DownBackend()

        @resilient(
            rate_limiter=RateLimiterConfig(max_calls=10, period=LONG, max_wait=5.0),
            shared_state=_shared(backend, fail_open=False),
        )
        def call() -> str:
            return "ok"

        start = time.monotonic()
        for _ in range(3):
            with pytest.raises(RateLimitExceededError, match="state backend unavailable"):
                call()
        assert backend.attempts == 1
        # Generous bound for slow CI: no call waits for max_wait
        assert time.monotonic() - start < 3.0

    def test_one_call_tries_again_when_the_pause_is_over(self) -> None:
        backend = DownBackend()

        @resilient(
            rate_limiter=RateLimiterConfig(max_calls=10, period=LONG),
            shared_state=_shared(backend),
        )
        def call() -> str:
            return "ok"

        call()
        _end_pause(_windows(call))
        call()
        assert backend.attempts == 2
        # Still down: the pause starts again
        call()
        assert backend.attempts == 2

    def test_counting_resumes_when_the_backend_is_back(self) -> None:
        backend = DownBackend()

        @resilient(
            rate_limiter=RateLimiterConfig(max_calls=10, period=LONG),
            shared_state=_shared(backend),
        )
        def call() -> str:
            return "ok"

        call()
        backend.down = False
        # Within the pause the recovery is not noticed yet
        call()
        assert backend.attempts == 1

        windows = _windows(call)
        _end_pause(windows)
        call()
        call()
        assert backend.attempts == 3
        assert windows._down_until == 0.0

    def test_pause_follows_the_sync_interval(self) -> None:
        @resilient(
            rate_limiter=RateLimiterConfig(max_calls=10, period=LONG),
            shared_state=_shared(InMemoryBackend(), sync_interval=3.0),
        )
        def call() -> str:
            return "ok"

        assert _windows(call)._pause == 3.0

    def test_pause_is_at_least_one_second(self) -> None:
        assert _unit_windows(InMemoryBackend())._pause == 1.0
        assert _unit_windows(InMemoryBackend(), pause=0.0)._pause == 1.0
        assert _unit_windows(InMemoryBackend(), pause=7.5)._pause == 7.5

    def test_retry_charges_and_corrections_skip_a_paused_backend(self) -> None:
        backend = DownBackend()
        windows = _unit_windows(backend)

        ok, _, _, counted = windows.acquire([1.0])
        assert ok
        assert counted == [None]
        assert backend.attempts == 1

        assert windows.charge([1.0]) is None
        windows.adjust([-2.0], None)
        assert backend.attempts == 1

    def test_a_retry_charge_that_works_ends_the_outage(self) -> None:
        backend = DownBackend()
        windows = _unit_windows(backend)
        windows.acquire([1.0])

        backend.down = False
        _end_pause(windows)
        assert windows.charge([1.0]) is not None
        assert windows._down_until == 0.0

    def test_a_correction_that_works_ends_the_outage(self) -> None:
        backend = DownBackend()
        windows = _unit_windows(backend)
        windows.acquire([1.0])

        backend.down = False
        _end_pause(windows)
        windows.adjust([-2.0], None)
        assert windows._down_until == 0.0
        assert backend.attempts == 2

    def test_only_one_call_waits_while_the_backend_is_tried_again(self) -> None:
        backend = DownBackend()
        windows = _unit_windows(backend)
        windows.acquire([1.0])
        _end_pause(windows)

        # The call that tries again hangs in the client for longer than a pause lasts
        gate = threading.Event()
        backend.gate = gate
        retrying = threading.Thread(target=windows.acquire, args=([1.0],))
        retrying.start()
        try:
            assert backend.waiting.wait(10.0)
            _age(windows, windows._pause + 0.5)

            for _ in range(3):
                ok, _, _, counted = windows.acquire([1.0])
                assert ok
                assert counted == [None]
            # Nobody else went to the backend while the first call was still waiting
            assert backend.attempts == 2
        finally:
            gate.set()
            retrying.join(10.0)
        assert not retrying.is_alive()
        # It failed, so the pause starts again
        assert windows._down_until > time.monotonic()

    def test_another_call_tries_when_a_retry_does_not_come_back(self) -> None:
        backend = DownBackend()
        windows = _unit_windows(backend)
        windows.acquire([1.0])
        _end_pause(windows)

        gate = threading.Event()
        backend.gate = gate
        lost = threading.Thread(target=windows.acquire, args=([1.0],))
        lost.start()
        try:
            assert backend.waiting.wait(10.0)
            # A minute later the first call has still not reported back
            _age(windows, 60.0)
            windows.acquire([1.0])
            assert backend.attempts == 3
        finally:
            gate.set()
            lost.join(10.0)
        assert not lost.is_alive()

    def test_a_rejected_retry_ends_the_outage(self) -> None:
        backend = DownBackend()
        backend.down = False
        windows = _unit_windows(backend)
        ok, _, _, counted = windows.acquire([1.0])
        assert ok
        key = counted[0]
        assert key is not None
        # Another process uses up the rest of the window
        InMemoryBackend.incr(backend, key, 9.0)

        backend.down = True
        windows.acquire([1.0])
        backend.down = False
        _end_pause(windows)

        ok, _, blocker, _ = windows.acquire([1.0])
        assert not ok
        assert blocker == "calls"
        # The backend answered, so the outage is over and the next call is counted again
        assert windows._down_until == 0.0
        ok, _, _, _ = windows.acquire([1.0])
        assert not ok

    def test_a_call_with_nothing_to_count_does_not_end_the_outage(self) -> None:
        backend = DownBackend()
        windows = _unit_windows(backend)
        windows.acquire([1.0])
        _end_pause(windows)

        ok, _, _, _ = windows.acquire([0.0])
        assert ok
        assert backend.attempts == 1
        # Nothing was learned about the backend: the next call still has to try it
        assert windows._down_until != 0.0
        windows.acquire([1.0])
        assert backend.attempts == 2

    def test_a_retry_charge_with_nothing_to_count_does_not_end_the_outage(self) -> None:
        backend = DownBackend()
        windows = _unit_windows(backend)
        windows.acquire([1.0])
        _end_pause(windows)

        windows.charge([0.0])
        assert backend.attempts == 1
        assert windows._down_until != 0.0
        windows.acquire([1.0])
        assert backend.attempts == 2

    def test_a_correction_with_nothing_to_send_does_not_end_the_outage(self) -> None:
        backend = DownBackend()
        windows = _unit_windows(backend)
        windows.acquire([1.0])
        _end_pause(windows)

        # Units to give back, but no window to give them back to
        windows.adjust([2.0], None)
        assert backend.attempts == 1
        assert windows._down_until != 0.0
        windows.acquire([1.0])
        assert backend.attempts == 2


class TestBackendOutageAsync:
    async def test_backend_is_left_alone_after_a_failure(self) -> None:
        backend = DownBackend()

        @resilient(
            rate_limiter=RateLimiterConfig(max_calls=10, period=LONG),
            shared_state=_shared(backend),
        )
        async def call() -> str:
            return "ok"

        for _ in range(5):
            assert await call() == "ok"
        assert backend.attempts == 1

    async def test_fail_closed_rejects_at_once_during_the_pause(self) -> None:
        backend = DownBackend()

        @resilient(
            rate_limiter=RateLimiterConfig(max_calls=10, period=LONG, max_wait=5.0),
            shared_state=_shared(backend, fail_open=False),
        )
        async def call() -> str:
            return "ok"

        start = time.monotonic()
        for _ in range(3):
            with pytest.raises(RateLimitExceededError, match="state backend unavailable"):
                await call()
        assert backend.attempts == 1
        assert time.monotonic() - start < 3.0

    async def test_counting_resumes_when_the_backend_is_back(self) -> None:
        backend = DownBackend()

        @resilient(
            rate_limiter=RateLimiterConfig(max_calls=10, period=LONG),
            shared_state=_shared(backend),
        )
        async def call() -> str:
            return "ok"

        await call()
        backend.down = False
        windows = _windows(call)
        _end_pause(windows)
        await call()
        await call()
        assert backend.attempts == 3
        assert windows._down_until == 0.0

    async def test_only_one_call_waits_while_the_backend_is_tried_again(self) -> None:
        backend = DownBackend()

        @resilient(
            rate_limiter=RateLimiterConfig(max_calls=10, period=LONG),
            shared_state=_shared(backend),
        )
        async def call() -> str:
            return "ok"

        await call()
        windows = _windows(call)
        _end_pause(windows)

        gate = threading.Event()
        backend.gate = gate
        retrying = asyncio.ensure_future(call())
        try:
            loop = asyncio.get_running_loop()
            assert await loop.run_in_executor(None, backend.waiting.wait, 10.0)
            _age(windows, windows._pause + 0.5)

            for _ in range(3):
                assert await call() == "ok"
            assert backend.attempts == 2
        finally:
            gate.set()
        assert await retrying == "ok"
