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


class TestCustomPoolSize:
    def test_custom_timeout_pool_size(self) -> None:
        """Test custom ThreadPoolExecutor pool size."""

        @resilient(timeout=TimeoutConfig(seconds=5.0, pool_size=2))
        def fast() -> str:
            return "ok"

        assert fast() == "ok"


class TestTimeoutCancellation:
    def test_timeout_attempts_thread_interrupt(self) -> None:
        """Timeout uses best-effort thread interruption via PyThreadState_SetAsyncExc."""
        import threading

        interrupted = threading.Event()

        @resilient(timeout=TimeoutConfig(seconds=0.1))
        def long_running() -> str:
            try:
                # Busy-wait in Python bytecode (interruptible)
                while True:
                    _ = 1 + 1
            except BaseException:
                interrupted.set()
                raise
            return "done"

        with pytest.raises(TimeoutError):
            long_running()

        # Give the thread a moment to receive the async exception
        interrupted.wait(timeout=1.0)
        # On CPython, the thread should be interrupted
        import ctypes

        if hasattr(ctypes, "pythonapi"):
            assert interrupted.is_set()

    def test_timeout_preserves_exception_chain(self) -> None:
        """Timeout error chains to the original TimeoutError."""
        from pyresilience._exceptions import ResilienceTimeoutError

        @resilient(timeout=TimeoutConfig(seconds=0.05))
        def slow() -> str:
            time.sleep(2)
            return "done"

        with pytest.raises(ResilienceTimeoutError) as exc_info:
            slow()
        assert exc_info.value.__cause__ is not None


class TestPerAttemptTimeoutSync:
    def test_per_attempt_true_each_attempt_gets_full_timeout(self) -> None:
        """per_attempt=True (default): each retry attempt gets the full timeout."""
        from pyresilience import RetryConfig

        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
            timeout=TimeoutConfig(seconds=0.3, per_attempt=True),
        )
        def my_func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                # Sleep less than timeout — should succeed on each attempt
                time.sleep(0.05)
                raise ValueError("retry me")
            return "ok"

        assert my_func() == "ok"
        assert call_count == 3

    def test_per_attempt_false_total_budget_shared(self) -> None:
        """per_attempt=False: total timeout shared across attempts, later attempts get less time."""
        from pyresilience import RetryConfig
        from pyresilience._exceptions import ResilienceTimeoutError

        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=5, delay=0.01, jitter=False),
            timeout=TimeoutConfig(seconds=0.2, per_attempt=False),
        )
        def my_func() -> str:
            nonlocal call_count
            call_count += 1
            time.sleep(0.1)
            raise ValueError("retry me")

        # With 0.2s total budget and each attempt using ~0.1s + 0.01s delay,
        # we should run out of budget before all 5 attempts
        with pytest.raises((ValueError, ResilienceTimeoutError)):
            my_func()

        assert call_count < 5

    def test_per_attempt_false_deadline_exceeded_raises(self) -> None:
        """per_attempt=False: raises ResilienceTimeoutError when total budget is exhausted."""
        from pyresilience import RetryConfig
        from pyresilience._exceptions import ResilienceTimeoutError

        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=10, delay=0.01, jitter=False),
            timeout=TimeoutConfig(seconds=0.15, per_attempt=False),
        )
        def my_func() -> str:
            nonlocal call_count
            call_count += 1
            time.sleep(0.08)
            raise ValueError("retry me")

        with pytest.raises((ValueError, ResilienceTimeoutError)):
            my_func()

        # Should not use all 10 attempts due to budget constraint
        assert call_count < 10


class TestPerAttemptTimeoutAsync:
    @pytest.mark.asyncio
    async def test_async_per_attempt_true_each_attempt_gets_full_timeout(self) -> None:
        """Async per_attempt=True: each attempt gets the full timeout."""
        from pyresilience import RetryConfig

        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
            timeout=TimeoutConfig(seconds=0.3, per_attempt=True),
        )
        async def my_func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                await asyncio.sleep(0.05)
                raise ValueError("retry me")
            return "ok"

        assert await my_func() == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_async_per_attempt_false_total_budget_shared(self) -> None:
        """Async per_attempt=False: total timeout shared across attempts."""
        from pyresilience import RetryConfig
        from pyresilience._exceptions import ResilienceTimeoutError

        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=5, delay=0.01, jitter=False),
            timeout=TimeoutConfig(seconds=0.2, per_attempt=False),
        )
        async def my_func() -> str:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)
            raise ValueError("retry me")

        with pytest.raises((ValueError, ResilienceTimeoutError)):
            await my_func()

        assert call_count < 5


class TestTimeoutConfigValidation:
    def test_seconds_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="seconds must be > 0"):
            TimeoutConfig(seconds=0)

    def test_pool_size_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="pool_size must be >= 1"):
            TimeoutConfig(pool_size=0)
