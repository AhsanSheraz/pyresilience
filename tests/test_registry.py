"""Tests for resilience registry."""

from __future__ import annotations

import pytest

from pyresilience._registry import ResilienceRegistry
from pyresilience._types import (
    CircuitBreakerConfig,
    ResilienceConfig,
    RetryConfig,
    TimeoutConfig,
)


class TestResilienceRegistry:
    def test_register_and_get(self) -> None:
        registry = ResilienceRegistry()
        config = ResilienceConfig(retry=RetryConfig(max_attempts=5))
        registry.register("api", config)
        assert registry.get("api") is config

    def test_get_returns_none_for_missing(self) -> None:
        registry = ResilienceRegistry()
        assert registry.get("missing") is None

    def test_get_or_default(self) -> None:
        registry = ResilienceRegistry()
        default = ResilienceConfig(retry=RetryConfig())
        registry.set_default(default)
        assert registry.get_or_default("missing") is default

    def test_get_or_default_raises_without_default(self) -> None:
        registry = ResilienceRegistry()
        with pytest.raises(KeyError, match="No config registered"):
            registry.get_or_default("missing")

    def test_get_or_default_prefers_registered(self) -> None:
        registry = ResilienceRegistry()
        default = ResilienceConfig(retry=RetryConfig())
        specific = ResilienceConfig(retry=RetryConfig(max_attempts=10))
        registry.set_default(default)
        registry.register("api", specific)
        assert registry.get_or_default("api") is specific

    def test_names(self) -> None:
        registry = ResilienceRegistry()
        registry.register("api", ResilienceConfig())
        registry.register("db", ResilienceConfig())
        assert sorted(registry.names) == ["api", "db"]

    def test_unregister(self) -> None:
        registry = ResilienceRegistry()
        registry.register("api", ResilienceConfig())
        assert registry.unregister("api") is True
        assert registry.get("api") is None
        assert registry.unregister("api") is False

    def test_clear(self) -> None:
        registry = ResilienceRegistry()
        registry.register("api", ResilienceConfig())
        registry.set_default(ResilienceConfig())
        registry.clear()
        assert registry.names == []
        with pytest.raises(KeyError):
            registry.get_or_default("api")

    def test_register_overwrites(self) -> None:
        registry = ResilienceRegistry()
        config1 = ResilienceConfig(retry=RetryConfig(max_attempts=1))
        config2 = ResilienceConfig(retry=RetryConfig(max_attempts=5))
        registry.register("api", config1)
        registry.register("api", config2)
        assert registry.get("api") is config2


class TestRegistryDecorator:
    def test_sync_decorator(self) -> None:
        registry = ResilienceRegistry()
        registry.register("api", ResilienceConfig(retry=RetryConfig(max_attempts=1)))

        @registry.decorator("api")
        def my_func() -> str:
            return "ok"

        assert my_func() == "ok"

    async def test_async_decorator(self) -> None:
        registry = ResilienceRegistry()
        registry.register("api", ResilienceConfig(retry=RetryConfig(max_attempts=1)))

        @registry.decorator("api")
        async def my_func() -> str:
            return "ok"

        assert await my_func() == "ok"

    def test_shared_circuit_breaker(self) -> None:
        registry = ResilienceRegistry()
        registry.register(
            "api",
            ResilienceConfig(
                circuit_breaker=CircuitBreakerConfig(failure_threshold=2, recovery_timeout=60.0),
            ),
        )

        call_count_a = 0
        call_count_b = 0

        @registry.decorator("api")
        def func_a() -> str:
            nonlocal call_count_a
            call_count_a += 1
            raise ValueError("fail")

        @registry.decorator("api")
        def func_b() -> str:
            nonlocal call_count_b
            call_count_b += 1
            return "ok"

        # func_a and func_b share the same executor (same circuit breaker)
        with pytest.raises(ValueError):
            func_a()
        with pytest.raises(ValueError):
            func_a()

        # Circuit should now be open for both
        with pytest.raises(RuntimeError, match="Circuit breaker is open"):
            func_b()

    def test_decorator_with_default_config(self) -> None:
        registry = ResilienceRegistry()
        registry.set_default(ResilienceConfig(timeout=TimeoutConfig(seconds=30.0)))

        @registry.decorator("unregistered")
        def my_func() -> str:
            return "ok"

        assert my_func() == "ok"

    def test_decorator_preserves_function_name(self) -> None:
        registry = ResilienceRegistry()
        registry.register("api", ResilienceConfig())

        @registry.decorator("api")
        def my_special_func() -> str:
            return "ok"

        assert my_special_func.__name__ == "my_special_func"

    async def test_async_decorator_preserves_function_name(self) -> None:
        registry = ResilienceRegistry()
        registry.register("api", ResilienceConfig())

        @registry.decorator("api")
        async def my_async_func() -> str:
            return "ok"

        assert my_async_func.__name__ == "my_async_func"
