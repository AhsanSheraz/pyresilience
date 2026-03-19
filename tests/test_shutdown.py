"""Tests for graceful shutdown infrastructure."""

from __future__ import annotations

import threading
import time

import pytest

import pyresilience._executor as _exec_mod
from pyresilience import resilient
from pyresilience._executor import enable_in_flight_tracking, get_in_flight_count, shutdown


def _reset_shutdown_state() -> None:
    """Reset module-level shutdown globals to clean state."""
    _exec_mod._shutting_down = False
    _exec_mod._tracking_enabled = False
    _exec_mod._in_flight_count = 0
    _exec_mod._in_flight.set()


class TestGetInFlightCount:
    def setup_method(self) -> None:
        _reset_shutdown_state()
        enable_in_flight_tracking()

    def teardown_method(self) -> None:
        _reset_shutdown_state()

    def test_returns_zero_when_idle(self) -> None:
        assert get_in_flight_count() == 0

    def test_increments_during_call(self) -> None:
        seen_count = 0
        barrier = threading.Event()
        done = threading.Event()

        @resilient()
        def slow_func() -> str:
            nonlocal seen_count
            seen_count = get_in_flight_count()
            barrier.set()
            done.wait(timeout=5.0)
            return "ok"

        t = threading.Thread(target=slow_func)
        t.start()

        barrier.wait(timeout=5.0)
        assert seen_count >= 1

        done.set()
        t.join(timeout=5.0)

    def test_returns_zero_after_call_completes(self) -> None:
        @resilient()
        def quick_func() -> str:
            return "done"

        quick_func()
        assert get_in_flight_count() == 0

    def test_tracks_multiple_concurrent_calls(self) -> None:
        max_seen = 0
        lock = threading.Lock()
        all_started = threading.Barrier(3, timeout=5.0)
        release = threading.Event()

        @resilient()
        def concurrent_func() -> str:
            nonlocal max_seen
            all_started.wait()
            current = get_in_flight_count()
            with lock:
                if current > max_seen:
                    max_seen = current
            release.wait(timeout=5.0)
            return "ok"

        threads = [threading.Thread(target=concurrent_func) for _ in range(3)]
        for t in threads:
            t.start()

        # Wait a bit for all threads to reach the barrier
        time.sleep(0.1)
        release.set()

        for t in threads:
            t.join(timeout=5.0)

        assert max_seen >= 2  # At least 2 concurrent calls seen

    def test_tracking_disabled_by_default(self) -> None:
        """Without enable_in_flight_tracking(), count stays 0."""
        _reset_shutdown_state()  # Disables tracking

        @resilient()
        def func() -> str:
            return "ok"

        func()
        assert get_in_flight_count() == 0


class TestShutdown:
    def setup_method(self) -> None:
        _reset_shutdown_state()

    def teardown_method(self) -> None:
        _reset_shutdown_state()

    def test_returns_true_when_no_calls_in_progress(self) -> None:
        result = shutdown(wait=True, timeout=5.0)
        assert result is True

    def test_returns_true_after_calls_drain(self) -> None:
        enable_in_flight_tracking()
        done = threading.Event()

        @resilient()
        def slow_func() -> str:
            done.wait(timeout=5.0)
            return "ok"

        t = threading.Thread(target=slow_func)
        t.start()

        # Give the call time to start
        time.sleep(0.05)
        assert get_in_flight_count() >= 1

        # Release the call so it drains
        done.set()
        t.join(timeout=5.0)

        result = shutdown(wait=True, timeout=5.0)
        assert result is True

    def test_returns_false_on_timeout(self) -> None:
        enable_in_flight_tracking()
        release = threading.Event()

        @resilient()
        def blocking_func() -> str:
            release.wait(timeout=10.0)
            return "ok"

        t = threading.Thread(target=blocking_func)
        t.start()

        # Give the call time to start
        time.sleep(0.05)

        result = shutdown(wait=True, timeout=0.1)
        assert result is False

        # Clean up
        release.set()
        t.join(timeout=5.0)

    def test_sets_shutting_down_flag(self) -> None:
        assert _exec_mod._shutting_down is False
        shutdown(wait=True, timeout=1.0)
        assert _exec_mod._shutting_down is True

    def test_shutdown_without_wait(self) -> None:
        result = shutdown(wait=False, timeout=1.0)
        assert result is True

    def test_shutdown_enables_tracking(self) -> None:
        """shutdown() automatically enables in-flight tracking."""
        assert _exec_mod._tracking_enabled is False
        shutdown(wait=True, timeout=1.0)
        assert _exec_mod._tracking_enabled is True

    def test_in_flight_event_cleared_during_call(self) -> None:
        """The _in_flight event should be cleared while a call is active."""
        enable_in_flight_tracking()
        barrier = threading.Event()
        release = threading.Event()

        @resilient()
        def func() -> str:
            barrier.set()
            release.wait(timeout=5.0)
            return "ok"

        t = threading.Thread(target=func)
        t.start()

        barrier.wait(timeout=5.0)
        # Event should be cleared (not set) during call
        assert not _exec_mod._in_flight.is_set()

        release.set()
        t.join(timeout=5.0)

        # Event should be set again after call
        assert _exec_mod._in_flight.is_set()


class TestShutdownAsync:
    @pytest.mark.asyncio
    async def test_async_call_tracks_in_flight(self) -> None:
        """Async calls should also be tracked by the in-flight counter."""
        _reset_shutdown_state()
        enable_in_flight_tracking()

        try:

            @resilient()
            async def async_func() -> str:
                return "ok"

            await async_func()
            assert get_in_flight_count() == 0
        finally:
            _reset_shutdown_state()
