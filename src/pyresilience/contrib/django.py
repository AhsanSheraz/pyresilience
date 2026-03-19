"""Django integration for pyresilience.

Provides middleware and a decorator for Django views.

Usage::

    # settings.py
    MIDDLEWARE = [
        ...
        'pyresilience.contrib.django.ResilientMiddleware',
    ]
    PYRESILIENCE_CONFIG = {
        'timeout_seconds': 30,
        'circuit_failure_threshold': 10,
        'circuit_recovery_seconds': 60,
    }

    # views.py
    from pyresilience.contrib.django import resilient_view
    from pyresilience import RetryConfig, TimeoutConfig

    @resilient_view(retry=RetryConfig(max_attempts=3), timeout=TimeoutConfig(seconds=10))
    def my_view(request):
        return JsonResponse(external_api.get_data())
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


class ResilientMiddleware:
    """Django middleware that wraps view execution with resilience patterns.

    Configure via Django settings::

        PYRESILIENCE_CONFIG = {
            'timeout_seconds': 30,
            'circuit_failure_threshold': 10,
            'circuit_recovery_seconds': 60,
        }
    """

    def __init__(self, get_response: Callable[..., Any]) -> None:
        self.get_response = get_response
        self._executor: Optional[_SyncExecutor] = None

    def _get_executor(self) -> _SyncExecutor:
        if self._executor is None:
            config = self._load_config()
            self._executor = _SyncExecutor(config)
        return self._executor

    @staticmethod
    def _load_config() -> ResilienceConfig:
        try:
            from django.conf import settings  # type: ignore[import-not-found]

            user_config = getattr(settings, "PYRESILIENCE_CONFIG", {})
        except ImportError:
            user_config = {}

        config = ResilienceConfig()
        if "timeout_seconds" in user_config:
            config.timeout = TimeoutConfig(seconds=user_config["timeout_seconds"])
        if "circuit_failure_threshold" in user_config:
            config.circuit_breaker = CircuitBreakerConfig(
                failure_threshold=user_config["circuit_failure_threshold"],
                recovery_timeout=user_config.get("circuit_recovery_seconds", 30.0),
            )
        if "max_attempts" in user_config:
            config.retry = RetryConfig(
                max_attempts=user_config["max_attempts"],
                delay=user_config.get("retry_delay", 1.0),
            )
        elif "max_retries" in user_config:
            import warnings

            warnings.warn(
                "PYRESILIENCE_CONFIG key 'max_retries' is deprecated, use 'max_attempts' instead",
                DeprecationWarning,
                stacklevel=2,
            )
            config.retry = RetryConfig(
                max_attempts=user_config["max_retries"],
                delay=user_config.get("retry_delay", 1.0),
            )
        return config

    def __call__(self, request: Any) -> Any:
        executor = self._get_executor()
        return executor.execute(self.get_response, self.get_response.__name__, request)


def resilient_view(
    *,
    retry: Optional[RetryConfig] = None,
    timeout: Optional[TimeoutConfig] = None,
    circuit_breaker: Optional[CircuitBreakerConfig] = None,
) -> Callable[[F], F]:
    """Decorator to apply resilience patterns to a Django view.

    Usage::

        @resilient_view(retry=RetryConfig(max_attempts=3), timeout=TimeoutConfig(seconds=10))
        def my_view(request):
            data = external_api.get_data()
            return JsonResponse(data)
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
