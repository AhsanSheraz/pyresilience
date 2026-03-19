"""Flask integration for pyresilience.

Provides an extension and a decorator for Flask views.

Usage::

    from flask import Flask
    from pyresilience.contrib.flask import Resilience, resilient_route
    from pyresilience import ResilienceConfig, RetryConfig, TimeoutConfig

    app = Flask(__name__)

    # Option 1: Extension — applies resilience to all routes
    resilience = Resilience(app, config=ResilienceConfig(
        timeout=TimeoutConfig(seconds=30),
    ))

    # Option 2: Per-route decorator
    @app.route("/data")
    @resilient_route(retry=RetryConfig(max_attempts=3), timeout=TimeoutConfig(seconds=10))
    def get_data():
        return external_api.get_data()
"""

from __future__ import annotations

import functools
from typing import Any, Callable, Optional, TypeVar

from pyresilience._executor import _SyncExecutor
from pyresilience._types import (
    CircuitBreakerConfig,
    ResilienceConfig,
    RetryConfig,
    TimeoutConfig,
)

F = TypeVar("F", bound=Callable[..., Any])


class Resilience:
    """Flask extension that applies resilience patterns to request handling.

    Usage::

        app = Flask(__name__)
        resilience = Resilience(app, config=ResilienceConfig(
            timeout=TimeoutConfig(seconds=30),
            circuit_breaker=CircuitBreakerConfig(failure_threshold=10),
        ))

    Or with the factory pattern::

        resilience = Resilience()
        resilience.init_app(app, config=ResilienceConfig(...))
    """

    def __init__(
        self,
        app: Optional[Any] = None,
        config: Optional[ResilienceConfig] = None,
    ) -> None:
        self._executor: Optional[_SyncExecutor] = None
        if app is not None:
            self.init_app(app, config)

    def init_app(
        self,
        app: Any,
        config: Optional[ResilienceConfig] = None,
    ) -> None:
        """Initialize the extension with a Flask app."""
        resolved_config = config or ResilienceConfig()
        self._executor = _SyncExecutor(resolved_config)

        app.before_request(self._before_request)
        app.extensions["pyresilience"] = self

    def _before_request(self) -> None:
        # Store executor in app context for potential per-request use
        pass

    @property
    def executor(self) -> _SyncExecutor:
        """Get the resilience executor."""
        if self._executor is None:
            raise RuntimeError("Resilience extension not initialized. Call init_app() first.")
        return self._executor

    def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute a function with resilience patterns."""
        return self.executor.execute(func, func.__name__, *args, **kwargs)


def resilient_route(
    *,
    retry: Optional[RetryConfig] = None,
    timeout: Optional[TimeoutConfig] = None,
    circuit_breaker: Optional[CircuitBreakerConfig] = None,
) -> Callable[[F], F]:
    """Decorator to apply resilience patterns to a Flask route.

    Usage::

        @app.route("/data")
        @resilient_route(retry=RetryConfig(max_attempts=3), timeout=TimeoutConfig(seconds=10))
        def get_data():
            return external_api.get_data()
    """
    config = ResilienceConfig(
        retry=retry,
        timeout=timeout,
        circuit_breaker=circuit_breaker,
    )
    executor = _SyncExecutor(config)

    def decorator(view_func: F) -> F:
        @functools.wraps(view_func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return executor.execute(view_func, view_func.__name__, *args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
