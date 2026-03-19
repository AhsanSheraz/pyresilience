"""FastAPI integration for pyresilience.

Provides middleware and dependency injection for FastAPI applications.

Usage::

    from fastapi import FastAPI
    from pyresilience.contrib.fastapi import ResilientMiddleware, resilient_dependency
    from pyresilience import RetryConfig, CircuitBreakerConfig, ResilienceConfig

    app = FastAPI()

    # Option 1: Middleware — applies resilience to all routes
    app.add_middleware(
        ResilientMiddleware,
        config=ResilienceConfig(
            timeout=TimeoutConfig(seconds=30),
            circuit_breaker=CircuitBreakerConfig(failure_threshold=10),
        ),
    )

    # Option 2: Dependency injection — per-route resilience
    payment_resilience = resilient_dependency(ResilienceConfig(
        retry=RetryConfig(max_attempts=3),
        circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
    ))

    @app.get("/charge")
    async def charge(resilience=Depends(payment_resilience)):
        return await resilience.execute(payment_service.charge)
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from pyresilience._executor import _AsyncExecutor
from pyresilience._types import ResilienceConfig


class ResilientMiddleware:
    """ASGI middleware that wraps request handling with resilience patterns.

    This middleware applies resilience patterns (timeout, circuit breaker, etc.)
    to the entire request handling pipeline.

    Args:
        app: The ASGI application.
        config: Resilience configuration to apply.
    """

    def __init__(self, app: Any, config: Optional[ResilienceConfig] = None) -> None:
        self.app = app
        self.config = config or ResilienceConfig()
        self.executor = _AsyncExecutor(self.config)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def _handle() -> None:
            await self.app(scope, receive, send)

        try:
            await self.executor.execute(_handle)
        except RuntimeError as exc:
            if "circuit breaker is open" in str(exc).lower():
                await self._send_503(send)
            else:
                raise

    @staticmethod
    async def _send_503(send: Any) -> None:
        """Send a 503 Service Unavailable response."""
        await send({
            "type": "http.response.start",
            "status": 503,
            "headers": [[b"content-type", b"application/json"]],
        })
        await send({
            "type": "http.response.body",
            "body": b'{"detail":"Service temporarily unavailable"}',
        })


class ResilientDependency:
    """FastAPI dependency that provides a resilience executor.

    Use with FastAPI's Depends() for per-route resilience configuration.

    Usage::

        dep = ResilientDependency(ResilienceConfig(...))

        @app.get("/endpoint")
        async def my_endpoint(resilience: ResilientDependency = Depends(dep)):
            return await resilience.call(my_service_function, arg1, arg2)
    """

    def __init__(self, config: ResilienceConfig) -> None:
        self.config = config
        self._executor = _AsyncExecutor(config)

    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute a function with the configured resilience patterns."""
        return await self._executor.execute(func, *args, **kwargs)

    async def __call__(self) -> ResilientDependency:
        """FastAPI dependency protocol — returns self."""
        return self


def resilient_dependency(config: ResilienceConfig) -> ResilientDependency:
    """Create a FastAPI dependency with the given resilience config.

    Usage::

        from fastapi import Depends, FastAPI
        from pyresilience import ResilienceConfig, RetryConfig
        from pyresilience.contrib.fastapi import resilient_dependency

        app = FastAPI()
        payment_dep = resilient_dependency(ResilienceConfig(
            retry=RetryConfig(max_attempts=3),
        ))

        @app.post("/charge")
        async def charge(resilience=Depends(payment_dep)):
            return await resilience.call(payment_service.charge, amount=100)
    """
    return ResilientDependency(config)
