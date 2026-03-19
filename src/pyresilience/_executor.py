"""Core resilience executor — orchestrates all patterns.

Performance-critical module. Key optimizations:
- Pre-cache config lookups as instance attributes at init time
- Inline isinstance() calls instead of helper function dispatch
- Guard event emission with bool check to skip _emit overhead
- Cache frequently-accessed attributes as locals in hot loops
- Use shared thread pool by default, custom pool only when configured
"""

from __future__ import annotations

import asyncio
import atexit
import ctypes
import logging
import os
import random
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Callable, Optional, Type

from pyresilience._bulkhead import AsyncBulkhead, Bulkhead
from pyresilience._cache import _SENTINEL, AsyncResultCache, ResultCache
from pyresilience._circuit_breaker import CircuitBreaker
from pyresilience._exceptions import (
    BulkheadFullError,
    CircuitOpenError,
    ResilienceTimeoutError,
)
from pyresilience._logging import _call_id_counter, call_id_var
from pyresilience._rate_limiter import AsyncRateLimiter, RateLimiter, RateLimitExceededError
from pyresilience._types import (
    CircuitState,
    EventType,
    FallbackConfig,
    ResilienceConfig,
    ResilienceEvent,
    ResilienceListener,
    RetryConfig,
)

# Module-level logger for listener error reporting
_logger = logging.getLogger("pyresilience")

# Shared thread pool for sync timeouts — sized like Python 3.13's default
_default_timeout_pool = ThreadPoolExecutor(max_workers=min(32, (os.cpu_count() or 1) + 4))

# Track custom pools for cleanup at exit
_custom_pools: list[weakref.ref[ThreadPoolExecutor]] = []


def _register_custom_pool(pool: ThreadPoolExecutor) -> None:
    _custom_pools.append(weakref.ref(pool))


def _shutdown_pools() -> None:
    for ref in _custom_pools:
        pool = ref()
        if pool is not None:
            pool.shutdown(wait=False)
    _custom_pools.clear()


atexit.register(_shutdown_pools)

# Cache random.random locally to avoid attribute lookup in hot path
_random = random.random

# Best-effort thread cancellation support (CPython only)
_HAS_ASYNC_EXC = hasattr(ctypes, "pythonapi")
if _HAS_ASYNC_EXC:
    ctypes.pythonapi.PyThreadState_SetAsyncExc.argtypes = [ctypes.c_ulong, ctypes.py_object]
    ctypes.pythonapi.PyThreadState_SetAsyncExc.restype = ctypes.c_int


def _interrupt_thread(thread_id: int) -> bool:
    """Best-effort interrupt of a running thread by raising ResilienceTimeoutError.

    CPython-only. The exception is raised at the next Python bytecode boundary.
    Will NOT interrupt blocking C extensions (e.g., time.sleep, socket.recv).
    Returns True if the exception was successfully scheduled.
    """
    if not _HAS_ASYNC_EXC:
        return False
    try:
        ret: int = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_ulong(thread_id),
            ctypes.py_object(ResilienceTimeoutError),
        )
        if ret > 1:
            # Affected more than one thread state — clear to prevent corruption
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(thread_id), None)
            return False
        return ret == 1
    except Exception:
        return False


def _emit(
    listeners: list[ResilienceListener],
    event_type: EventType,
    func_name: str,
    attempt: int = 0,
    error: Optional[BaseException] = None,
    detail: str = "",
) -> None:
    """Emit an event to all listeners. No-op when listeners list is empty."""
    event = ResilienceEvent(
        event_type=event_type,
        function_name=func_name,
        attempt=attempt,
        error=error,
        detail=detail,
    )
    for listener in listeners:
        try:
            listener(event)
        except Exception:
            _logger.warning("Listener %r raised an exception", listener, exc_info=True)


def _compute_delay(retry_cfg: RetryConfig, attempt: int) -> float:
    """Calculate retry delay with exponential backoff and optional jitter.

    When jitter is enabled, the delay is randomized but never falls below 10%
    of the base (pre-jitter) delay. This prevents zero-delay retry storms.
    """
    delay = retry_cfg.delay * (retry_cfg.backoff_factor ** (attempt - 1))
    if delay > retry_cfg.max_delay:
        delay = retry_cfg.max_delay
    if retry_cfg.jitter:
        base_delay = delay
        delay = max(base_delay * 0.1, _random() * delay)
    return delay


def _apply_fallback(fallback_cfg: FallbackConfig, exc: BaseException) -> Any:
    """Apply fallback handler or return static fallback value."""
    handler = fallback_cfg.handler
    if callable(handler):
        return handler(exc)
    return handler


async def _apply_fallback_async(fallback_cfg: FallbackConfig, exc: BaseException) -> Any:
    """Apply fallback handler with async support.

    If the handler is an async function, awaits it. Otherwise, calls it synchronously.
    """
    handler = fallback_cfg.handler
    if callable(handler):
        if asyncio.iscoroutinefunction(handler):
            return await handler(exc)
        return handler(exc)
    return handler


class _SyncExecutor:
    """Executes a sync function with resilience patterns.

    All config is resolved once at __init__ and stored as instance attrs
    to minimize per-call overhead.
    """

    __slots__ = (
        "_bulkhead",
        "_cache",
        "_circuit_breaker",
        "_circuit_error_types",
        "_fallback_cfg",
        "_fallback_on",
        "_fast_path",
        "_has_listeners",
        "_has_timeout",
        "_listeners",
        "_max_attempts",
        "_rate_limiter",
        "_retry_cfg",
        "_retry_on",
        "_retry_on_result",
        "_slow_call_duration",
        "_timeout_pool",
        "_timeout_seconds",
    )

    def __init__(self, config: ResilienceConfig) -> None:
        self._listeners = list(config.listeners)
        self._has_listeners = bool(self._listeners)

        # Pre-cache tuples for isinstance checks (avoids per-call list→tuple conversion)
        self._retry_on: tuple[Type[BaseException], ...] = (
            tuple(config.retry.retry_on) if config.retry else ()
        )
        self._circuit_error_types: tuple[Type[BaseException], ...] = (
            tuple(config.circuit_breaker.error_types) if config.circuit_breaker else ()
        )
        self._fallback_on: tuple[Type[BaseException], ...] = (
            tuple(config.fallback.fallback_on) if config.fallback else ()
        )
        self._retry_cfg = config.retry
        self._fallback_cfg = config.fallback
        self._max_attempts = config.retry.max_attempts if config.retry else 1
        self._has_timeout = config.timeout is not None
        self._timeout_seconds = config.timeout.seconds if config.timeout else 0.0
        self._retry_on_result = config.retry.retry_on_result if config.retry else None
        self._slow_call_duration = (
            config.circuit_breaker.slow_call_duration if config.circuit_breaker else 0.0
        )
        # Fast path: skip retry loop when no retry, no timeout, no slow call tracking
        self._fast_path = (
            config.retry is None and config.timeout is None and self._slow_call_duration == 0.0
        )

        # Share global pool unless custom pool_size is configured
        _default_pool_size = min(32, (os.cpu_count() or 1) + 4)
        if config.timeout and config.timeout.pool_size != _default_pool_size:
            pool = ThreadPoolExecutor(max_workers=config.timeout.pool_size)
            self._timeout_pool: ThreadPoolExecutor = pool
            _register_custom_pool(pool)
        else:
            self._timeout_pool = _default_timeout_pool

        self._circuit_breaker: Optional[CircuitBreaker] = (
            CircuitBreaker(config.circuit_breaker) if config.circuit_breaker else None
        )
        self._bulkhead: Optional[Bulkhead] = Bulkhead(config.bulkhead) if config.bulkhead else None
        self._rate_limiter: Optional[RateLimiter] = (
            RateLimiter(config.rate_limiter) if config.rate_limiter else None
        )
        self._cache: Optional[ResultCache] = ResultCache(config.cache) if config.cache else None

    def execute(self, func: Callable[..., Any], func_name: str, *args: Any, **kwargs: Any) -> Any:
        # Set unique call ID for MetricsCollector latency tracking
        call_id_var.set(next(_call_id_counter))

        listeners = self._listeners
        has_listeners = self._has_listeners
        fallback_cfg = self._fallback_cfg
        cache = self._cache

        # Cache check — fast path for repeated calls
        cache_key: Any = None
        cache_key_lock: Optional[threading.Lock] = None
        if cache is not None:
            cache_key = ResultCache.make_key(*args, **kwargs)
            cached = cache.get(cache_key)
            if cached is not _SENTINEL:
                if has_listeners:
                    _emit(listeners, EventType.CACHE_HIT, func_name)
                return cached
            if has_listeners:
                _emit(listeners, EventType.CACHE_MISS, func_name)
            # Stampede prevention: per-key lock ensures only one thread computes
            cache_key_lock = cache.get_key_lock(cache_key)
            cache_key_lock.acquire()
            # Double-check: another thread may have cached the value while we waited
            cached = cache.get(cache_key)
            if cached is not _SENTINEL:
                cache_key_lock.release()
                cache_key_lock = None
                if has_listeners:
                    _emit(listeners, EventType.CACHE_HIT, func_name)
                return cached

        try:
            # Circuit breaker — reject immediately when open
            circuit_breaker = self._circuit_breaker
            if circuit_breaker is not None and not circuit_breaker.allow_request():
                if has_listeners:
                    _emit(listeners, EventType.CIRCUIT_OPEN, func_name)
                if fallback_cfg is not None:
                    if has_listeners:
                        _emit(listeners, EventType.FALLBACK_USED, func_name)
                    return _apply_fallback(
                        fallback_cfg, CircuitOpenError("Circuit breaker is open")
                    )
                raise CircuitOpenError("Circuit breaker is open")

            # Rate limiter
            rate_limiter = self._rate_limiter
            if rate_limiter is not None and not rate_limiter.acquire():
                if has_listeners:
                    _emit(listeners, EventType.RATE_LIMITED, func_name)
                if fallback_cfg is not None:
                    if has_listeners:
                        _emit(listeners, EventType.FALLBACK_USED, func_name)
                    return _apply_fallback(
                        fallback_cfg, RateLimitExceededError("Rate limit exceeded")
                    )
                raise RateLimitExceededError("Rate limit exceeded")

            # Bulkhead
            bulkhead = self._bulkhead
            if bulkhead is not None and not bulkhead.acquire():
                if has_listeners:
                    _emit(listeners, EventType.BULKHEAD_REJECTED, func_name)
                if fallback_cfg is not None:
                    if has_listeners:
                        _emit(listeners, EventType.FALLBACK_USED, func_name)
                    return _apply_fallback(fallback_cfg, BulkheadFullError("Bulkhead full"))
                raise BulkheadFullError("Bulkhead full")

            # Track whether we currently hold the bulkhead slot
            bulkhead_held = [bulkhead is not None]

            try:
                # Fast path: no retry, no timeout — direct call
                if self._fast_path:
                    result = self._execute_direct(
                        func, func_name, listeners, has_listeners, circuit_breaker, *args, **kwargs
                    )
                else:
                    result = self._execute_with_retry(
                        func,
                        func_name,
                        listeners,
                        has_listeners,
                        circuit_breaker,
                        bulkhead,
                        bulkhead_held,
                        *args,
                        **kwargs,
                    )
                if cache is not None and cache_key is not None:
                    cache.put(cache_key, result)
                return result
            finally:
                if bulkhead_held[0]:
                    bulkhead.release()  # type: ignore[union-attr]
        finally:
            if cache_key_lock is not None:
                cache_key_lock.release()

    def _execute_direct(
        self,
        func: Callable[..., Any],
        func_name: str,
        listeners: list[ResilienceListener],
        has_listeners: bool,
        circuit_breaker: Optional[CircuitBreaker],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Fast path: single execution with no retry loop overhead."""
        fallback_on = self._fallback_on
        fallback_cfg = self._fallback_cfg
        try:
            result = func(*args, **kwargs)
            if circuit_breaker is not None:
                prev_state, new_state = circuit_breaker.record_success_atomic(0.0)
                if (
                    new_state == CircuitState.CLOSED
                    and prev_state != CircuitState.CLOSED
                    and has_listeners
                ):
                    _emit(listeners, EventType.CIRCUIT_CLOSED, func_name)
            if has_listeners:
                _emit(listeners, EventType.SUCCESS, func_name, attempt=1)
            return result
        except Exception as exc:
            if circuit_breaker is not None and isinstance(exc, self._circuit_error_types):
                new_state = circuit_breaker.record_failure(0.0)
                if new_state == CircuitState.OPEN and has_listeners:
                    _emit(listeners, EventType.CIRCUIT_OPEN, func_name, error=exc)
            if fallback_cfg is not None and isinstance(exc, fallback_on):
                if has_listeners:
                    _emit(listeners, EventType.FALLBACK_USED, func_name, error=exc)
                return _apply_fallback(fallback_cfg, exc)
            if has_listeners:
                _emit(listeners, EventType.FAILURE, func_name, error=exc)
            raise

    def _execute_with_retry(
        self,
        func: Callable[..., Any],
        func_name: str,
        listeners: list[ResilienceListener],
        has_listeners: bool,
        circuit_breaker: Optional[CircuitBreaker],
        bulkhead: Optional[Bulkhead],
        bulkhead_held: list[bool],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        retry_cfg = self._retry_cfg
        max_attempts = self._max_attempts
        retry_on = self._retry_on
        circuit_error_types = self._circuit_error_types
        fallback_on = self._fallback_on
        fallback_cfg = self._fallback_cfg
        has_timeout = self._has_timeout
        retry_on_result = self._retry_on_result
        slow_call_duration = self._slow_call_duration
        track_duration = circuit_breaker is not None and slow_call_duration > 0
        last_exc: Optional[Exception] = None
        call_start: float = 0.0

        for attempt in range(1, max_attempts + 1):
            # Re-check circuit breaker before retry attempts
            if attempt > 1 and circuit_breaker is not None and not circuit_breaker.allow_request():
                if has_listeners:
                    _emit(listeners, EventType.CIRCUIT_OPEN, func_name)
                err = CircuitOpenError("Circuit breaker is open")
                if fallback_cfg is not None and isinstance(err, fallback_on):
                    if has_listeners:
                        _emit(listeners, EventType.FALLBACK_USED, func_name)
                    return _apply_fallback(fallback_cfg, err)
                raise err

            try:
                if track_duration:
                    call_start = time.monotonic()

                if has_timeout:
                    result = self._execute_with_timeout(func, func_name, listeners, *args, **kwargs)
                else:
                    result = func(*args, **kwargs)

                duration = (time.monotonic() - call_start) if track_duration else 0.0

                # Check retry_on_result predicate
                if retry_on_result is not None and retry_on_result(result):
                    if attempt < max_attempts:
                        delay = _compute_delay(retry_cfg, attempt) if retry_cfg else 0.0
                        if has_listeners:
                            _emit(
                                listeners,
                                EventType.RETRY,
                                func_name,
                                attempt=attempt,
                                detail=f"result predicate triggered, retrying in {delay:.2f}s",
                            )
                        if delay > 0:
                            # Release bulkhead during retry sleep
                            if bulkhead is not None and bulkhead_held[0]:
                                bulkhead.release()
                                bulkhead_held[0] = False
                            time.sleep(delay)
                            if bulkhead is not None and not bulkhead_held[0]:
                                if not bulkhead.acquire():
                                    raise BulkheadFullError("Bulkhead full")
                                bulkhead_held[0] = True
                        continue
                    # Last attempt: predicate matched but no retries left
                    if has_listeners:
                        _emit(
                            listeners,
                            EventType.RETRY_EXHAUSTED,
                            func_name,
                            attempt=attempt,
                            detail="result predicate matched on final attempt",
                        )
                    return result

                if circuit_breaker is not None:
                    prev_state, new_state = circuit_breaker.record_success_atomic(duration)
                    if (
                        new_state == CircuitState.CLOSED
                        and prev_state != CircuitState.CLOSED
                        and has_listeners
                    ):
                        _emit(listeners, EventType.CIRCUIT_CLOSED, func_name)
                    if track_duration and duration >= slow_call_duration and has_listeners:
                        _emit(
                            listeners,
                            EventType.SLOW_CALL,
                            func_name,
                            detail=f"{duration:.3f}s >= {slow_call_duration}s",
                        )

                if has_listeners:
                    _emit(listeners, EventType.SUCCESS, func_name, attempt=attempt)
                return result

            except Exception as exc:
                last_exc = exc
                duration = (time.monotonic() - call_start) if track_duration else 0.0

                # Circuit breaker tracking
                if circuit_breaker is not None and isinstance(exc, circuit_error_types):
                    new_state = circuit_breaker.record_failure(duration)
                    if new_state == CircuitState.OPEN and has_listeners:
                        _emit(listeners, EventType.CIRCUIT_OPEN, func_name, error=exc)

                # Retry if retryable and attempts remain
                if retry_cfg is not None and attempt < max_attempts and isinstance(exc, retry_on):
                    delay = _compute_delay(retry_cfg, attempt)
                    if has_listeners:
                        _emit(
                            listeners,
                            EventType.RETRY,
                            func_name,
                            attempt=attempt,
                            error=exc,
                            detail=f"retrying in {delay:.2f}s",
                        )
                    # Release bulkhead during retry sleep
                    if bulkhead is not None and bulkhead_held[0]:
                        bulkhead.release()
                        bulkhead_held[0] = False
                    time.sleep(delay)
                    if bulkhead is not None and not bulkhead_held[0]:
                        if not bulkhead.acquire():
                            raise BulkheadFullError("Bulkhead full") from exc
                        bulkhead_held[0] = True
                    continue

                # Retries exhausted
                if retry_cfg is not None and attempt >= max_attempts and has_listeners:
                    _emit(
                        listeners,
                        EventType.RETRY_EXHAUSTED,
                        func_name,
                        attempt=attempt,
                        error=exc,
                    )

                # Fallback
                if fallback_cfg is not None and isinstance(exc, fallback_on):
                    if has_listeners:
                        _emit(listeners, EventType.FALLBACK_USED, func_name, error=exc)
                    return _apply_fallback(fallback_cfg, exc)

                if has_listeners:
                    _emit(listeners, EventType.FAILURE, func_name, error=exc)
                raise

        # Retries exhausted via retry_on_result (no exception to re-raise)
        # Note: currently unreachable — last attempt always returns via success path
        if retry_cfg is not None and has_listeners:  # pragma: no cover
            _emit(
                listeners,
                EventType.RETRY_EXHAUSTED,
                func_name,
                attempt=max_attempts,
            )
        if last_exc:  # pragma: no cover
            raise last_exc
        raise RuntimeError("Unexpected state in retry loop")  # pragma: no cover

    def _execute_with_timeout(
        self,
        func: Callable[..., Any],
        func_name: str,
        listeners: list[ResilienceListener],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        timeout_seconds = self._timeout_seconds
        thread_id_holder: list[int] = []

        def _wrapper() -> Any:
            thread_id_holder.append(threading.get_ident())
            return func(*args, **kwargs)

        future = self._timeout_pool.submit(_wrapper)
        try:
            return future.result(timeout=timeout_seconds)
        except (TimeoutError, FuturesTimeoutError) as exc:
            future.cancel()
            # Best-effort: try to interrupt the running thread (CPython only).
            # This raises ResilienceTimeoutError at the next Python bytecode
            # boundary. Will NOT interrupt blocking C extensions.
            if thread_id_holder:
                _interrupt_thread(thread_id_holder[0])
            if self._has_listeners:
                _emit(
                    listeners,
                    EventType.TIMEOUT,
                    func_name,
                    detail=f"exceeded {timeout_seconds}s",
                )
            raise ResilienceTimeoutError(
                f"{func_name} exceeded timeout of {timeout_seconds}s"
            ) from exc


class _AsyncExecutor:
    """Executes an async function with resilience patterns.

    Mirrors _SyncExecutor optimizations: pre-cached config, inlined isinstance,
    guarded event emission, cached locals in hot loops.
    """

    __slots__ = (
        "_bulkhead",
        "_cache",
        "_circuit_breaker",
        "_circuit_error_types",
        "_fallback_cfg",
        "_fallback_on",
        "_fast_path",
        "_has_listeners",
        "_has_timeout",
        "_listeners",
        "_max_attempts",
        "_rate_limiter",
        "_retry_cfg",
        "_retry_on",
        "_retry_on_result",
        "_slow_call_duration",
        "_timeout_seconds",
    )

    def __init__(self, config: ResilienceConfig) -> None:
        self._listeners = list(config.listeners)
        self._has_listeners = bool(self._listeners)

        # Pre-cache tuples for isinstance checks
        self._retry_on: tuple[Type[BaseException], ...] = (
            tuple(config.retry.retry_on) if config.retry else ()
        )
        self._circuit_error_types: tuple[Type[BaseException], ...] = (
            tuple(config.circuit_breaker.error_types) if config.circuit_breaker else ()
        )
        self._fallback_on: tuple[Type[BaseException], ...] = (
            tuple(config.fallback.fallback_on) if config.fallback else ()
        )
        self._retry_cfg = config.retry
        self._fallback_cfg = config.fallback
        self._max_attempts = config.retry.max_attempts if config.retry else 1
        self._has_timeout = config.timeout is not None
        self._timeout_seconds = config.timeout.seconds if config.timeout else 0.0
        self._retry_on_result = config.retry.retry_on_result if config.retry else None
        self._slow_call_duration = (
            config.circuit_breaker.slow_call_duration if config.circuit_breaker else 0.0
        )
        self._fast_path = (
            config.retry is None and config.timeout is None and self._slow_call_duration == 0.0
        )

        self._circuit_breaker: Optional[CircuitBreaker] = (
            CircuitBreaker(config.circuit_breaker) if config.circuit_breaker else None
        )
        self._bulkhead: Optional[AsyncBulkhead] = (
            AsyncBulkhead(config.bulkhead) if config.bulkhead else None
        )
        self._rate_limiter: Optional[AsyncRateLimiter] = (
            AsyncRateLimiter(config.rate_limiter) if config.rate_limiter else None
        )
        self._cache: Optional[AsyncResultCache] = (
            AsyncResultCache(config.cache) if config.cache else None
        )

    async def execute(
        self, func: Callable[..., Any], func_name: str, *args: Any, **kwargs: Any
    ) -> Any:
        # Set unique call ID for MetricsCollector latency tracking
        call_id_var.set(next(_call_id_counter))

        listeners = self._listeners
        has_listeners = self._has_listeners
        fallback_cfg = self._fallback_cfg
        cache = self._cache

        # Cache check
        cache_key: Any = None
        cache_key_lock: Optional[asyncio.Lock] = None
        if cache is not None:
            cache_key = AsyncResultCache.make_key(*args, **kwargs)
            cached = cache.get(cache_key)
            if cached is not _SENTINEL:
                if has_listeners:
                    _emit(listeners, EventType.CACHE_HIT, func_name)
                return cached
            if has_listeners:
                _emit(listeners, EventType.CACHE_MISS, func_name)
            # Stampede prevention: per-key lock ensures only one coroutine computes
            cache_key_lock = cache.get_async_key_lock(cache_key)
            await cache_key_lock.acquire()
            # Double-check: another coroutine may have cached the value while we waited
            cached = cache.get(cache_key)
            if cached is not _SENTINEL:
                cache_key_lock.release()
                cache_key_lock = None
                if has_listeners:
                    _emit(listeners, EventType.CACHE_HIT, func_name)
                return cached

        try:
            # Circuit breaker
            circuit_breaker = self._circuit_breaker
            if circuit_breaker is not None and not circuit_breaker.allow_request():
                if has_listeners:
                    _emit(listeners, EventType.CIRCUIT_OPEN, func_name)
                if fallback_cfg is not None:
                    if has_listeners:
                        _emit(listeners, EventType.FALLBACK_USED, func_name)
                    return await _apply_fallback_async(
                        fallback_cfg, CircuitOpenError("Circuit breaker is open")
                    )
                raise CircuitOpenError("Circuit breaker is open")

            # Rate limiter
            rate_limiter = self._rate_limiter
            if rate_limiter is not None and not await rate_limiter.acquire():
                if has_listeners:
                    _emit(listeners, EventType.RATE_LIMITED, func_name)
                if fallback_cfg is not None:
                    if has_listeners:
                        _emit(listeners, EventType.FALLBACK_USED, func_name)
                    return await _apply_fallback_async(
                        fallback_cfg, RateLimitExceededError("Rate limit exceeded")
                    )
                raise RateLimitExceededError("Rate limit exceeded")

            # Bulkhead
            bulkhead = self._bulkhead
            if bulkhead is not None and not await bulkhead.acquire():
                if has_listeners:
                    _emit(listeners, EventType.BULKHEAD_REJECTED, func_name)
                if fallback_cfg is not None:
                    if has_listeners:
                        _emit(listeners, EventType.FALLBACK_USED, func_name)
                    return await _apply_fallback_async(
                        fallback_cfg, BulkheadFullError("Bulkhead full")
                    )
                raise BulkheadFullError("Bulkhead full")

            # Track whether we currently hold the bulkhead slot
            bulkhead_held = [bulkhead is not None]

            try:
                if self._fast_path:
                    result = await self._execute_direct(
                        func, func_name, listeners, has_listeners, circuit_breaker, *args, **kwargs
                    )
                else:
                    result = await self._execute_with_retry(
                        func,
                        func_name,
                        listeners,
                        has_listeners,
                        circuit_breaker,
                        bulkhead,
                        bulkhead_held,
                        *args,
                        **kwargs,
                    )
                if cache is not None and cache_key is not None:
                    cache.put(cache_key, result)
                return result
            finally:
                if bulkhead_held[0]:
                    bulkhead.release()  # type: ignore[union-attr]
        finally:
            if cache_key_lock is not None:
                cache_key_lock.release()

    async def _execute_direct(
        self,
        func: Callable[..., Any],
        func_name: str,
        listeners: list[ResilienceListener],
        has_listeners: bool,
        circuit_breaker: Optional[CircuitBreaker],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Fast path: single async execution with no retry loop overhead."""
        fallback_on = self._fallback_on
        fallback_cfg = self._fallback_cfg
        try:
            result = await func(*args, **kwargs)
            if circuit_breaker is not None:
                prev_state, new_state = circuit_breaker.record_success_atomic(0.0)
                if (
                    new_state == CircuitState.CLOSED
                    and prev_state != CircuitState.CLOSED
                    and has_listeners
                ):
                    _emit(listeners, EventType.CIRCUIT_CLOSED, func_name)
            if has_listeners:
                _emit(listeners, EventType.SUCCESS, func_name, attempt=1)
            return result
        except Exception as exc:
            if circuit_breaker is not None and isinstance(exc, self._circuit_error_types):
                new_state = circuit_breaker.record_failure(0.0)
                if new_state == CircuitState.OPEN and has_listeners:
                    _emit(listeners, EventType.CIRCUIT_OPEN, func_name, error=exc)
            if fallback_cfg is not None and isinstance(exc, fallback_on):
                if has_listeners:
                    _emit(listeners, EventType.FALLBACK_USED, func_name, error=exc)
                return await _apply_fallback_async(fallback_cfg, exc)
            if has_listeners:
                _emit(listeners, EventType.FAILURE, func_name, error=exc)
            raise

    async def _execute_with_retry(
        self,
        func: Callable[..., Any],
        func_name: str,
        listeners: list[ResilienceListener],
        has_listeners: bool,
        circuit_breaker: Optional[CircuitBreaker],
        bulkhead: Optional[AsyncBulkhead],
        bulkhead_held: list[bool],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        retry_cfg = self._retry_cfg
        max_attempts = self._max_attempts
        retry_on = self._retry_on
        circuit_error_types = self._circuit_error_types
        fallback_on = self._fallback_on
        fallback_cfg = self._fallback_cfg
        has_timeout = self._has_timeout
        timeout_seconds = self._timeout_seconds
        retry_on_result = self._retry_on_result
        slow_call_duration = self._slow_call_duration
        track_duration = circuit_breaker is not None and slow_call_duration > 0
        last_exc: Optional[Exception] = None
        call_start: float = 0.0

        for attempt in range(1, max_attempts + 1):
            # Re-check circuit breaker before retry attempts
            if attempt > 1 and circuit_breaker is not None and not circuit_breaker.allow_request():
                if has_listeners:
                    _emit(listeners, EventType.CIRCUIT_OPEN, func_name)
                err = CircuitOpenError("Circuit breaker is open")
                if fallback_cfg is not None and isinstance(err, fallback_on):
                    if has_listeners:
                        _emit(listeners, EventType.FALLBACK_USED, func_name)
                    return await _apply_fallback_async(fallback_cfg, err)
                raise err

            try:
                if track_duration:
                    call_start = time.monotonic()

                if has_timeout:
                    try:
                        result = await asyncio.wait_for(
                            func(*args, **kwargs), timeout=timeout_seconds
                        )
                    except asyncio.TimeoutError as exc:
                        if has_listeners:
                            _emit(
                                listeners,
                                EventType.TIMEOUT,
                                func_name,
                                detail=f"exceeded {timeout_seconds}s",
                            )
                        raise ResilienceTimeoutError(
                            f"{func_name} exceeded timeout of {timeout_seconds}s"
                        ) from exc
                else:
                    result = await func(*args, **kwargs)

                duration = (time.monotonic() - call_start) if track_duration else 0.0

                # Check retry_on_result predicate
                if retry_on_result is not None and retry_on_result(result):
                    if attempt < max_attempts:
                        delay = _compute_delay(retry_cfg, attempt) if retry_cfg else 0.0
                        if has_listeners:
                            _emit(
                                listeners,
                                EventType.RETRY,
                                func_name,
                                attempt=attempt,
                                detail=f"result predicate triggered, retrying in {delay:.2f}s",
                            )
                        if delay > 0:
                            # Release bulkhead during retry sleep
                            if bulkhead is not None and bulkhead_held[0]:
                                bulkhead.release()
                                bulkhead_held[0] = False
                            await asyncio.sleep(delay)
                            if bulkhead is not None and not bulkhead_held[0]:
                                if not await bulkhead.acquire():
                                    raise BulkheadFullError("Bulkhead full")
                                bulkhead_held[0] = True
                        continue
                    # Last attempt: predicate matched but no retries left
                    if has_listeners:
                        _emit(
                            listeners,
                            EventType.RETRY_EXHAUSTED,
                            func_name,
                            attempt=attempt,
                            detail="result predicate matched on final attempt",
                        )
                    return result

                if circuit_breaker is not None:
                    prev_state, new_state = circuit_breaker.record_success_atomic(duration)
                    if (
                        new_state == CircuitState.CLOSED
                        and prev_state != CircuitState.CLOSED
                        and has_listeners
                    ):
                        _emit(listeners, EventType.CIRCUIT_CLOSED, func_name)
                    if track_duration and duration >= slow_call_duration and has_listeners:
                        _emit(
                            listeners,
                            EventType.SLOW_CALL,
                            func_name,
                            detail=f"{duration:.3f}s >= {slow_call_duration}s",
                        )

                if has_listeners:
                    _emit(listeners, EventType.SUCCESS, func_name, attempt=attempt)
                return result

            except Exception as exc:
                last_exc = exc
                duration = (time.monotonic() - call_start) if track_duration else 0.0

                if circuit_breaker is not None and isinstance(exc, circuit_error_types):
                    new_state = circuit_breaker.record_failure(duration)
                    if new_state == CircuitState.OPEN and has_listeners:
                        _emit(listeners, EventType.CIRCUIT_OPEN, func_name, error=exc)

                if retry_cfg is not None and attempt < max_attempts and isinstance(exc, retry_on):
                    delay = _compute_delay(retry_cfg, attempt)
                    if has_listeners:
                        _emit(
                            listeners,
                            EventType.RETRY,
                            func_name,
                            attempt=attempt,
                            error=exc,
                            detail=f"retrying in {delay:.2f}s",
                        )
                    # Release bulkhead during retry sleep
                    if bulkhead is not None and bulkhead_held[0]:
                        bulkhead.release()
                        bulkhead_held[0] = False
                    await asyncio.sleep(delay)
                    if bulkhead is not None and not bulkhead_held[0]:
                        if not await bulkhead.acquire():
                            raise BulkheadFullError("Bulkhead full") from exc
                        bulkhead_held[0] = True
                    continue

                if retry_cfg is not None and attempt >= max_attempts and has_listeners:
                    _emit(
                        listeners,
                        EventType.RETRY_EXHAUSTED,
                        func_name,
                        attempt=attempt,
                        error=exc,
                    )

                if fallback_cfg is not None and isinstance(exc, fallback_on):
                    if has_listeners:
                        _emit(listeners, EventType.FALLBACK_USED, func_name, error=exc)
                    return await _apply_fallback_async(fallback_cfg, exc)

                if has_listeners:
                    _emit(listeners, EventType.FAILURE, func_name, error=exc)
                raise

        # Retries exhausted via retry_on_result (no exception to re-raise)
        # Note: currently unreachable — last attempt always returns via success path
        if retry_cfg is not None and has_listeners:  # pragma: no cover
            _emit(
                listeners,
                EventType.RETRY_EXHAUSTED,
                func_name,
                attempt=max_attempts,
            )
        if last_exc:  # pragma: no cover
            raise last_exc
        raise RuntimeError("Unexpected state in retry loop")  # pragma: no cover
