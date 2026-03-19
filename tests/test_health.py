"""Tests for health check utilities."""

from __future__ import annotations

import pytest

from pyresilience import ResilienceRegistry
from pyresilience._health import health_check
from pyresilience._types import (
    CircuitBreakerConfig,
    ResilienceConfig,
    RetryConfig,
)


class TestHealthCheck:
    def test_empty_registry_returns_empty_dict(self) -> None:
        """health_check returns empty dict when no configs are registered."""
        registry = ResilienceRegistry()
        assert health_check(registry) == {}

    def test_no_circuit_breaker_returns_empty_dict(self) -> None:
        """health_check returns empty dict when configs have no circuit breakers."""
        registry = ResilienceRegistry()
        registry.register("api", ResilienceConfig(retry=RetryConfig(max_attempts=3)))

        @registry.decorator("api")
        def my_func() -> str:
            return "ok"

        my_func()
        assert health_check(registry) == {}

    def test_returns_circuit_breaker_state(self) -> None:
        """health_check returns circuit breaker state for registered functions."""
        registry = ResilienceRegistry()
        registry.register(
            "api",
            ResilienceConfig(
                circuit_breaker=CircuitBreakerConfig(failure_threshold=3, recovery_timeout=60.0),
            ),
        )

        @registry.decorator("api")
        def my_func() -> str:
            return "ok"

        my_func()  # Trigger executor creation
        status = health_check(registry)
        assert "api" in status
        assert status["api"]["circuit_breaker"]["state"] == "closed"
        assert status["api"]["circuit_breaker"]["failure_count"] == 0

    def test_state_changes_after_failures(self) -> None:
        """Circuit breaker state changes are reflected in health_check output."""
        registry = ResilienceRegistry()
        registry.register(
            "api",
            ResilienceConfig(
                circuit_breaker=CircuitBreakerConfig(failure_threshold=2, recovery_timeout=60.0),
            ),
        )

        @registry.decorator("api")
        def my_func() -> str:
            raise ValueError("fail")

        # Trigger failures to open the circuit
        with pytest.raises(ValueError):
            my_func()
        with pytest.raises(ValueError):
            my_func()

        status = health_check(registry)
        assert "api" in status
        assert status["api"]["circuit_breaker"]["state"] == "open"

    def test_no_executor_created_returns_empty(self) -> None:
        """If a config is registered but no function decorated/called, no executor exists."""
        registry = ResilienceRegistry()
        registry.register(
            "api",
            ResilienceConfig(
                circuit_breaker=CircuitBreakerConfig(failure_threshold=3),
            ),
        )
        # No decorator call, so no executor is created
        status = health_check(registry)
        assert status == {}

    def test_multiple_registrations(self) -> None:
        """health_check reports state for multiple registered circuit breakers."""
        registry = ResilienceRegistry()
        registry.register(
            "api-a",
            ResilienceConfig(
                circuit_breaker=CircuitBreakerConfig(failure_threshold=2, recovery_timeout=60.0),
            ),
        )
        registry.register(
            "api-b",
            ResilienceConfig(
                circuit_breaker=CircuitBreakerConfig(failure_threshold=5, recovery_timeout=60.0),
            ),
        )

        @registry.decorator("api-a")
        def func_a() -> str:
            return "ok"

        @registry.decorator("api-b")
        def func_b() -> str:
            return "ok"

        func_a()
        func_b()

        status = health_check(registry)
        assert "api-a" in status
        assert "api-b" in status
        assert status["api-a"]["circuit_breaker"]["state"] == "closed"
        assert status["api-b"]["circuit_breaker"]["state"] == "closed"


class TestHealthCheckAsync:
    @pytest.mark.asyncio
    async def test_async_circuit_breaker_state(self) -> None:
        """health_check works with async decorated functions."""
        registry = ResilienceRegistry()
        registry.register(
            "async-api",
            ResilienceConfig(
                circuit_breaker=CircuitBreakerConfig(failure_threshold=3, recovery_timeout=60.0),
            ),
        )

        @registry.decorator("async-api")
        async def my_func() -> str:
            return "ok"

        await my_func()

        status = health_check(registry)
        assert "async-api" in status
        assert status["async-api"]["circuit_breaker"]["state"] == "closed"
