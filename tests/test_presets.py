"""Tests for dependency-specific resilience presets."""

from __future__ import annotations

import pytest

from pyresilience import (
    FallbackConfig,
    ResilienceEvent,
    db_policy,
    http_policy,
    queue_policy,
    resilient,
    strict_policy,
)


class TestHttpPolicy:
    def test_default_http_policy(self) -> None:
        policy = http_policy()
        assert "retry" in policy
        assert "timeout" in policy
        assert "circuit_breaker" in policy
        assert policy["timeout"].seconds == 10.0
        assert policy["retry"].max_attempts == 3

    def test_http_policy_custom(self) -> None:
        policy = http_policy(timeout_seconds=5.0, max_attempts=5, max_concurrent=20)
        assert policy["timeout"].seconds == 5.0
        assert policy["retry"].max_attempts == 5
        assert "bulkhead" in policy
        assert policy["bulkhead"].max_concurrent == 20

    def test_http_policy_with_fallback(self) -> None:
        fb = FallbackConfig(handler={"cached": True})
        policy = http_policy(fallback=fb)
        assert policy["fallback"] is fb

    def test_http_policy_with_listeners(self) -> None:
        events: list[ResilienceEvent] = []
        policy = http_policy(listeners=[events.append])
        assert len(policy["listeners"]) == 1

    def test_http_policy_with_retry_on(self) -> None:
        policy = http_policy(retry_on=[ValueError, ConnectionError])
        assert ValueError in policy["retry"].retry_on
        assert ConnectionError in policy["retry"].retry_on

    def test_http_policy_applied(self) -> None:
        call_count = 0

        @resilient(**http_policy(timeout_seconds=5, max_attempts=2, retry_delay=0.01))
        def api_call() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("timeout")
            return "ok"

        assert api_call() == "ok"
        assert call_count == 2


class TestDbPolicy:
    def test_default_db_policy(self) -> None:
        policy = db_policy()
        assert policy["timeout"].seconds == 30.0
        assert policy["retry"].max_attempts == 2
        assert policy["bulkhead"].max_concurrent == 10
        assert policy["circuit_breaker"].failure_threshold == 3

    def test_db_policy_custom(self) -> None:
        policy = db_policy(max_concurrent=5, timeout_seconds=60.0)
        assert policy["bulkhead"].max_concurrent == 5
        assert policy["timeout"].seconds == 60.0

    def test_db_policy_applied(self) -> None:
        @resilient(**db_policy(timeout_seconds=5, max_attempts=1, retry_delay=0.01))
        def query() -> str:
            return "result"

        assert query() == "result"


class TestQueuePolicy:
    def test_default_queue_policy(self) -> None:
        policy = queue_policy()
        assert policy["timeout"].seconds == 15.0
        assert policy["retry"].max_attempts == 5
        assert policy["retry"].delay == 2.0
        assert policy["circuit_breaker"].failure_threshold == 10

    def test_queue_policy_with_bulkhead(self) -> None:
        policy = queue_policy(max_concurrent=50)
        assert "bulkhead" in policy
        assert policy["bulkhead"].max_concurrent == 50

    def test_queue_policy_applied(self) -> None:
        @resilient(**queue_policy(timeout_seconds=5, max_attempts=2, retry_delay=0.01))
        def publish() -> str:
            return "sent"

        assert publish() == "sent"


class TestStrictPolicy:
    def test_default_strict_policy(self) -> None:
        policy = strict_policy()
        assert policy["timeout"].seconds == 5.0
        assert policy["retry"].max_attempts == 1
        assert policy["retry"].jitter is False
        assert policy["circuit_breaker"].failure_threshold == 3

    def test_strict_policy_applied(self) -> None:
        @resilient(**strict_policy(timeout_seconds=5))
        def fast_call() -> str:
            return "fast"

        assert fast_call() == "fast"

    def test_strict_policy_fails_fast(self) -> None:
        @resilient(**strict_policy(timeout_seconds=5))
        def always_fails() -> str:
            raise ValueError("fail")

        with pytest.raises(ValueError, match="fail"):
            always_fails()


class TestPresetEdgeCases:
    def test_db_policy_with_fallback_and_listeners(self) -> None:
        events: list[ResilienceEvent] = []
        fb = FallbackConfig(handler="cached")
        policy = db_policy(fallback=fb, listeners=[events.append])
        assert policy["fallback"] is fb
        assert len(policy["listeners"]) == 1

    def test_queue_policy_with_fallback_and_listeners(self) -> None:
        events: list[ResilienceEvent] = []
        fb = FallbackConfig(handler="queued")
        policy = queue_policy(fallback=fb, listeners=[events.append], max_concurrent=100)
        assert policy["fallback"] is fb
        assert policy["bulkhead"].max_concurrent == 100

    def test_strict_policy_with_listeners(self) -> None:
        events: list[ResilienceEvent] = []
        policy = strict_policy(listeners=[events.append])
        assert len(policy["listeners"]) == 1

    def test_db_policy_with_retry_on(self) -> None:
        policy = db_policy(retry_on=[ConnectionError])
        assert ConnectionError in policy["retry"].retry_on

    def test_queue_policy_with_retry_on(self) -> None:
        policy = queue_policy(retry_on=[TimeoutError])
        assert TimeoutError in policy["retry"].retry_on


class TestPresetAsync:
    @pytest.mark.asyncio
    async def test_async_http_policy(self) -> None:
        @resilient(**http_policy(timeout_seconds=5, max_attempts=1, retry_delay=0.01))
        async def async_api_call() -> str:
            return "async ok"

        assert await async_api_call() == "async ok"

    @pytest.mark.asyncio
    async def test_async_db_policy(self) -> None:
        @resilient(**db_policy(timeout_seconds=5, max_attempts=1, retry_delay=0.01))
        async def async_query() -> str:
            return "async result"

        assert await async_query() == "async result"


class TestStrictPolicyDocAccuracy:
    def test_strict_policy_default_is_one_attempt(self) -> None:
        """Verify strict_policy default max_attempts=1 means no retries."""
        policy = strict_policy()
        assert policy["retry"].max_attempts == 1


class TestPresetsEdgeCoverage:
    def test_http_policy_with_rate_limit_and_cache(self) -> None:
        """Test http_policy with rate_limit and cache options."""
        from pyresilience import CacheConfig, RateLimiterConfig
        from pyresilience.presets import http_policy

        policy = http_policy(
            rate_limit=RateLimiterConfig(max_calls=100, period=1.0),
            cache=CacheConfig(max_size=100, ttl=30),
        )
        assert "rate_limiter" in policy
        assert "cache" in policy
