"""Core resilience executor — orchestrates all patterns."""

from __future__ import annotations

import asyncio
import contextlib
import random
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional, TypeVar

from pyresilience._bulkhead import AsyncBulkhead, Bulkhead, BulkheadFullError
from pyresilience._cache import _SENTINEL, AsyncResultCache, ResultCache
from pyresilience._circuit_breaker import CircuitBreaker
from pyresilience._rate_limiter import AsyncRateLimiter, RateLimiter, RateLimitExceededError
from pyresilience._types import (
    CircuitBreakerConfig,
    CircuitState,
    EventType,
    FallbackConfig,
    ResilienceConfig,
    ResilienceEvent,
    ResilienceListener,
    RetryConfig,
)

F = TypeVar("F", bound=Callable[..., Any])

# Shared thread pool for sync timeouts
_timeout_pool = ThreadPoolExecutor(max_workers=4)


def _emit(
    listeners: list[ResilienceListener],
    event_type: EventType,
    func_name: str,
    attempt: int = 0,
    error: Optional[BaseException] = None,
    detail: str = "",
) -> None:
    event = ResilienceEvent(
        event_type=event_type,
        function_name=func_name,
        attempt=attempt,
        error=error,
        detail=detail,
    )
    for listener in listeners:
        with contextlib.suppress(Exception):
            listener(event)


def _compute_delay(config: RetryConfig, attempt: int) -> float:
    delay = config.delay * (config.backoff_factor ** (attempt - 1))
    delay = min(delay, config.max_delay)
    if config.jitter:
        delay = delay * (0.5 + random.random() * 0.5)
    return delay


def _is_retryable(exc: BaseException, config: RetryConfig) -> bool:
    return isinstance(exc, tuple(config.retry_on))


def _is_circuit_error(exc: BaseException, config: CircuitBreakerConfig) -> bool:
    return isinstance(exc, tuple(config.error_types))


def _is_fallback_error(exc: BaseException, config: FallbackConfig) -> bool:
    return isinstance(exc, tuple(config.fallback_on))


def _apply_fallback(config: FallbackConfig, exc: BaseException) -> Any:
    handler = config.handler
    if callable(handler):
        return handler(exc)
    return handler


class _SyncExecutor:
    """Executes a sync function with resilience patterns."""

    def __init__(self, config: ResilienceConfig) -> None:
        self.config = config
        self.circuit_breaker: Optional[CircuitBreaker] = None
        self.bulkhead: Optional[Bulkhead] = None
        self.rate_limiter: Optional[RateLimiter] = None
        self.cache: Optional[ResultCache] = None

        if config.circuit_breaker:
            self.circuit_breaker = CircuitBreaker(config.circuit_breaker)
        if config.bulkhead:
            self.bulkhead = Bulkhead(config.bulkhead)
        if config.rate_limiter:
            self.rate_limiter = RateLimiter(config.rate_limiter)
        if config.cache:
            self.cache = ResultCache(config.cache)

    def execute(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        func_name = getattr(func, "__name__", str(func))
        listeners = self.config.listeners

        # Cache check
        cache_key: Optional[str] = None
        if self.cache:
            cache_key = ResultCache.make_key(*args, **kwargs)
            cached = self.cache.get(cache_key)
            if cached is not _SENTINEL:
                _emit(listeners, EventType.CACHE_HIT, func_name)
                return cached
            _emit(listeners, EventType.CACHE_MISS, func_name)

        # Circuit breaker check
        if self.circuit_breaker and not self.circuit_breaker.allow_request():
            _emit(listeners, EventType.CIRCUIT_OPEN, func_name)
            if self.config.fallback:
                _emit(listeners, EventType.FALLBACK_USED, func_name)
                exc = RuntimeError("Circuit breaker is open")
                return _apply_fallback(self.config.fallback, exc)
            raise RuntimeError("Circuit breaker is open")

        # Rate limiter check
        if self.rate_limiter and not self.rate_limiter.acquire():
            _emit(listeners, EventType.RATE_LIMITED, func_name)
            if self.config.fallback:
                _emit(listeners, EventType.FALLBACK_USED, func_name)
                return _apply_fallback(
                    self.config.fallback, RateLimitExceededError("Rate limit exceeded")
                )
            raise RateLimitExceededError("Rate limit exceeded")

        # Bulkhead acquire
        if self.bulkhead and not self.bulkhead.acquire():
            _emit(listeners, EventType.BULKHEAD_REJECTED, func_name)
            if self.config.fallback:
                _emit(listeners, EventType.FALLBACK_USED, func_name)
                return _apply_fallback(self.config.fallback, BulkheadFullError("Bulkhead full"))
            raise BulkheadFullError("Bulkhead full")

        try:
            result = self._execute_with_retry(func, func_name, listeners, *args, **kwargs)
            # Store in cache on success
            if self.cache and cache_key is not None:
                self.cache.put(cache_key, result)
            return result
        finally:
            if self.bulkhead:
                self.bulkhead.release()

    def _execute_with_retry(
        self,
        func: Callable[..., Any],
        func_name: str,
        listeners: list[ResilienceListener],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        retry_cfg = self.config.retry
        max_attempts = retry_cfg.max_attempts if retry_cfg else 1
        last_exc: Optional[BaseException] = None

        for attempt in range(1, max_attempts + 1):
            try:
                result = self._execute_once(func, func_name, listeners, *args, **kwargs)

                # Record circuit breaker success
                if self.circuit_breaker:
                    new_state = self.circuit_breaker.record_success()
                    if new_state == CircuitState.CLOSED:
                        _emit(listeners, EventType.CIRCUIT_CLOSED, func_name)

                _emit(listeners, EventType.SUCCESS, func_name, attempt=attempt)
                return result

            except BaseException as exc:
                last_exc = exc

                # Record circuit breaker failure
                if (
                    self.circuit_breaker
                    and self.config.circuit_breaker
                    and _is_circuit_error(exc, self.config.circuit_breaker)
                ):
                    new_state = self.circuit_breaker.record_failure()
                    if new_state == CircuitState.OPEN:
                        _emit(listeners, EventType.CIRCUIT_OPEN, func_name, error=exc)

                # Check if retryable
                if retry_cfg and attempt < max_attempts and _is_retryable(exc, retry_cfg):
                    delay = _compute_delay(retry_cfg, attempt)
                    _emit(
                        listeners,
                        EventType.RETRY,
                        func_name,
                        attempt=attempt,
                        error=exc,
                        detail=f"retrying in {delay:.2f}s",
                    )
                    time.sleep(delay)
                    continue

                # Exhausted retries or not retryable
                if retry_cfg and attempt >= max_attempts:
                    _emit(
                        listeners,
                        EventType.RETRY_EXHAUSTED,
                        func_name,
                        attempt=attempt,
                        error=exc,
                    )

                # Try fallback
                if self.config.fallback and _is_fallback_error(exc, self.config.fallback):
                    _emit(listeners, EventType.FALLBACK_USED, func_name, error=exc)
                    return _apply_fallback(self.config.fallback, exc)

                _emit(listeners, EventType.FAILURE, func_name, error=exc)
                raise

        # Should not reach here, but satisfy type checker
        if last_exc:
            raise last_exc
        raise RuntimeError("Unexpected state in retry loop")  # pragma: no cover

    def _execute_once(
        self,
        func: Callable[..., Any],
        func_name: str,
        listeners: list[ResilienceListener],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        timeout_cfg = self.config.timeout
        if not timeout_cfg:
            return func(*args, **kwargs)

        # Run with timeout using a thread pool
        import concurrent.futures

        future = _timeout_pool.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout_cfg.seconds)
        except (TimeoutError, concurrent.futures.TimeoutError):
            future.cancel()
            _emit(
                listeners,
                EventType.TIMEOUT,
                func_name,
                detail=f"exceeded {timeout_cfg.seconds}s",
            )
            raise TimeoutError(f"{func_name} exceeded timeout of {timeout_cfg.seconds}s") from None


class _AsyncExecutor:
    """Executes an async function with resilience patterns."""

    def __init__(self, config: ResilienceConfig) -> None:
        self.config = config
        self.circuit_breaker: Optional[CircuitBreaker] = None
        self.bulkhead: Optional[AsyncBulkhead] = None
        self.rate_limiter: Optional[AsyncRateLimiter] = None
        self.cache: Optional[AsyncResultCache] = None

        if config.circuit_breaker:
            self.circuit_breaker = CircuitBreaker(config.circuit_breaker)
        if config.bulkhead:
            self.bulkhead = AsyncBulkhead(config.bulkhead)
        if config.rate_limiter:
            self.rate_limiter = AsyncRateLimiter(config.rate_limiter)
        if config.cache:
            self.cache = AsyncResultCache(config.cache)

    async def execute(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        func_name = getattr(func, "__name__", str(func))
        listeners = self.config.listeners

        # Cache check
        cache_key: Optional[str] = None
        if self.cache:
            cache_key = AsyncResultCache.make_key(*args, **kwargs)
            cached = self.cache.get(cache_key)
            if cached is not _SENTINEL:
                _emit(listeners, EventType.CACHE_HIT, func_name)
                return cached
            _emit(listeners, EventType.CACHE_MISS, func_name)

        # Circuit breaker check
        if self.circuit_breaker and not self.circuit_breaker.allow_request():
            _emit(listeners, EventType.CIRCUIT_OPEN, func_name)
            if self.config.fallback:
                _emit(listeners, EventType.FALLBACK_USED, func_name)
                exc = RuntimeError("Circuit breaker is open")
                return _apply_fallback(self.config.fallback, exc)
            raise RuntimeError("Circuit breaker is open")

        # Rate limiter check
        if self.rate_limiter:
            acquired = await self.rate_limiter.acquire()
            if not acquired:
                _emit(listeners, EventType.RATE_LIMITED, func_name)
                if self.config.fallback:
                    _emit(listeners, EventType.FALLBACK_USED, func_name)
                    return _apply_fallback(
                        self.config.fallback, RateLimitExceededError("Rate limit exceeded")
                    )
                raise RateLimitExceededError("Rate limit exceeded")

        # Bulkhead acquire
        if self.bulkhead:
            acquired = await self.bulkhead.acquire()
            if not acquired:
                _emit(listeners, EventType.BULKHEAD_REJECTED, func_name)
                if self.config.fallback:
                    _emit(listeners, EventType.FALLBACK_USED, func_name)
                    return _apply_fallback(self.config.fallback, BulkheadFullError("Bulkhead full"))
                raise BulkheadFullError("Bulkhead full")

        try:
            result = await self._execute_with_retry(func, func_name, listeners, *args, **kwargs)
            # Store in cache on success
            if self.cache and cache_key is not None:
                self.cache.put(cache_key, result)
            return result
        finally:
            if self.bulkhead:
                self.bulkhead.release()

    async def _execute_with_retry(
        self,
        func: Callable[..., Any],
        func_name: str,
        listeners: list[ResilienceListener],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        retry_cfg = self.config.retry
        max_attempts = retry_cfg.max_attempts if retry_cfg else 1
        last_exc: Optional[BaseException] = None

        for attempt in range(1, max_attempts + 1):
            try:
                result = await self._execute_once(func, func_name, listeners, *args, **kwargs)

                if self.circuit_breaker:
                    new_state = self.circuit_breaker.record_success()
                    if new_state == CircuitState.CLOSED:
                        _emit(listeners, EventType.CIRCUIT_CLOSED, func_name)

                _emit(listeners, EventType.SUCCESS, func_name, attempt=attempt)
                return result

            except BaseException as exc:
                last_exc = exc

                if (
                    self.circuit_breaker
                    and self.config.circuit_breaker
                    and _is_circuit_error(exc, self.config.circuit_breaker)
                ):
                    new_state = self.circuit_breaker.record_failure()
                    if new_state == CircuitState.OPEN:
                        _emit(listeners, EventType.CIRCUIT_OPEN, func_name, error=exc)

                if retry_cfg and attempt < max_attempts and _is_retryable(exc, retry_cfg):
                    delay = _compute_delay(retry_cfg, attempt)
                    _emit(
                        listeners,
                        EventType.RETRY,
                        func_name,
                        attempt=attempt,
                        error=exc,
                        detail=f"retrying in {delay:.2f}s",
                    )
                    await asyncio.sleep(delay)
                    continue

                if retry_cfg and attempt >= max_attempts:
                    _emit(
                        listeners,
                        EventType.RETRY_EXHAUSTED,
                        func_name,
                        attempt=attempt,
                        error=exc,
                    )

                if self.config.fallback and _is_fallback_error(exc, self.config.fallback):
                    _emit(listeners, EventType.FALLBACK_USED, func_name, error=exc)
                    return _apply_fallback(self.config.fallback, exc)

                _emit(listeners, EventType.FAILURE, func_name, error=exc)
                raise

        if last_exc:
            raise last_exc
        raise RuntimeError("Unexpected state in retry loop")  # pragma: no cover

    async def _execute_once(
        self,
        func: Callable[..., Any],
        func_name: str,
        listeners: list[ResilienceListener],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        timeout_cfg = self.config.timeout
        if not timeout_cfg:
            return await func(*args, **kwargs)

        try:
            return await asyncio.wait_for(func(*args, **kwargs), timeout=timeout_cfg.seconds)
        except asyncio.TimeoutError:
            _emit(
                listeners,
                EventType.TIMEOUT,
                func_name,
                detail=f"exceeded {timeout_cfg.seconds}s",
            )
            raise TimeoutError(f"{func_name} exceeded timeout of {timeout_cfg.seconds}s") from None
