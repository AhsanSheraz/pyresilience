"""Additional tests to cover edge cases and boost coverage."""

from __future__ import annotations

import asyncio
import time
from unittest import mock

import pytest

from pyresilience import (
    BulkheadConfig,
    CacheConfig,
    CircuitBreakerConfig,
    EventType,
    FallbackConfig,
    RateLimiterConfig,
    ResilienceEvent,
    RetryConfig,
    TimeoutConfig,
    resilient,
)
from pyresilience._bulkhead import AsyncBulkhead, Bulkhead, BulkheadFullError


class TestBulkheadEdgeCases:
    def test_sync_bulkhead_with_wait(self) -> None:
        """Test sync bulkhead with max_wait > 0."""
        bulkhead = Bulkhead(BulkheadConfig(max_concurrent=1, max_wait=0.5))
        assert bulkhead.acquire()
        bulkhead.release()

    def test_sync_bulkhead_wait_timeout(self) -> None:
        """Test sync bulkhead times out waiting for slot."""
        bulkhead = Bulkhead(BulkheadConfig(max_concurrent=1, max_wait=0.1))
        assert bulkhead.acquire()
        # Second acquire should timeout
        assert not bulkhead.acquire()
        bulkhead.release()

    @pytest.mark.asyncio
    async def test_async_bulkhead_with_wait(self) -> None:
        """Test async bulkhead with max_wait > 0."""
        config = BulkheadConfig(max_concurrent=1, max_wait=0.5)
        bulkhead = AsyncBulkhead(config)
        assert await bulkhead.acquire()
        bulkhead.release()

    @pytest.mark.asyncio
    async def test_async_bulkhead_wait_timeout(self) -> None:
        """Test async bulkhead times out waiting for slot."""
        config = BulkheadConfig(max_concurrent=1, max_wait=0.1)
        bulkhead = AsyncBulkhead(config)
        assert await bulkhead.acquire()
        # Second acquire should timeout
        assert not await bulkhead.acquire()
        bulkhead.release()

    @pytest.mark.asyncio
    async def test_async_bulkhead_release_without_acquire(self) -> None:
        """Test releasing async bulkhead when semaphore is None."""
        config = BulkheadConfig(max_concurrent=1)
        bulkhead = AsyncBulkhead(config)
        # Release without acquiring — semaphore is None, should not crash
        bulkhead.release()


class TestMaxDelayCap:
    def test_max_delay_caps_computed_delay(self) -> None:
        """Cover line 66: delay = retry_cfg.max_delay."""
        call_count = 0

        @resilient(
            retry=RetryConfig(
                max_attempts=3,
                delay=10.0,
                backoff_factor=10.0,
                max_delay=0.01,
                jitter=False,
            ),
        )
        def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "ok"

        result = flaky()
        assert result == "ok"
        assert call_count == 3


class TestCustomPoolSize:
    def test_custom_timeout_pool_size(self) -> None:
        """Cover line 133: custom ThreadPoolExecutor."""

        @resilient(timeout=TimeoutConfig(seconds=5.0, pool_size=2))
        def fast() -> str:
            return "ok"

        assert fast() == "ok"


class TestSyncCircuitBreakerWithListenersAndFallback:
    def test_circuit_open_with_listeners_and_fallback(self) -> None:
        """Cover lines 171, 174: circuit open + listeners + fallback."""
        events: list[ResilienceEvent] = []

        @resilient(
            circuit_breaker=CircuitBreakerConfig(failure_threshold=1, recovery_timeout=60),
            fallback=FallbackConfig(handler="fallback_val", fallback_on=(RuntimeError,)),
            listeners=[events.append],
        )
        def fails() -> str:
            raise ValueError("fail")

        # First call fails (ValueError not in fallback_on), opens circuit
        with pytest.raises(ValueError):
            fails()

        # Second call hits open circuit → RuntimeError → caught by fallback
        result = fails()
        assert result == "fallback_val"
        event_types = [e.event_type for e in events]
        assert EventType.CIRCUIT_OPEN in event_types
        assert EventType.FALLBACK_USED in event_types


class TestSyncRateLimiterWithListenersAndFallback:
    def test_rate_limited_with_listeners_and_fallback(self) -> None:
        """Cover lines 185, 193, 196: rate limiter + listeners + fallback."""
        events: list[ResilienceEvent] = []

        @resilient(
            rate_limiter=RateLimiterConfig(max_calls=1, period=60.0),
            fallback=FallbackConfig(handler="rate_limited_val"),
            listeners=[events.append],
        )
        def limited() -> str:
            return "ok"

        # First call succeeds
        r1 = limited()
        assert r1 == "ok"

        # Second call hits rate limit → fallback
        r2 = limited()
        assert r2 == "rate_limited_val"
        event_types = [e.event_type for e in events]
        assert EventType.RATE_LIMITED in event_types
        assert EventType.FALLBACK_USED in event_types


class TestSyncBulkheadWithListenersAndFallback:
    def test_bulkhead_rejected_with_listeners_and_fallback(self) -> None:
        """Cover lines 193, 196: bulkhead rejection + listeners + fallback."""
        events: list[ResilienceEvent] = []
        import threading

        @resilient(
            bulkhead=BulkheadConfig(max_concurrent=1, max_wait=0),
            fallback=FallbackConfig(handler="busy_val"),
            listeners=[events.append],
        )
        def slow() -> str:
            time.sleep(0.3)
            return "done"

        results: list[str] = [None, None]  # type: ignore[list-item]

        def run(idx: int) -> None:
            results[idx] = slow()

        t1 = threading.Thread(target=run, args=(0,))
        t2 = threading.Thread(target=run, args=(1,))
        t1.start()
        time.sleep(0.05)
        t2.start()
        t1.join()
        t2.join()

        assert "done" in results
        assert "busy_val" in results
        event_types = [e.event_type for e in events]
        assert EventType.BULKHEAD_REJECTED in event_types
        assert EventType.FALLBACK_USED in event_types


class TestSyncRetryOnResultRetries:
    def test_retry_on_result_retries_then_succeeds(self) -> None:
        """Test retry_on_result retries and eventually returns good result."""
        events: list[ResilienceEvent] = []
        call_count = 0

        @resilient(
            retry=RetryConfig(
                max_attempts=3,
                delay=0.001,
                retry_on_result=lambda r: r == "bad",
            ),
            listeners=[events.append],
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
        event_types = [e.event_type for e in events]
        assert EventType.RETRY in event_types

    def test_retry_on_result_returns_last_result_when_exhausted(self) -> None:
        """On last attempt, result is returned even if predicate matches."""

        @resilient(
            retry=RetryConfig(
                max_attempts=2,
                delay=0.001,
                retry_on_result=lambda r: r == "bad",
            ),
        )
        def always_bad() -> str:
            return "bad"

        result = always_bad()
        assert result == "bad"


class TestAsyncExecutorEdgeCases:
    @pytest.mark.asyncio
    async def test_async_circuit_breaker_opens_and_rejects(self) -> None:
        """Test async circuit breaker opens and rejects."""
        call_count = 0

        @resilient(
            circuit_breaker=CircuitBreakerConfig(failure_threshold=2, recovery_timeout=10),
        )
        async def fails() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        for _ in range(2):
            with pytest.raises(ValueError):
                await fails()

        with pytest.raises(RuntimeError, match="Circuit breaker is open"):
            await fails()
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_async_circuit_breaker_with_fallback(self) -> None:
        """Test async circuit breaker with fallback when open."""

        @resilient(
            circuit_breaker=CircuitBreakerConfig(failure_threshold=1, recovery_timeout=10),
            fallback=FallbackConfig(handler="fallback_value"),
        )
        async def fails() -> str:
            raise ValueError("fail")

        await fails()  # Opens circuit
        result = await fails()  # Returns fallback
        assert result == "fallback_value"

    @pytest.mark.asyncio
    async def test_async_bulkhead_rejects_with_fallback(self) -> None:
        """Test async bulkhead rejection with fallback."""

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
    async def test_async_circuit_breaker_failure_tracking(self) -> None:
        """Test async circuit breaker records failures."""
        events: list[ResilienceEvent] = []

        @resilient(
            circuit_breaker=CircuitBreakerConfig(failure_threshold=2),
            listeners=[events.append],
        )
        async def fails() -> str:
            raise ValueError("fail")

        for _ in range(2):
            with pytest.raises(ValueError):
                await fails()

        event_types = [e.event_type for e in events]
        assert EventType.CIRCUIT_OPEN in event_types

    @pytest.mark.asyncio
    async def test_async_circuit_breaker_success_closes(self) -> None:
        """Test async circuit breaker closes on success after half-open."""
        events: list[ResilienceEvent] = []
        call_count = 0

        @resilient(
            circuit_breaker=CircuitBreakerConfig(
                failure_threshold=1, recovery_timeout=0.1, success_threshold=1
            ),
            listeners=[events.append],
        )
        async def sometimes_fails() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("fail")
            return "ok"

        # First call fails, opens circuit
        with pytest.raises(ValueError):
            await sometimes_fails()

        # Wait for recovery
        await asyncio.sleep(0.15)

        # Next call succeeds, closes circuit
        result = await sometimes_fails()
        assert result == "ok"
        event_types = [e.event_type for e in events]
        assert EventType.CIRCUIT_CLOSED in event_types

    @pytest.mark.asyncio
    async def test_async_cache_hit_miss_with_listeners(self) -> None:
        """Cover lines 440, 443: async cache hit/miss with listeners."""
        events: list[ResilienceEvent] = []

        @resilient(
            cache=CacheConfig(max_size=10, ttl=60),
            listeners=[events.append],
        )
        async def cached_func(x: int) -> int:
            return x * 2

        # First call: cache miss
        r1 = await cached_func(5)
        assert r1 == 10

        # Second call: cache hit
        r2 = await cached_func(5)
        assert r2 == 10

        event_types = [e.event_type for e in events]
        assert EventType.CACHE_MISS in event_types
        assert EventType.CACHE_HIT in event_types

    @pytest.mark.asyncio
    async def test_async_circuit_open_with_listeners_and_fallback(self) -> None:
        """Cover lines 449, 452: async circuit open + listeners + fallback."""
        events: list[ResilienceEvent] = []

        @resilient(
            circuit_breaker=CircuitBreakerConfig(failure_threshold=1, recovery_timeout=60),
            fallback=FallbackConfig(handler="async_fallback", fallback_on=(RuntimeError,)),
            listeners=[events.append],
        )
        async def fails() -> str:
            raise ValueError("fail")

        # Opens circuit (ValueError not in fallback_on)
        with pytest.raises(ValueError):
            await fails()

        # Hits open circuit → RuntimeError → caught by fallback
        result = await fails()
        assert result == "async_fallback"
        event_types = [e.event_type for e in events]
        assert EventType.CIRCUIT_OPEN in event_types
        assert EventType.FALLBACK_USED in event_types

    @pytest.mark.asyncio
    async def test_async_rate_limited_with_listeners_and_fallback(self) -> None:
        """Cover lines 460, 462-464: async rate limiter + listeners + fallback."""
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
        """Cover lines 471, 474: async bulkhead + listeners + fallback."""
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

    @pytest.mark.asyncio
    async def test_async_timeout_with_listeners(self) -> None:
        """Cover line 524: async timeout with listeners."""
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
        """Cover lines 515, 562: async slow call detection with listeners."""
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
        """Cover lines 546, 553->555: async retry_on_result with listeners."""
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
        """Cover line 607: async fallback_used event with listeners."""
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


class TestSyncExecutorEdgeCases:
    def test_sync_circuit_breaker_success_closes(self) -> None:
        """Test sync circuit breaker closes on success after half-open."""
        events: list[ResilienceEvent] = []
        call_count = 0

        @resilient(
            circuit_breaker=CircuitBreakerConfig(
                failure_threshold=1, recovery_timeout=0.1, success_threshold=1
            ),
            listeners=[events.append],
        )
        def sometimes_fails() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("fail")
            return "ok"

        with pytest.raises(ValueError):
            sometimes_fails()

        time.sleep(0.15)
        result = sometimes_fails()
        assert result == "ok"
        event_types = [e.event_type for e in events]
        assert EventType.CIRCUIT_CLOSED in event_types

    def test_sync_failure_event_no_retry(self) -> None:
        """Test failure event when no retry configured."""
        events: list[ResilienceEvent] = []

        @resilient(
            fallback=FallbackConfig(handler="default", fallback_on=(TypeError,)),
            listeners=[events.append],
        )
        def fails() -> str:
            raise ValueError("fail")

        with pytest.raises(ValueError):
            fails()

        event_types = [e.event_type for e in events]
        assert EventType.FAILURE in event_types


class TestPresetsEdgeCoverage:
    def test_http_policy_with_rate_limit_and_cache(self) -> None:
        """Cover lines 94, 96 in _presets.py."""
        from pyresilience.presets import http_policy

        policy = http_policy(
            rate_limit=RateLimiterConfig(max_calls=100, period=1.0),
            cache=CacheConfig(max_size=100, ttl=30),
        )
        assert "rate_limiter" in policy
        assert "cache" in policy


class TestDjangoLoadConfig:
    def test_load_config_with_all_settings(self) -> None:
        """Cover django.py lines 70, 76, 78, 83."""
        from pyresilience.contrib.django import ResilientMiddleware

        mock_settings = mock.MagicMock()
        mock_settings.PYRESILIENCE_CONFIG = {
            "timeout_seconds": 15,
            "circuit_failure_threshold": 5,
            "circuit_recovery_seconds": 45,
            "max_retries": 3,
            "retry_delay": 0.5,
        }

        with (
            mock.patch("pyresilience.contrib.django.settings", mock_settings, create=True),
            mock.patch.dict(
                "sys.modules",
                {"django": mock.MagicMock(), "django.conf": mock.MagicMock()},
            ),
        ):
            import sys

            sys.modules["django.conf"].settings = mock_settings
            config = ResilientMiddleware._load_config()

        assert config.timeout is not None
        assert config.timeout.seconds == 15
        assert config.circuit_breaker is not None
        assert config.circuit_breaker.failure_threshold == 5
        assert config.retry is not None
        assert config.retry.max_attempts == 3


class TestFastapiMiddleware503:
    @pytest.mark.asyncio
    async def test_middleware_circuit_open_sends_503(self) -> None:
        """Cover fastapi.py lines 67-71, 76-83."""
        from pyresilience._types import CircuitBreakerConfig, ResilienceConfig
        from pyresilience.contrib.fastapi import ResilientMiddleware

        # Use a circuit breaker that will be open
        config = ResilienceConfig(
            circuit_breaker=CircuitBreakerConfig(failure_threshold=1, recovery_timeout=60),
        )

        call_count = 0

        async def failing_app(scope: dict, receive: object, send: object) -> None:
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        middleware = ResilientMiddleware(failing_app, config=config)

        sent_messages: list[dict] = []

        async def mock_send(msg: dict) -> None:
            sent_messages.append(msg)

        # First call opens circuit
        with pytest.raises(ValueError):
            await middleware({"type": "http"}, None, mock_send)

        # Second call hits open circuit → 503
        await middleware({"type": "http"}, None, mock_send)
        assert len(sent_messages) == 2
        assert sent_messages[0]["status"] == 503

    @pytest.mark.asyncio
    async def test_middleware_non_circuit_error_reraises(self) -> None:
        """Cover fastapi.py line 71: non-circuit RuntimeError re-raises."""
        from pyresilience.contrib.fastapi import ResilientMiddleware

        async def error_app(scope: dict, receive: object, send: object) -> None:
            raise RuntimeError("something else")

        middleware = ResilientMiddleware(error_app)

        with pytest.raises(RuntimeError, match="something else"):
            await middleware({"type": "http"}, None, None)


class TestLoggingLatencyTracking:
    def test_latency_tracked_on_retry_then_success(self) -> None:
        """Cover _logging.py line 145: latency tracking."""
        from pyresilience._logging import MetricsCollector

        metrics = MetricsCollector()
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01),
            listeners=[metrics],
        )
        def retry_then_succeed() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("fail")
            return "ok"

        retry_then_succeed()
        latencies = metrics.get_latencies()
        # Should have tracked latency for the successful call
        assert len(latencies) > 0


class TestMainModule:
    def test_main_as_script(self) -> None:
        """Cover __main__.py line 15."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "pyresilience"],
            capture_output=True,
            text=True,
        )
        assert "pyresilience" in result.stdout
