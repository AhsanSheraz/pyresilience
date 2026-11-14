"""Tests for shared rate limits while the state backend is unreachable."""

from __future__ import annotations

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
    """Counts the increments it is asked for and fails them while ``down`` is True."""

    def __init__(self) -> None:
        super().__init__()
        self.down = True
        self.attempts = 0

    def incr(self, key: str, amount: float, ttl: Optional[float] = None) -> float:
        self.attempts += 1
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
