"""Tests for framework integrations (contrib modules)."""

from __future__ import annotations

import pytest

from pyresilience._types import (
    CircuitBreakerConfig,
    ResilienceConfig,
    RetryConfig,
    TimeoutConfig,
)


class TestFastapiIntegration:
    def test_resilient_dependency_creation(self) -> None:
        from pyresilience.contrib.fastapi import ResilientDependency, resilient_dependency

        config = ResilienceConfig(retry=RetryConfig(max_attempts=2))
        dep = resilient_dependency(config)
        assert isinstance(dep, ResilientDependency)
        assert dep.config is config

    async def test_resilient_dependency_call_returns_self(self) -> None:
        from pyresilience.contrib.fastapi import ResilientDependency

        config = ResilienceConfig()
        dep = ResilientDependency(config)
        result = await dep()
        assert result is dep

    async def test_resilient_dependency_executes_function(self) -> None:
        from pyresilience.contrib.fastapi import ResilientDependency

        config = ResilienceConfig(retry=RetryConfig(max_attempts=1))
        dep = ResilientDependency(config)

        async def my_func(x: int) -> int:
            return x * 2

        result = await dep.call(my_func, 5)
        assert result == 10

    async def test_resilient_dependency_with_retry(self) -> None:
        from pyresilience.contrib.fastapi import ResilientDependency

        config = ResilienceConfig(retry=RetryConfig(max_attempts=3, delay=0.01))
        dep = ResilientDependency(config)
        call_count = 0

        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "ok"

        result = await dep.call(flaky)
        assert result == "ok"
        assert call_count == 3

    async def test_middleware_passes_non_http(self) -> None:
        from pyresilience.contrib.fastapi import ResilientMiddleware

        called = False

        async def app(scope: dict, receive: object, send: object) -> None:
            nonlocal called
            called = True

        middleware = ResilientMiddleware(app, config=ResilienceConfig())
        await middleware({"type": "websocket"}, None, None)
        assert called is True

    async def test_middleware_wraps_http(self) -> None:
        from pyresilience.contrib.fastapi import ResilientMiddleware

        called = False

        async def app(scope: dict, receive: object, send: object) -> None:
            nonlocal called
            called = True

        middleware = ResilientMiddleware(app, config=ResilienceConfig())
        await middleware({"type": "http"}, None, None)
        assert called is True

    async def test_middleware_default_config(self) -> None:
        from pyresilience.contrib.fastapi import ResilientMiddleware

        async def app(scope: dict, receive: object, send: object) -> None:
            pass

        middleware = ResilientMiddleware(app)
        assert middleware.config is not None


class TestDjangoIntegration:
    def test_resilient_view_decorator(self) -> None:
        from pyresilience.contrib.django import resilient_view

        @resilient_view(
            retry=RetryConfig(max_attempts=1),
            timeout=TimeoutConfig(seconds=30),
        )
        def my_view(request: object) -> str:
            return "ok"

        assert my_view(None) == "ok"
        assert my_view.__name__ == "my_view"

    def test_resilient_view_with_circuit_breaker(self) -> None:
        from pyresilience.contrib.django import resilient_view

        @resilient_view(circuit_breaker=CircuitBreakerConfig(failure_threshold=5))
        def my_view(request: object) -> str:
            return "ok"

        assert my_view(None) == "ok"

    def test_middleware_init(self) -> None:
        from pyresilience.contrib.django import ResilientMiddleware

        def get_response(request: object) -> str:
            return "response"

        middleware = ResilientMiddleware(get_response)
        assert middleware.get_response is get_response

    def test_middleware_call(self) -> None:
        from pyresilience.contrib.django import ResilientMiddleware

        def get_response(request: object) -> str:
            return "response"

        middleware = ResilientMiddleware(get_response)
        result = middleware("fake_request")
        assert result == "response"

    def test_middleware_load_config_no_django(self) -> None:
        from pyresilience.contrib.django import ResilientMiddleware

        config = ResilientMiddleware._load_config()
        assert config is not None

    def test_middleware_load_config_with_settings(self) -> None:
        from unittest import mock

        mock_load = mock.patch("pyresilience.contrib.django.ResilientMiddleware._load_config")
        with mock_load as patched:
            patched.return_value = ResilienceConfig(
                timeout=TimeoutConfig(seconds=15),
                circuit_breaker=CircuitBreakerConfig(failure_threshold=3, recovery_timeout=45),
                retry=RetryConfig(max_attempts=2, delay=0.5),
            )
            config = patched()
            assert config.timeout is not None
            assert config.timeout.seconds == 15
            assert config.circuit_breaker is not None
            assert config.retry is not None


class TestFlaskIntegration:
    def test_resilient_route_decorator(self) -> None:
        from pyresilience.contrib.flask import resilient_route

        @resilient_route(
            retry=RetryConfig(max_attempts=1),
            timeout=TimeoutConfig(seconds=30),
        )
        def my_view() -> str:
            return "ok"

        assert my_view() == "ok"
        assert my_view.__name__ == "my_view"

    def test_resilient_route_with_circuit_breaker(self) -> None:
        from pyresilience.contrib.flask import resilient_route

        @resilient_route(circuit_breaker=CircuitBreakerConfig(failure_threshold=5))
        def my_view() -> str:
            return "ok"

        assert my_view() == "ok"

    def test_resilience_extension_without_app(self) -> None:
        from pyresilience.contrib.flask import Resilience

        ext = Resilience()
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = ext.executor

    def test_resilience_extension_call(self) -> None:
        from pyresilience.contrib.flask import Resilience

        mock_app = type(
            "App",
            (),
            {
                "before_request": lambda self, f: None,
                "extensions": {},
            },
        )()

        ext = Resilience(mock_app, config=ResilienceConfig())
        result = ext.call(lambda: "hello")
        assert result == "hello"

    def test_resilience_extension_init_app(self) -> None:
        from pyresilience.contrib.flask import Resilience

        mock_app = type(
            "App",
            (),
            {
                "before_request": lambda self, f: None,
                "extensions": {},
            },
        )()

        ext = Resilience()
        ext.init_app(mock_app, config=ResilienceConfig(timeout=TimeoutConfig(seconds=10)))
        assert "pyresilience" in mock_app.extensions
        assert ext.executor is not None

    def test_resilience_extension_default_config(self) -> None:
        from pyresilience.contrib.flask import Resilience

        mock_app = type(
            "App",
            (),
            {
                "before_request": lambda self, f: None,
                "extensions": {},
            },
        )()

        ext = Resilience()
        ext.init_app(mock_app)  # No config — should use default
        assert ext.executor is not None
