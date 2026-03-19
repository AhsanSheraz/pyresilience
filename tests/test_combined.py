"""Tests for combined resilience patterns."""

from __future__ import annotations

import logging
import time

import pytest

from pyresilience import (
    BulkheadConfig,
    CircuitBreakerConfig,
    CircuitOpenError,
    EventType,
    FallbackConfig,
    ResilienceEvent,
    ResilienceTimeoutError,
    RetryConfig,
    TimeoutConfig,
    resilient,
)


class TestCombinedPatterns:
    def test_retry_with_timeout(self) -> None:
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
            timeout=TimeoutConfig(seconds=0.5),
        )
        def sometimes_slow() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                time.sleep(2)  # Trigger timeout
            return "ok"

        result = sometimes_slow()
        assert result == "ok"
        assert call_count == 2

    def test_retry_with_fallback(self) -> None:
        @resilient(
            retry=RetryConfig(max_attempts=2, delay=0.01),
            fallback=FallbackConfig(handler="fallback_value"),
        )
        def always_fails() -> str:
            raise ValueError("fail")

        assert always_fails() == "fallback_value"

    def test_circuit_breaker_with_retry(self) -> None:
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=2, delay=0.01),
            circuit_breaker=CircuitBreakerConfig(failure_threshold=3),
        )
        def fails() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        # First call: 2 attempts = 2 failures (CB still closed)
        with pytest.raises(ValueError):
            fails()

        # Second call: attempt 1 fails (3rd failure, CB opens),
        # retry re-checks CB which is now open → CircuitOpenError
        with pytest.raises((ValueError, CircuitOpenError)):
            fails()

        # Circuit should be open now
        with pytest.raises(CircuitOpenError, match="Circuit breaker is open"):
            fails()

    def test_all_patterns_success(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            retry=RetryConfig(max_attempts=2, delay=0.01),
            timeout=TimeoutConfig(seconds=5.0),
            circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
            fallback=FallbackConfig(handler="fallback"),
            listeners=[events.append],
        )
        def works() -> str:
            return "success"

        result = works()
        assert result == "success"
        event_types = [e.event_type for e in events]
        assert EventType.SUCCESS in event_types

    def test_all_patterns_failure_with_fallback(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            retry=RetryConfig(max_attempts=2, delay=0.01),
            timeout=TimeoutConfig(seconds=5.0),
            circuit_breaker=CircuitBreakerConfig(failure_threshold=10),
            fallback=FallbackConfig(handler=lambda e: "graceful_degradation"),
            listeners=[events.append],
        )
        def always_fails() -> str:
            raise ValueError("fail")

        result = always_fails()
        assert result == "graceful_degradation"
        event_types = [e.event_type for e in events]
        assert EventType.RETRY in event_types
        assert EventType.RETRY_EXHAUSTED in event_types
        assert EventType.FALLBACK_USED in event_types


class TestCombinedAsync:
    @pytest.mark.asyncio
    async def test_async_retry_with_fallback(self) -> None:
        @resilient(
            retry=RetryConfig(max_attempts=2, delay=0.01),
            fallback=FallbackConfig(handler="async_fallback"),
        )
        async def always_fails() -> str:
            raise ValueError("fail")

        assert await always_fails() == "async_fallback"


class TestJitterFloor:
    def test_jitter_never_returns_zero(self) -> None:
        """Verify jitter has a 10% floor — no zero-delay retry storms."""
        from pyresilience._executor import _compute_delay

        cfg = RetryConfig(delay=1.0, backoff_factor=2.0, jitter=True)
        # Run many times to check the floor
        for attempt in range(1, 10):
            for _ in range(100):
                delay = _compute_delay(cfg, attempt)
                base = min(cfg.delay * (cfg.backoff_factor ** (attempt - 1)), cfg.max_delay)
                assert delay >= base * 0.1, f"delay {delay} below 10% floor of {base * 0.1}"

    def test_jitter_zero_base_delay_allowed(self) -> None:
        """When user sets delay=0, jitter floor is also 0."""
        from pyresilience._executor import _compute_delay

        cfg = RetryConfig(delay=0.0, backoff_factor=2.0, jitter=True)
        delay = _compute_delay(cfg, 1)
        assert delay == 0.0


class TestCircuitBreakerRecheck:
    def test_cb_recheck_stops_retries(self) -> None:
        """Verify circuit breaker is re-checked between retry attempts."""
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=5, delay=0.001),
            circuit_breaker=CircuitBreakerConfig(failure_threshold=2, recovery_timeout=60),
        )
        def fails() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        with pytest.raises((ValueError, CircuitOpenError)):
            fails()

        # Should have stopped early — CB opens after 2 failures,
        # 3rd attempt blocked by re-check
        assert call_count <= 3


class TestListenerErrorLogging:
    def test_broken_listener_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Verify broken listener errors are logged, not silently swallowed."""

        def broken_listener(event: ResilienceEvent) -> None:
            raise RuntimeError("listener crashed")

        @resilient(
            retry=RetryConfig(max_attempts=1),
            listeners=[broken_listener],
        )
        def works() -> str:
            return "ok"

        with caplog.at_level(logging.WARNING, logger="pyresilience"):
            result = works()

        assert result == "ok"
        assert any(
            "Listener" in r.message and "raised an exception" in r.message for r in caplog.records
        )


class TestTimeoutErrorChain:
    def test_timeout_preserves_cause(self) -> None:
        """Verify ResilienceTimeoutError chains from original exception."""

        @resilient(timeout=TimeoutConfig(seconds=0.1))
        def slow() -> str:
            time.sleep(5)
            return "ok"

        with pytest.raises(ResilienceTimeoutError) as exc_info:
            slow()

        # __cause__ should be set (from exc), not suppressed (from None)
        assert exc_info.value.__cause__ is not None


class TestDecoratorIntrospection:
    def test_sync_wrapper_has_executor(self) -> None:
        @resilient(retry=RetryConfig(max_attempts=2))
        def my_func() -> str:
            return "ok"

        assert hasattr(my_func, "_executor")
        assert hasattr(my_func, "__wrapped__")

    @pytest.mark.asyncio
    async def test_async_wrapper_has_executor(self) -> None:
        @resilient(retry=RetryConfig(max_attempts=2))
        async def my_func() -> str:
            return "ok"

        assert hasattr(my_func, "_executor")
        assert hasattr(my_func, "__wrapped__")


class TestBulkheadReleaseDuringSleep:
    def test_bulkhead_released_during_retry_sleep(self) -> None:
        """Verify bulkhead slot is released during retry backoff."""
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.1, jitter=False),
            bulkhead=BulkheadConfig(max_concurrent=1),
        )
        def fails_then_works() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "ok"

        result = fails_then_works()
        assert result == "ok"
        assert call_count == 3


class TestAsyncCombinedEdgeCases:
    @pytest.mark.asyncio
    async def test_async_bulkhead_rejects_with_fallback(self) -> None:
        """Test async bulkhead rejection with fallback."""
        import asyncio

        @resilient(
            bulkhead=BulkheadConfig(max_concurrent=1, max_wait=0),
            fallback=FallbackConfig(handler="busy"),
        )
        async def slow() -> str:
            await asyncio.sleep(0.3)
            return "done"

        async def run_both() -> tuple[str, str]:
            t1 = asyncio.create_task(slow())
            await asyncio.sleep(0.05)
            t2 = asyncio.create_task(slow())
            r1 = await t1
            r2 = await t2
            return r1, r2

        r1, r2 = await run_both()
        assert r1 == "done"
        assert r2 == "busy"

    @pytest.mark.asyncio
    async def test_async_bulkhead_rejects_without_fallback(self) -> None:
        """Test async bulkhead rejection raises error."""
        import asyncio

        from pyresilience._exceptions import BulkheadFullError

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

    @pytest.mark.asyncio
    async def test_async_retry_exhausted_event(self) -> None:
        """Test async retry exhausted event is emitted."""

        events: list[ResilienceEvent] = []

        @resilient(
            retry=RetryConfig(max_attempts=2, delay=0.01),
            listeners=[events.append],
        )
        async def always_fails() -> str:
            raise ValueError("fail")

        with pytest.raises(ValueError):
            await always_fails()

        event_types = [e.event_type for e in events]
        assert EventType.RETRY_EXHAUSTED in event_types
        assert EventType.FAILURE in event_types

    @pytest.mark.asyncio
    async def test_async_cache_hit_miss_with_listeners(self) -> None:
        """Async cache hit/miss with listeners."""
        from pyresilience import CacheConfig

        events: list[ResilienceEvent] = []

        @resilient(
            cache=CacheConfig(max_size=10, ttl=60),
            listeners=[events.append],
        )
        async def cached_func(x: int) -> int:
            return x * 2

        r1 = await cached_func(5)
        assert r1 == 10
        r2 = await cached_func(5)
        assert r2 == 10

        event_types = [e.event_type for e in events]
        assert EventType.CACHE_MISS in event_types
        assert EventType.CACHE_HIT in event_types

    @pytest.mark.asyncio
    async def test_async_timeout_with_listeners(self) -> None:
        """Async timeout with listeners."""
        import asyncio

        events: list[ResilienceEvent] = []

        @resilient(
            timeout=TimeoutConfig(seconds=0.05),
            listeners=[events.append],
        )
        async def slow() -> str:
            await asyncio.sleep(5)
            return "done"

        with pytest.raises(TimeoutError):
            await slow()

        event_types = [e.event_type for e in events]
        assert EventType.TIMEOUT in event_types

    @pytest.mark.asyncio
    async def test_async_slow_call_with_listeners(self) -> None:
        """Async slow call detection with listeners."""
        import asyncio

        events: list[ResilienceEvent] = []

        @resilient(
            circuit_breaker=CircuitBreakerConfig(
                failure_threshold=10,
                slow_call_duration=0.05,
                slow_call_rate_threshold=1.0,
            ),
            listeners=[events.append],
        )
        async def slow() -> str:
            await asyncio.sleep(0.1)
            return "ok"

        result = await slow()
        assert result == "ok"
        event_types = [e.event_type for e in events]
        assert EventType.SLOW_CALL in event_types

    @pytest.mark.asyncio
    async def test_async_retry_on_result_with_listeners(self) -> None:
        """Async retry_on_result with listeners."""
        events: list[ResilienceEvent] = []
        call_count = 0

        @resilient(
            retry=RetryConfig(
                max_attempts=3,
                delay=0.001,
                retry_on_result=lambda r: r == "retry_me",
            ),
            listeners=[events.append],
        )
        async def conditional() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return "retry_me"
            return "ok"

        result = await conditional()
        assert result == "ok"
        assert call_count == 3
        event_types = [e.event_type for e in events]
        assert EventType.RETRY in event_types

    @pytest.mark.asyncio
    async def test_async_retry_on_result_returns_last_result(self) -> None:
        """On last attempt, result is returned even if predicate matches."""

        @resilient(
            retry=RetryConfig(
                max_attempts=2,
                delay=0.001,
                retry_on_result=lambda r: r == "bad",
            ),
        )
        async def always_bad() -> str:
            return "bad"

        result = await always_bad()
        assert result == "bad"

    @pytest.mark.asyncio
    async def test_async_fallback_used_on_exception(self) -> None:
        """Async fallback_used event with listeners."""
        events: list[ResilienceEvent] = []

        @resilient(
            fallback=FallbackConfig(handler="fallback_val"),
            listeners=[events.append],
        )
        async def fails() -> str:
            raise ValueError("fail")

        result = await fails()
        assert result == "fallback_val"
        event_types = [e.event_type for e in events]
        assert EventType.FALLBACK_USED in event_types

    @pytest.mark.asyncio
    async def test_async_rate_limited_with_listeners_and_fallback(self) -> None:
        """Async rate limiter + listeners + fallback."""
        from pyresilience import RateLimiterConfig

        events: list[ResilienceEvent] = []

        @resilient(
            rate_limiter=RateLimiterConfig(max_calls=1, period=60.0),
            fallback=FallbackConfig(handler="async_rate_limited"),
            listeners=[events.append],
        )
        async def limited() -> str:
            return "ok"

        r1 = await limited()
        assert r1 == "ok"

        r2 = await limited()
        assert r2 == "async_rate_limited"
        event_types = [e.event_type for e in events]
        assert EventType.RATE_LIMITED in event_types
        assert EventType.FALLBACK_USED in event_types

    @pytest.mark.asyncio
    async def test_async_bulkhead_rejected_with_listeners_and_fallback(self) -> None:
        """Async bulkhead + listeners + fallback."""
        import asyncio

        events: list[ResilienceEvent] = []

        @resilient(
            bulkhead=BulkheadConfig(max_concurrent=1, max_wait=0),
            fallback=FallbackConfig(handler="async_busy"),
            listeners=[events.append],
        )
        async def slow() -> str:
            await asyncio.sleep(0.3)
            return "done"

        t1 = asyncio.create_task(slow())
        await asyncio.sleep(0.05)
        t2 = asyncio.create_task(slow())

        r1 = await t1
        r2 = await t2
        assert r1 == "done"
        assert r2 == "async_busy"
        event_types = [e.event_type for e in events]
        assert EventType.BULKHEAD_REJECTED in event_types
        assert EventType.FALLBACK_USED in event_types


class TestPoolShutdown:
    def test_shutdown_pools_cleans_up(self) -> None:
        """Test _shutdown_pools cleans up custom pools."""
        from concurrent.futures import ThreadPoolExecutor

        from pyresilience._executor import _custom_pools, _register_custom_pool, _shutdown_pools

        pool = ThreadPoolExecutor(max_workers=1)
        _register_custom_pool(pool)
        assert len(_custom_pools) > 0
        _shutdown_pools()
        assert len(_custom_pools) == 0


class TestCBRecheckWithFallback:
    def test_sync_cb_recheck_triggers_fallback(self) -> None:
        """CB opens during retry, fallback catches CircuitOpenError."""
        events: list[ResilienceEvent] = []
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=5, delay=0.001),
            circuit_breaker=CircuitBreakerConfig(failure_threshold=2, recovery_timeout=60),
            fallback=FallbackConfig(handler="cb_fallback"),
            listeners=[events.append],
        )
        def always_fails() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        result = always_fails()
        assert result == "cb_fallback"
        event_types = [e.event_type for e in events]
        assert EventType.CIRCUIT_OPEN in event_types
        assert EventType.FALLBACK_USED in event_types

    @pytest.mark.asyncio
    async def test_async_cb_recheck_triggers_fallback(self) -> None:
        """Async: CB opens during retry, fallback catches CircuitOpenError."""
        events: list[ResilienceEvent] = []
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=5, delay=0.001),
            circuit_breaker=CircuitBreakerConfig(failure_threshold=2, recovery_timeout=60),
            fallback=FallbackConfig(handler="async_cb_fallback"),
            listeners=[events.append],
        )
        async def always_fails() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        result = await always_fails()
        assert result == "async_cb_fallback"
        event_types = [e.event_type for e in events]
        assert EventType.CIRCUIT_OPEN in event_types
        assert EventType.FALLBACK_USED in event_types


class TestRetryOnResultWithBulkhead:
    def test_sync_retry_on_result_releases_bulkhead(self) -> None:
        """retry_on_result with bulkhead releases slot during sleep."""
        call_count = 0

        @resilient(
            retry=RetryConfig(
                max_attempts=3,
                delay=0.01,
                jitter=False,
                retry_on_result=lambda r: r == "bad",
            ),
            bulkhead=BulkheadConfig(max_concurrent=1),
        )
        def eventually_good() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return "bad"
            return "good"

        result = eventually_good()
        assert result == "good"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_async_retry_on_result_releases_bulkhead(self) -> None:
        """Async: retry_on_result with bulkhead releases slot during sleep."""
        call_count = 0

        @resilient(
            retry=RetryConfig(
                max_attempts=3,
                delay=0.01,
                jitter=False,
                retry_on_result=lambda r: r == "bad",
            ),
            bulkhead=BulkheadConfig(max_concurrent=1),
        )
        async def eventually_good() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return "bad"
            return "good"

        result = await eventually_good()
        assert result == "good"
        assert call_count == 3


class TestAsyncRetryBulkheadRelease:
    @pytest.mark.asyncio
    async def test_async_bulkhead_released_during_retry_sleep(self) -> None:
        """Async: bulkhead slot released during retry backoff on exception."""
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.05, jitter=False),
            bulkhead=BulkheadConfig(max_concurrent=1),
        )
        async def fails_then_works() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "ok"

        result = await fails_then_works()
        assert result == "ok"
        assert call_count == 3


class TestAsyncFallbackOnFailure:
    @pytest.mark.asyncio
    async def test_async_fallback_after_retry_exhausted(self) -> None:
        """Async: fallback used after retries exhausted."""
        events: list[ResilienceEvent] = []

        @resilient(
            retry=RetryConfig(max_attempts=2, delay=0.001),
            fallback=FallbackConfig(handler="async_fb"),
            listeners=[events.append],
        )
        async def always_fails() -> str:
            raise ValueError("fail")

        result = await always_fails()
        assert result == "async_fb"
        event_types = [e.event_type for e in events]
        assert EventType.RETRY_EXHAUSTED in event_types
        assert EventType.FALLBACK_USED in event_types
