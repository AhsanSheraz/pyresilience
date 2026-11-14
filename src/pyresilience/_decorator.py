"""The @resilient decorator — the main public API."""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, Optional, TypeVar, overload

from pyresilience._executor import _AsyncExecutor, _SyncExecutor
from pyresilience._types import (
    BulkheadConfig,
    CacheConfig,
    CircuitBreakerConfig,
    FallbackConfig,
    RateLimiterConfig,
    ResilienceConfig,
    ResilienceListener,
    RetryBudgetConfig,
    RetryConfig,
    SharedStateConfig,
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
    rate_limiter: Optional[RateLimiterConfig] = ...,
    cache: Optional[CacheConfig] = ...,
    retry_budget: Optional[RetryBudgetConfig] = ...,
    listeners: Optional[list[ResilienceListener]] = ...,
    shared_state: Optional[SharedStateConfig] = ...,
) -> Callable[[F], F]: ...


def resilient(
    func: Optional[F] = None,
    *,
    retry: Optional[RetryConfig] = None,
    timeout: Optional[TimeoutConfig] = None,
    circuit_breaker: Optional[CircuitBreakerConfig] = None,
    fallback: Optional[FallbackConfig] = None,
    bulkhead: Optional[BulkheadConfig] = None,
    rate_limiter: Optional[RateLimiterConfig] = None,
    cache: Optional[CacheConfig] = None,
    retry_budget: Optional[RetryBudgetConfig] = None,
    listeners: Optional[list[ResilienceListener]] = None,
    shared_state: Optional[SharedStateConfig] = None,
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
        rate_limiter: Rate limiter configuration for call rate limiting.
        cache: Cache configuration for result caching.
        retry_budget: Global retry budget configuration.
        listeners: List of callbacks to receive resilience events.
        shared_state: Share circuit breaker, rate limit and retry budget state
            between processes through a state backend.
    """
    config = ResilienceConfig(
        retry=retry,
        timeout=timeout,
        circuit_breaker=circuit_breaker,
        fallback=fallback,
        bulkhead=bulkhead,
        rate_limiter=rate_limiter,
        cache=cache,
        retry_budget=retry_budget,
        listeners=listeners or [],
        shared_state=shared_state,
    )

    def decorator(fn: F) -> F:
        fn_name = fn.__name__
        # Default name of this function's state in a shared backend
        state_key = f"{fn.__module__}.{fn.__qualname__}"
        if inspect.iscoroutinefunction(fn):
            executor = _AsyncExecutor(config, state_key=state_key)

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                return await executor.execute(fn, fn_name, *args, **kwargs)

            async_wrapper._executor = executor  # type: ignore[attr-defined]
            return async_wrapper  # type: ignore[return-value]
        else:
            executor_sync = _SyncExecutor(config, state_key=state_key)

            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                return executor_sync.execute(fn, fn_name, *args, **kwargs)

            sync_wrapper._executor = executor_sync  # type: ignore[attr-defined]
            return sync_wrapper  # type: ignore[return-value]

    if func is not None:
        # Used as @resilient without arguments — pass through with no patterns
        return decorator(func)

    return decorator
