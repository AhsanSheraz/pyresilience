"""Tests for dependency-specific resilience presets."""

from __future__ import annotations

import pytest

from pyresilience import (
    FallbackConfig,
    ResilienceEvent,
    db_policy,
    http_policy,
    llm_policy,
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


class TestLlmPolicy:
    def test_default_llm_policy_shape(self) -> None:
        policy = llm_policy()
        # Should have exactly 4 base keys: retry, timeout, circuit_breaker, rate_limiter
        assert "retry" in policy
        assert "timeout" in policy
        assert "circuit_breaker" in policy
        assert "rate_limiter" in policy
        # Default has no bulkhead, fallback, or listeners
        assert "bulkhead" not in policy
        assert "fallback" not in policy
        assert "listeners" not in policy

    def test_default_llm_policy_values(self) -> None:
        policy = llm_policy()
        assert policy["timeout"].seconds == 60.0
        assert policy["retry"].max_attempts == 4
        assert policy["retry"].delay == 1.0
        assert policy["retry"].max_delay == 60.0
        assert policy["rate_limiter"].max_calls == 60
        assert policy["rate_limiter"].period == 60.0
        assert policy["circuit_breaker"].failure_threshold == 5
        assert policy["circuit_breaker"].recovery_timeout == 30.0

    def test_retry_on_result_with_status_code(self) -> None:
        policy = llm_policy()
        # Create a fake response object with status_code attribute
        response = type("R", (), {"status_code": 429})()
        assert policy["retry"].retry_on_result is not None
        assert policy["retry"].retry_on_result(response) is True
        # Non-matching status code should return False
        response_ok = type("R", (), {"status_code": 200})()
        assert policy["retry"].retry_on_result(response_ok) is False

    def test_custom_retry_on_status_codes(self) -> None:
        policy = llm_policy(retry_on_status_codes=(429, 503))
        response_429 = type("R", (), {"status_code": 429})()
        response_503 = type("R", (), {"status_code": 503})()
        response_500 = type("R", (), {"status_code": 500})()
        assert policy["retry"].retry_on_result(response_429) is True
        assert policy["retry"].retry_on_result(response_503) is True
        assert policy["retry"].retry_on_result(response_500) is False

    def test_delay_func_with_retry_after_header(self) -> None:
        policy = llm_policy()
        delay_func = policy["retry"].delay_func
        assert delay_func is not None
        # Create a fake response with Retry-After header
        response = type("R", (), {"headers": {"Retry-After": "7"}})()
        delay = delay_func(1, response)
        assert delay == 7.0

    def test_delay_func_clamps_to_max_wait(self) -> None:
        policy = llm_policy(retry_after_max_wait=60.0)
        delay_func = policy["retry"].delay_func
        assert delay_func is not None
        # Create a response with a very large Retry-After value
        response = type("R", (), {"headers": {"Retry-After": "999999"}})()
        delay = delay_func(1, response)
        # Should be clamped to max_wait (60.0)
        assert delay == 60.0

    def test_ignore_on_default_empty(self) -> None:
        policy = llm_policy()
        assert policy["retry"].ignore_on == ()
        assert policy["circuit_breaker"].ignore_on == ()

    def test_ignore_on_propagates_to_both_retry_and_circuit_breaker(self) -> None:
        policy = llm_policy(ignore_on=[ValueError])
        assert ValueError in policy["retry"].ignore_on
        assert ValueError in policy["circuit_breaker"].ignore_on

    def test_ignore_on_with_multiple_exceptions(self) -> None:
        policy = llm_policy(ignore_on=[ValueError, TypeError])
        assert ValueError in policy["retry"].ignore_on
        assert TypeError in policy["retry"].ignore_on
        assert ValueError in policy["circuit_breaker"].ignore_on
        assert TypeError in policy["circuit_breaker"].ignore_on

    def test_max_concurrent_adds_bulkhead(self) -> None:
        policy = llm_policy(max_concurrent=5)
        assert "bulkhead" in policy
        assert policy["bulkhead"].max_concurrent == 5

    def test_retry_on_custom_exception(self) -> None:
        policy = llm_policy(retry_on=[ConnectionError])
        assert policy["retry"].retry_on == (ConnectionError,)

    def test_llm_policy_integration_sync(self) -> None:
        call_count = 0

        @resilient(
            **llm_policy(
                timeout_seconds=5,
                max_attempts=2,
                retry_delay=0.01,
                max_calls=1000,
                period=1.0,
                retry_after_max_wait=1.0,
            )
        )
        def llm_call() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("network issue")
            return "ok"

        assert llm_call() == "ok"
        assert call_count == 2

    def test_llm_policy_with_fallback(self) -> None:
        fb = FallbackConfig(handler="fallback_response")
        policy = llm_policy(fallback=fb)
        assert policy["fallback"] is fb

    def test_llm_policy_with_listeners(self) -> None:
        events: list[ResilienceEvent] = []
        policy = llm_policy(listeners=[events.append])
        assert len(policy["listeners"]) == 1


class TestLlmPolicyAsync:
    async def test_llm_policy_integration_async(self) -> None:
        call_count = 0

        @resilient(
            **llm_policy(
                timeout_seconds=5,
                max_attempts=2,
                retry_delay=0.01,
                max_calls=1000,
                period=1.0,
                retry_after_max_wait=1.0,
            )
        )
        async def async_llm_call() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("network issue")
            return "ok"

        result = await async_llm_call()
        assert result == "ok"
        assert call_count == 2
