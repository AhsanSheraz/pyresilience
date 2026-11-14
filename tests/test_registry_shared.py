"""Tests for state shared by sync and async functions under one registry name."""

from __future__ import annotations

import pytest

from pyresilience import (
    CircuitBreakerConfig,
    CircuitOpenError,
    FallbackConfig,
    RateLimit,
    RateLimiterConfig,
    RateLimitExceededError,
    ResilienceConfig,
    ResilienceRegistry,
    RetryBudgetConfig,
    RetryConfig,
)

LONG = 3600.0


def _registry(config: ResilienceConfig) -> ResilienceRegistry:
    registry = ResilienceRegistry()
    registry.register("svc", config)
    return registry


class TestRegistrySharesStateAcrossCallStyles:
    async def test_circuit_breaker_is_shared(self) -> None:
        registry = _registry(
            ResilienceConfig(
                circuit_breaker=CircuitBreakerConfig(failure_threshold=2, recovery_timeout=60.0)
            )
        )

        @registry.decorator("svc")
        def sync_call() -> str:
            raise ConnectionError("down")

        @registry.decorator("svc")
        async def async_call() -> str:
            return "ok"

        for _ in range(2):
            with pytest.raises(ConnectionError):
                sync_call()
        # The sync function opened the circuit; the async function is blocked too
        with pytest.raises(CircuitOpenError):
            await async_call()
        assert (
            sync_call._executor._circuit_breaker  # type: ignore[attr-defined]
            is async_call._executor._circuit_breaker  # type: ignore[attr-defined]
        )

    async def test_plain_rate_limit_is_shared(self) -> None:
        registry = _registry(
            ResilienceConfig(rate_limiter=RateLimiterConfig(max_calls=3, period=LONG))
        )

        @registry.decorator("svc")
        def sync_call() -> str:
            return "sync"

        @registry.decorator("svc")
        async def async_call() -> str:
            return "async"

        assert sync_call() == "sync"
        assert await async_call() == "async"
        assert sync_call() == "sync"
        with pytest.raises(RateLimitExceededError):
            await async_call()
        with pytest.raises(RateLimitExceededError):
            sync_call()

    async def test_plain_rate_limit_waits_on_the_shared_bucket(self) -> None:
        registry = _registry(
            ResilienceConfig(rate_limiter=RateLimiterConfig(max_calls=1, period=0.1, max_wait=2.0))
        )

        @registry.decorator("svc")
        def sync_call() -> str:
            return "sync"

        @registry.decorator("svc")
        async def async_call() -> str:
            return "async"

        assert sync_call() == "sync"
        # The bucket is empty; the async caller waits for the refill
        assert await async_call() == "async"

    async def test_plain_rate_limit_wait_can_time_out(self) -> None:
        registry = _registry(
            ResilienceConfig(
                rate_limiter=RateLimiterConfig(max_calls=1, period=LONG, max_wait=0.05)
            )
        )

        @registry.decorator("svc")
        def sync_call() -> str:
            return "sync"

        @registry.decorator("svc")
        async def async_call() -> str:
            return "async"

        sync_call()
        with pytest.raises(RateLimitExceededError):
            await async_call()

    async def test_reset_reaches_the_shared_bucket(self) -> None:
        registry = _registry(
            ResilienceConfig(rate_limiter=RateLimiterConfig(max_calls=1, period=LONG))
        )

        @registry.decorator("svc")
        def sync_call() -> str:
            return "sync"

        @registry.decorator("svc")
        async def async_call() -> str:
            return "async"

        sync_call()
        async_call._executor._rate_limiter.reset()  # type: ignore[attr-defined]
        assert sync_call() == "sync"

    async def test_weighted_rate_limit_is_shared(self) -> None:
        registry = _registry(
            ResilienceConfig(
                rate_limiter=RateLimiterConfig(
                    max_calls=10,
                    period=LONG,
                    limits=[RateLimit(100, LONG, name="tokens", cost=lambda prompt: len(prompt))],
                )
            )
        )

        @registry.decorator("svc")
        def sync_call(prompt: str) -> str:
            return prompt

        @registry.decorator("svc")
        async def async_call(prompt: str) -> str:
            return prompt

        sync_call("x" * 60)
        with pytest.raises(RateLimitExceededError, match="tokens"):
            await async_call("x" * 60)
        assert await async_call("x" * 30) == "x" * 30

    async def test_retry_budget_is_shared(self) -> None:
        registry = _registry(
            ResilienceConfig(
                retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
                retry_budget=RetryBudgetConfig(max_retries=2, refill_rate=0.0001),
            )
        )
        sync_attempts = 0
        async_attempts = 0

        @registry.decorator("svc")
        def sync_call() -> str:
            nonlocal sync_attempts
            sync_attempts += 1
            raise ConnectionError("down")

        @registry.decorator("svc")
        async def async_call() -> str:
            nonlocal async_attempts
            async_attempts += 1
            raise ConnectionError("down")

        with pytest.raises(ConnectionError):
            sync_call()
        assert sync_attempts == 3  # spent both retries of the shared budget
        with pytest.raises(ConnectionError):
            await async_call()
        assert async_attempts == 1  # nothing left for the async function

    async def test_fallback_cooldown_is_shared(self) -> None:
        def backup(prompt: str) -> str:
            return f"backup: {prompt}"

        registry = _registry(
            ResilienceConfig(fallback=FallbackConfig(alternatives=[backup], cooldown=30.0))
        )
        async_attempts = 0

        @registry.decorator("svc")
        def sync_call(prompt: str) -> str:
            raise ConnectionError("down")

        @registry.decorator("svc")
        async def async_call(prompt: str) -> str:
            nonlocal async_attempts
            async_attempts += 1
            return "primary"

        assert sync_call("one") == "backup: one"
        # The sync failure started the cooldown of the shared primary target
        assert await async_call("two") == "backup: two"
        assert async_attempts == 0

    def test_two_names_do_not_share_state(self) -> None:
        registry = ResilienceRegistry()
        config = ResilienceConfig(rate_limiter=RateLimiterConfig(max_calls=1, period=LONG))
        registry.register("a", config)
        registry.register("b", config)

        @registry.decorator("a")
        def call_a() -> str:
            return "a"

        @registry.decorator("b")
        def call_b() -> str:
            return "b"

        assert call_a() == "a"
        assert call_b() == "b"


class TestRegistryDropsState:
    def test_register_again_rebuilds_executors_and_state(self) -> None:
        registry = _registry(
            ResilienceConfig(rate_limiter=RateLimiterConfig(max_calls=1, period=LONG))
        )

        @registry.decorator("svc")
        def first() -> str:
            return "ok"

        first()
        with pytest.raises(RateLimitExceededError):
            first()

        registry.register(
            "svc", ResilienceConfig(rate_limiter=RateLimiterConfig(max_calls=5, period=LONG))
        )
        assert registry.get_executor("svc") is None

        @registry.decorator("svc")
        def second() -> str:
            return "ok"

        for _ in range(5):
            assert second() == "ok"

    def test_unregister_drops_state(self) -> None:
        registry = _registry(
            ResilienceConfig(rate_limiter=RateLimiterConfig(max_calls=1, period=LONG))
        )

        @registry.decorator("svc")
        def call() -> str:
            return "ok"

        call()
        assert registry.unregister("svc") is True
        assert registry.get_executor("svc") is None
        assert registry._parts == {}

    def test_clear_drops_state(self) -> None:
        registry = _registry(
            ResilienceConfig(rate_limiter=RateLimiterConfig(max_calls=1, period=LONG))
        )

        @registry.decorator("svc")
        def call() -> str:
            return "ok"

        call()
        registry.clear()
        assert registry._parts == {}
        assert registry.names == []
