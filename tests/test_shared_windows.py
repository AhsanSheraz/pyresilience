"""Tests for corrections of shared rate-limit windows, including window rollover."""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from pyresilience import (
    InMemoryBackend,
    RateLimit,
    RateLimiterConfig,
    SharedStateConfig,
    resilient,
)
from pyresilience._shared import _SharedWindows


def _windows(backend: InMemoryBackend, period: float = 3600.0) -> _SharedWindows:
    return _SharedWindows(backend, "svc", ["tokens"], [100.0], [period], fail_open=True)


def _values(backend: InMemoryBackend) -> dict[str, float]:
    names = backend.keys()
    return {key: float(backend.get(key) or 0.0) for key in names}


class TestSharedWindowCorrections:
    def test_acquire_reports_the_window_it_counted_in(self) -> None:
        backend = InMemoryBackend()
        ok, wait, blocker, windows = _windows(backend).acquire([40.0])
        assert (ok, wait, blocker) == (True, 0.0, "")
        assert windows[0] is not None
        assert _values(backend) == {windows[0]: 40.0}

    def test_zero_cost_touches_no_window(self) -> None:
        backend = InMemoryBackend()
        ok, _, _, windows = _windows(backend).acquire([0.0])
        assert ok is True
        assert windows == [None]
        assert backend.keys() == []

    def test_refund_goes_back_to_the_same_window(self) -> None:
        backend = InMemoryBackend()
        shared = _windows(backend)
        _, _, _, windows = shared.acquire([90.0])
        shared.adjust([80.0], windows)
        assert _values(backend) == {windows[0]: 10.0}

    def test_refund_is_dropped_once_the_window_has_passed(self) -> None:
        backend = InMemoryBackend()
        shared = _windows(backend)
        shared.acquire([90.0])
        # The call was counted in an earlier window than the current one
        shared.adjust([80.0], ["svc:rl:tokens:0"])
        values = _values(backend)
        # Nothing may go negative: the current window never held these units
        assert all(value >= 0 for value in values.values())
        assert sum(values.values()) == 90.0

    def test_refund_without_known_window_is_dropped(self) -> None:
        backend = InMemoryBackend()
        shared = _windows(backend)
        _, _, _, windows = shared.acquire([90.0])
        shared.adjust([80.0], None)
        assert _values(backend) == {windows[0]: 90.0}

    def test_extra_usage_is_charged_to_the_current_window(self) -> None:
        backend = InMemoryBackend()
        shared = _windows(backend)
        _, _, _, windows = shared.acquire([10.0])
        shared.adjust([-25.0], ["svc:rl:tokens:0"])
        assert _values(backend) == {windows[0]: 35.0}

    def test_charge_adds_to_the_current_window_without_a_limit_check(self) -> None:
        backend = InMemoryBackend()
        shared = _windows(backend)
        _, _, _, windows = shared.acquire([90.0])
        charged = shared.charge([90.0])
        assert charged == windows
        assert _values(backend) == {windows[0]: 180.0}

    def test_charge_reports_backend_failure(self) -> None:
        class Down(InMemoryBackend):
            def incr(self, key: str, amount: float, ttl: Optional[float] = None) -> float:
                raise ConnectionError("backend down")

        assert _windows(Down()).charge([5.0]) is None

    def test_undo_keeps_an_expiry_on_the_counter(self) -> None:
        backend = InMemoryBackend()
        shared = _windows(backend, period=0.05)
        ok, _, _, _ = shared.acquire([500.0])  # above capacity: taken and given back
        assert ok is False
        time.sleep(0.15)
        # The counter that was touched expires like any other
        assert backend.keys() == []


class TestLongCallsAcrossAWindow:
    def test_sync_call_spanning_a_window_leaves_no_negative_counter(self) -> None:
        backend = InMemoryBackend()
        limiter = RateLimiterConfig(
            max_calls=100,
            period=0.3,
            limits=[
                RateLimit(100, 0.3, name="tokens", cost=lambda: 90, actual_cost=lambda result: 10)
            ],
        )

        @resilient(
            rate_limiter=limiter,
            shared_state=SharedStateConfig(backend=backend, key="svc", sync_interval=0),
        )
        def slow_call() -> str:
            time.sleep(0.35)  # longer than one window
            return "ok"

        assert slow_call() == "ok"
        tokens = {k: v for k, v in _values(backend).items() if ":tokens:" in k}
        assert all(value >= 0 for value in tokens.values())

    async def test_async_call_spanning_a_window_leaves_no_negative_counter(self) -> None:
        backend = InMemoryBackend()
        limiter = RateLimiterConfig(
            max_calls=100,
            period=0.3,
            limits=[
                RateLimit(100, 0.3, name="tokens", cost=lambda: 90, actual_cost=lambda result: 10)
            ],
        )

        @resilient(
            rate_limiter=limiter,
            shared_state=SharedStateConfig(backend=backend, key="svc", sync_interval=0),
        )
        async def slow_call() -> str:
            await asyncio.sleep(0.35)
            return "ok"

        assert await slow_call() == "ok"
        tokens = {k: v for k, v in _values(backend).items() if ":tokens:" in k}
        assert all(value >= 0 for value in tokens.values())
