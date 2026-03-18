"""The @resilient decorator — the main public API."""

from __future__ import annotations

import asyncio
import functools
from typing import Any, Callable, Optional, TypeVar, overload

from pyresilience._executor import _AsyncExecutor, _SyncExecutor
from pyresilience._types import (
    BulkheadConfig,
    CircuitBreakerConfig,
    FallbackConfig,
    ResilienceConfig,
    ResilienceListener,
    RetryConfig,
    TimeoutConfig,
)

F = TypeVar("F", bound=Callable[..., Any])


@overload
def resilient(func: F) -> F: ...


@overload
def resilient(
    *,
    retry: Optional[RetryConfig] = ...,
    timeout: Optional[TimeoutConfig] = ...,
    circuit_breaker: Optional[CircuitBreakerConfig] = ...,
    fallback: Optional[FallbackConfig] = ...,
    bulkhead: Optional[BulkheadConfig] = ...,
    listeners: Optional[list[ResilienceListener]] = ...,
) -> Callable[[F], F]: ...


def resilient(
    func: Optional[F] = None,
    *,
    retry: Optional[RetryConfig] = None,
    timeout: Optional[TimeoutConfig] = None,
    circuit_breaker: Optional[CircuitBreakerConfig] = None,
    fallback: Optional[FallbackConfig] = None,
    bulkhead: Optional[BulkheadConfig] = None,
    listeners: Optional[list[ResilienceListener]] = None,
) -> Any:
    """Decorator that applies resilience patterns to a function.

    Can be used with or without arguments:

        @resilient
        def my_func(): ...

        @resilient(retry=RetryConfig(max_attempts=5), timeout=TimeoutConfig(seconds=10))
        def my_func(): ...

        @resilient(retry=RetryConfig(), circuit_breaker=CircuitBreakerConfig())
        async def my_async_func(): ...

    Args:
        retry: Retry configuration. Pass RetryConfig() for defaults.
        timeout: Timeout configuration. Pass TimeoutConfig() for defaults.
        circuit_breaker: Circuit breaker configuration.
        fallback: Fallback configuration for graceful degradation.
        bulkhead: Bulkhead configuration for concurrency limiting.
        listeners: List of callbacks to receive resilience events.
    """
    config = ResilienceConfig(
        retry=retry,
        timeout=timeout,
        circuit_breaker=circuit_breaker,
        fallback=fallback,
        bulkhead=bulkhead,
        listeners=listeners or [],
    )

    def decorator(fn: F) -> F:
        if asyncio.iscoroutinefunction(fn):
            executor = _AsyncExecutor(config)

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                return await executor.execute(fn, *args, **kwargs)

            return async_wrapper  # type: ignore[return-value]
        else:
            executor_sync = _SyncExecutor(config)

            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                return executor_sync.execute(fn, *args, **kwargs)

            return sync_wrapper  # type: ignore[return-value]

    if func is not None:
        # Used as @resilient without arguments — apply default retry
        config.retry = config.retry or RetryConfig()
        return decorator(func)

    return decorator
