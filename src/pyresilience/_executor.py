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
import os
import random
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from functools import partial
from typing import TYPE_CHECKING, Any, Callable, Optional, Type, Union

from pyresilience._bulkhead import AsyncBulkhead, Bulkhead
from pyresilience._cache import _SENTINEL, AsyncResultCache, ResultCache
from pyresilience._events import _emit
from pyresilience._exceptions import (
    BulkheadFullError,
    CircuitOpenError,
    ResilienceTimeoutError,
)
from pyresilience._fallback import (
    _apply_fallback,
    _apply_fallback_async,
    _fallback_match,
    _FallbackRouter,
)
from pyresilience._logging import _call_id_counter, call_id_var
from pyresilience._parts import _build_parts, _Parts
from pyresilience._rate_limiter import AsyncRateLimiter, RateLimiter, RateLimitExceededError
from pyresilience._stream import _wrap_stream
from pyresilience._types import (
    CircuitState,
    EventType,
    ResilienceConfig,
    ResilienceListener,
    RetryConfig,
)
from pyresilience._weighted_limiter import _AsyncWeightedRateLimiter, _WeightedRateLimiter

if TYPE_CHECKING:
    from pyresilience._circuit_breaker import CircuitBreaker
    from pyresilience._retry_budget import RetryBudget

# Shared thread pool for sync timeouts — sized like Python 3.13's default
_default_timeout_pool = ThreadPoolExecutor(max_workers=min(32, (os.cpu_count() or 1) + 4))

# Track custom pools for cleanup at exit
_custom_pools: list[weakref.ref[ThreadPoolExecutor]] = []

# In-flight call tracking for graceful shutdown (lazy activation)
# Tracking is zero-cost until enable_in_flight_tracking() or shutdown() is called.
_in_flight = threading.Event()
_in_flight.set()  # Initially "no calls in flight" (set = ready)
_in_flight_count = 0
_in_flight_lock = threading.Lock()
_shutting_down = False
_tracking_enabled = False


def enable_in_flight_tracking() -> None:
    """Enable in-flight call tracking. Called automatically by shutdown()."""
    global _tracking_enabled
    _tracking_enabled = True


def _track_call_start() -> None:
    """Increment in-flight call counter. No-op unless tracking is enabled."""
    if not _tracking_enabled:
        return
    global _in_flight_count
    with _in_flight_lock:
        _in_flight_count += 1
        _in_flight.clear()


def _track_call_end() -> None:
    """Decrement in-flight call counter. No-op unless tracking is enabled."""
    if not _tracking_enabled:
        return
    global _in_flight_count
    with _in_flight_lock:
        _in_flight_count -= 1
        if _in_flight_count <= 0:
            _in_flight_count = 0
            _in_flight.set()


def get_in_flight_count() -> int:
    """Return the number of currently in-flight resilient calls."""
    with _in_flight_lock:
        return _in_flight_count


def shutdown(wait: bool = True, timeout: float = 30.0) -> bool:
    """Gracefully shut down pyresilience, draining in-flight calls.

    Args:
        wait: If True, block until all in-flight calls complete or timeout expires.
        timeout: Maximum seconds to wait for in-flight calls to drain.

    Returns:
        True if all calls drained within the timeout, False if timed out.
    """
    global _shutting_down
    _shutting_down = True
    enable_in_flight_tracking()

    drained = True
    if wait:
        drained = _in_flight.wait(timeout=timeout)

    # Shut down thread pools
    _shutdown_pools()
    return drained


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
        return ret == 1
    except Exception:
        return False


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
        "_circuit_ignore_on",
        "_delay_func",
        "_entry",
        "_fallback_cfg",
        "_fallback_on",
        "_fast_path",
        "_has_listeners",
        "_has_timeout",
        "_ignore_on",
        "_listeners",
        "_max_attempts",
        "_rate_limiter",
        "_retry_budget",
        "_retry_cfg",
        "_retry_on",
        "_retry_on_result",
        "_router",
        "_slow_call_duration",
        "_stream_idle",
        "_timeout_per_attempt",
        "_timeout_pool",
        "_timeout_seconds",
        "_timeout_total",
        "_weighted_limiter",
    )

    def __init__(
        self,
        config: ResilienceConfig,
        shared: Optional[_Parts] = None,
        state_key: str = "",
    ) -> None:
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
        self._ignore_on: tuple[Type[BaseException], ...] = (
            tuple(config.retry.ignore_on) if config.retry else ()
        )
        self._circuit_ignore_on: tuple[Type[BaseException], ...] = (
            tuple(config.circuit_breaker.ignore_on) if config.circuit_breaker else ()
        )
        self._delay_func: Optional[Callable[[int, Any], Optional[float]]] = (
            config.retry.delay_func if config.retry else None
        )
        self._retry_cfg = config.retry
        self._fallback_cfg = config.fallback
        self._max_attempts = config.retry.max_attempts if config.retry else 1
        self._has_timeout = config.timeout is not None
        self._timeout_seconds = config.timeout.seconds if config.timeout else 0.0
        self._timeout_per_attempt = config.timeout.per_attempt if config.timeout else True
        # Overall deadline: `seconds` when per_attempt is off, else the optional total_seconds
        self._timeout_total = 0.0
        self._stream_idle = 0.0
        if config.timeout is not None:
            if not config.timeout.per_attempt:
                self._timeout_total = config.timeout.seconds
            elif config.timeout.total_seconds is not None:
                self._timeout_total = config.timeout.total_seconds
            self._stream_idle = config.timeout.stream_idle_seconds or 0.0
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

        # Stateful parts: built for this executor, or shared under a registry name
        parts = shared if shared is not None else _build_parts(config, state_key)
        self._circuit_breaker: Optional[CircuitBreaker] = parts.circuit_breaker
        self._bulkhead: Optional[Bulkhead] = Bulkhead(config.bulkhead) if config.bulkhead else None
        # The weighted limiter replaces the plain one only when the config needs it
        self._rate_limiter: Union[RateLimiter, _WeightedRateLimiter, None] = parts.plain_limiter
        self._weighted_limiter: Optional[_WeightedRateLimiter] = None
        if config.rate_limiter is not None and parts.limiter_core is not None:
            self._weighted_limiter = _WeightedRateLimiter(config.rate_limiter, parts.limiter_core)
            self._rate_limiter = self._weighted_limiter
        self._cache: Optional[ResultCache] = ResultCache(config.cache) if config.cache else None
        self._retry_budget: Optional[RetryBudget] = parts.retry_budget

        # Alternatives and cooldown are handled by a router around the core. The core
        # then runs without a fallback of its own, so failures reach the router.
        self._router: Optional[_FallbackRouter] = parts.router
        if self._router is not None:
            self._fallback_cfg = None
            self._fallback_on = ()

        # Entry point is chosen once, so the plain path pays for no optional feature
        self._entry: Callable[..., Any] = self._execute_core
        if self._router is not None:
            self._entry = self._execute_routed
        elif self._stream_idle > 0:
            self._entry = self._execute_stream

    def execute(self, func: Callable[..., Any], func_name: str, *args: Any, **kwargs: Any) -> Any:
        # Set unique call ID for MetricsCollector latency tracking
        call_id_var.set(next(_call_id_counter))
        _tracking = _tracking_enabled
        if _tracking:
            _track_call_start()

        try:
            return self._entry(func, func_name, *args, **kwargs)
        finally:
            if _tracking:
                _track_call_end()

    def _execute_stream(
        self, func: Callable[..., Any], func_name: str, *args: Any, **kwargs: Any
    ) -> Any:
        """Run the call, then bound the idle time of a streamed result."""
        result = self._execute_core(func, func_name, *args, **kwargs)
        return _wrap_stream(result, self._stream_idle, func_name, self._listeners)

    def _execute_routed(
        self, func: Callable[..., Any], func_name: str, *args: Any, **kwargs: Any
    ) -> Any:
        """Run the call through the fallback router (alternatives and cooldown)."""
        router: _FallbackRouter = self._router  # type: ignore[assignment]
        cache = self._cache
        result: Any = _SENTINEL
        report_miss: Optional[Callable[[], None]] = None
        if cache is not None and router.primary_cooling():
            # The cache comes first in the pipeline, also while the primary is skipped
            result = cache.get(ResultCache.make_key(*args, **kwargs))
            if self._has_listeners:
                if result is not _SENTINEL:
                    _emit(self._listeners, EventType.CACHE_HIT, func_name)
                else:
                    # Reported when a fallback answers. If the primary is called after
                    # all, the core looks the cache up again and reports the miss itself.
                    report_miss = partial(_emit, self._listeners, EventType.CACHE_MISS, func_name)
        if result is _SENTINEL:
            result = router.run_sync(
                self._execute_core, func, func_name, args, kwargs, self._listeners, report_miss
            )
        if self._stream_idle > 0:
            result = _wrap_stream(result, self._stream_idle, func_name, self._listeners)
        return result

    def _on_rate_limited(
        self, func_name: str, listeners: list[ResilienceListener], blocker: str
    ) -> Any:
        """A weighted limit refused the call: fall back or raise."""
        has_listeners = self._has_listeners
        if has_listeners:
            _emit(
                listeners,
                EventType.RATE_LIMITED,
                func_name,
                detail=f"limit '{blocker}' exceeded",
            )
        err = RateLimitExceededError(f"Rate limit exceeded ({blocker})")
        fallback_cfg = self._fallback_cfg
        if fallback_cfg is not None:
            if has_listeners:
                _emit(listeners, EventType.FALLBACK_USED, func_name)
            return _apply_fallback(fallback_cfg, err)
        raise err

    def _on_total_timeout(
        self,
        func_name: str,
        listeners: list[ResilienceListener],
        cause: Optional[BaseException],
    ) -> Any:
        """Stop retrying because the overall deadline is spent: fall back or raise."""
        total = self._timeout_total
        has_listeners = self._has_listeners
        # An attempt that ran into the deadline has already reported its timeout
        if has_listeners and not isinstance(cause, ResilienceTimeoutError):
            _emit(listeners, EventType.TIMEOUT, func_name, detail=f"exceeded total {total}s budget")
        err = ResilienceTimeoutError(f"{func_name} exceeded total timeout budget of {total}s")
        err.__cause__ = cause
        fallback_cfg = self._fallback_cfg
        if fallback_cfg is not None:
            # A fallback for the error that was being retried still applies
            matched = _fallback_match(err, self._fallback_on)
            if matched is not None:
                if has_listeners:
                    _emit(listeners, EventType.FALLBACK_USED, func_name, error=err)
                return _apply_fallback(fallback_cfg, matched)
        if has_listeners:
            _emit(listeners, EventType.FAILURE, func_name, error=err)
        raise err

    def _execute_core(
        self, func: Callable[..., Any], func_name: str, *args: Any, **kwargs: Any
    ) -> Any:
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
            if rate_limiter is not None:
                weighted = self._weighted_limiter
                if weighted is not None:
                    costs, blocker = weighted.reserve(args, kwargs)
                    if costs is None:
                        return self._on_rate_limited(func_name, listeners, blocker)
                    if weighted.observes:
                        func = weighted.bind(func, costs)
                elif not rate_limiter.acquire():
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
            if has_listeners:
                _start = time.monotonic()
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
                _emit(
                    listeners,
                    EventType.SUCCESS,
                    func_name,
                    attempt=1,
                    duration=time.monotonic() - _start,
                )
            return result
        except Exception as exc:
            if (
                circuit_breaker is not None
                and isinstance(exc, self._circuit_error_types)
                and not (self._circuit_ignore_on and isinstance(exc, self._circuit_ignore_on))
            ):
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

    def _resolve_delay(self, attempt: int, trigger: Union[BaseException, Any]) -> float:
        """Compute retry delay, honouring custom delay_func when set.

        Returns 0.0 for negative custom values; clamps to max_delay.
        Falls back to _compute_delay when delay_func is absent or returns None.
        """
        delay_func = self._delay_func
        if delay_func is not None:
            custom = delay_func(attempt, trigger)
            if custom is not None:
                if custom < 0:
                    return 0.0
                max_delay = self._retry_cfg.max_delay  # type: ignore[union-attr]
                if custom > max_delay:
                    return max_delay
                return custom
        return _compute_delay(self._retry_cfg, attempt)  # type: ignore[arg-type]

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
        ignore_on = self._ignore_on
        circuit_error_types = self._circuit_error_types
        circuit_ignore_on = self._circuit_ignore_on
        fallback_on = self._fallback_on
        fallback_cfg = self._fallback_cfg
        has_timeout = self._has_timeout
        timeout_per_attempt = self._timeout_per_attempt
        retry_on_result = self._retry_on_result
        slow_call_duration = self._slow_call_duration
        track_duration = circuit_breaker is not None and slow_call_duration > 0
        last_exc: Optional[Exception] = None
        call_start: float = 0.0
        # Overall deadline shared by all attempts and retry waits (0.0 = none)
        timeout_seconds: float = 0.0
        deadline: float = 0.0
        if has_timeout:
            timeout_seconds = self._timeout_seconds
            if self._timeout_total > 0:
                deadline = time.monotonic() + self._timeout_total

        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                # Re-check circuit breaker before retry attempts
                if circuit_breaker is not None and not circuit_breaker.allow_request():
                    if has_listeners:
                        _emit(listeners, EventType.CIRCUIT_OPEN, func_name)
                    err = CircuitOpenError("Circuit breaker is open")
                    if fallback_cfg is not None and isinstance(err, fallback_on):
                        if has_listeners:
                            _emit(listeners, EventType.FALLBACK_USED, func_name)
                        return _apply_fallback(fallback_cfg, err)
                    raise err

                if deadline and time.monotonic() >= deadline:
                    # The retry sleep or the wait for a bulkhead slot overshot the deadline
                    return self._on_total_timeout(func_name, listeners, last_exc)

            try:
                if track_duration:
                    call_start = time.monotonic()

                if has_timeout:
                    attempt_timeout = timeout_seconds
                    if deadline:
                        # Never let one attempt outlive the overall deadline
                        remaining = deadline - time.monotonic()
                        if not timeout_per_attempt or remaining < attempt_timeout:
                            attempt_timeout = round(remaining, 3)
                    result = self._execute_with_timeout(
                        func, func_name, listeners, attempt_timeout, *args, **kwargs
                    )
                else:
                    result = func(*args, **kwargs)

                duration = (time.monotonic() - call_start) if track_duration else 0.0

                # Check retry_on_result predicate
                if retry_on_result is not None and retry_on_result(result):
                    if attempt < max_attempts:
                        retry_budget = self._retry_budget
                        if retry_budget is not None and not retry_budget.acquire():
                            if has_listeners:
                                _emit(
                                    listeners,
                                    EventType.RETRY_EXHAUSTED,
                                    func_name,
                                    attempt=attempt,
                                    detail="retry budget exhausted",
                                )
                            return result
                        delay = self._resolve_delay(attempt, result)
                        if deadline and time.monotonic() + delay >= deadline:
                            # No time left for another attempt: hand back the last result
                            if retry_budget is not None:
                                retry_budget.refund()
                            if has_listeners:
                                _emit(
                                    listeners,
                                    EventType.RETRY_EXHAUSTED,
                                    func_name,
                                    attempt=attempt,
                                    detail="total timeout budget exhausted",
                                )
                            return result
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
                    _emit(
                        listeners,
                        EventType.SUCCESS,
                        func_name,
                        attempt=attempt,
                        duration=duration,
                    )
                return result

            except Exception as exc:
                last_exc = exc
                duration = (time.monotonic() - call_start) if track_duration else 0.0

                # Circuit breaker tracking — ignored exceptions must never record failure
                if (
                    circuit_breaker is not None
                    and isinstance(exc, circuit_error_types)
                    and not (circuit_ignore_on and isinstance(exc, circuit_ignore_on))
                ):
                    new_state = circuit_breaker.record_failure(duration)
                    if new_state == CircuitState.OPEN and has_listeners:
                        _emit(listeners, EventType.CIRCUIT_OPEN, func_name, error=exc)

                # ignore_on: re-raise immediately, no retry, no fallback chain
                if ignore_on and isinstance(exc, ignore_on):
                    if has_listeners:
                        _emit(listeners, EventType.FAILURE, func_name, attempt=attempt, error=exc)
                    raise

                # Retry if retryable and attempts remain
                if retry_cfg is not None and attempt < max_attempts and isinstance(exc, retry_on):
                    # Check retry budget before retrying
                    retry_budget = self._retry_budget
                    if retry_budget is not None and not retry_budget.acquire():
                        if has_listeners:
                            _emit(
                                listeners,
                                EventType.RETRY_EXHAUSTED,
                                func_name,
                                attempt=attempt,
                                error=exc,
                                detail="retry budget exhausted",
                            )
                        if fallback_cfg is not None and isinstance(exc, fallback_on):
                            if has_listeners:
                                _emit(listeners, EventType.FALLBACK_USED, func_name, error=exc)
                            return _apply_fallback(fallback_cfg, exc)
                        raise

                    delay = self._resolve_delay(attempt, exc)
                    if deadline and time.monotonic() + delay >= deadline:
                        # No time left for another attempt: stop instead of sleeping
                        if retry_budget is not None:
                            retry_budget.refund()
                        return self._on_total_timeout(func_name, listeners, exc)
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
        timeout_seconds: float,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
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
        "_circuit_ignore_on",
        "_delay_func",
        "_entry",
        "_fallback_cfg",
        "_fallback_on",
        "_fast_path",
        "_has_listeners",
        "_has_timeout",
        "_ignore_on",
        "_listeners",
        "_max_attempts",
        "_rate_limiter",
        "_retry_budget",
        "_retry_cfg",
        "_retry_on",
        "_retry_on_result",
        "_router",
        "_slow_call_duration",
        "_stream_idle",
        "_timeout_per_attempt",
        "_timeout_seconds",
        "_timeout_total",
        "_weighted_limiter",
    )

    def __init__(
        self,
        config: ResilienceConfig,
        shared: Optional[_Parts] = None,
        state_key: str = "",
    ) -> None:
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
        self._ignore_on: tuple[Type[BaseException], ...] = (
            tuple(config.retry.ignore_on) if config.retry else ()
        )
        self._circuit_ignore_on: tuple[Type[BaseException], ...] = (
            tuple(config.circuit_breaker.ignore_on) if config.circuit_breaker else ()
        )
        self._delay_func: Optional[Callable[[int, Any], Optional[float]]] = (
            config.retry.delay_func if config.retry else None
        )
        self._retry_cfg = config.retry
        self._fallback_cfg = config.fallback
        self._max_attempts = config.retry.max_attempts if config.retry else 1
        self._has_timeout = config.timeout is not None
        self._timeout_seconds = config.timeout.seconds if config.timeout else 0.0
        self._timeout_per_attempt = config.timeout.per_attempt if config.timeout else True
        # Overall deadline: `seconds` when per_attempt is off, else the optional total_seconds
        self._timeout_total = 0.0
        self._stream_idle = 0.0
        if config.timeout is not None:
            if not config.timeout.per_attempt:
                self._timeout_total = config.timeout.seconds
            elif config.timeout.total_seconds is not None:
                self._timeout_total = config.timeout.total_seconds
            self._stream_idle = config.timeout.stream_idle_seconds or 0.0
        self._retry_on_result = config.retry.retry_on_result if config.retry else None
        self._slow_call_duration = (
            config.circuit_breaker.slow_call_duration if config.circuit_breaker else 0.0
        )
        self._fast_path = (
            config.retry is None and config.timeout is None and self._slow_call_duration == 0.0
        )

        # Stateful parts: built for this executor, or shared under a registry name
        parts = shared if shared is not None else _build_parts(config, state_key)
        self._circuit_breaker: Optional[CircuitBreaker] = parts.circuit_breaker
        self._bulkhead: Optional[AsyncBulkhead] = (
            AsyncBulkhead(config.bulkhead) if config.bulkhead else None
        )
        # The weighted limiter replaces the plain one only when the config needs it
        self._rate_limiter: Union[AsyncRateLimiter, _AsyncWeightedRateLimiter, None] = None
        self._weighted_limiter: Optional[_AsyncWeightedRateLimiter] = None
        if config.rate_limiter is not None:
            if parts.limiter_core is not None:
                self._weighted_limiter = _AsyncWeightedRateLimiter(
                    config.rate_limiter, parts.limiter_core
                )
                self._rate_limiter = self._weighted_limiter
            elif shared is not None:
                # Draw from the bucket the sync executor of this name uses
                self._rate_limiter = AsyncRateLimiter(config.rate_limiter, parts.plain_limiter)
            else:
                self._rate_limiter = AsyncRateLimiter(config.rate_limiter)
        self._cache: Optional[AsyncResultCache] = (
            AsyncResultCache(config.cache) if config.cache else None
        )
        self._retry_budget: Optional[RetryBudget] = parts.retry_budget

        # Alternatives and cooldown are handled by a router around the core. The core
        # then runs without a fallback of its own, so failures reach the router.
        self._router: Optional[_FallbackRouter] = parts.router
        if self._router is not None:
            self._fallback_cfg = None
            self._fallback_on = ()

        # Entry point is chosen once, so the plain path pays for no optional feature
        self._entry: Callable[..., Any] = self._execute_core
        if self._router is not None:
            self._entry = self._execute_routed
        elif self._stream_idle > 0:
            self._entry = self._execute_stream

    async def execute(
        self, func: Callable[..., Any], func_name: str, *args: Any, **kwargs: Any
    ) -> Any:
        # Set unique call ID for MetricsCollector latency tracking
        call_id_var.set(next(_call_id_counter))
        _tracking = _tracking_enabled
        if _tracking:
            _track_call_start()

        try:
            return await self._entry(func, func_name, *args, **kwargs)
        finally:
            if _tracking:
                _track_call_end()

    async def _execute_stream(
        self, func: Callable[..., Any], func_name: str, *args: Any, **kwargs: Any
    ) -> Any:
        """Run the call, then bound the idle time of a streamed result."""
        result = await self._execute_core(func, func_name, *args, **kwargs)
        return _wrap_stream(result, self._stream_idle, func_name, self._listeners)

    async def _execute_routed(
        self, func: Callable[..., Any], func_name: str, *args: Any, **kwargs: Any
    ) -> Any:
        """Run the call through the fallback router (alternatives and cooldown)."""
        router: _FallbackRouter = self._router  # type: ignore[assignment]
        cache = self._cache
        result: Any = _SENTINEL
        report_miss: Optional[Callable[[], None]] = None
        if cache is not None and router.primary_cooling():
            # The cache comes first in the pipeline, also while the primary is skipped
            result = cache.get(AsyncResultCache.make_key(*args, **kwargs))
            if self._has_listeners:
                if result is not _SENTINEL:
                    _emit(self._listeners, EventType.CACHE_HIT, func_name)
                else:
                    # Reported when a fallback answers. If the primary is called after
                    # all, the core looks the cache up again and reports the miss itself.
                    report_miss = partial(_emit, self._listeners, EventType.CACHE_MISS, func_name)
        if result is _SENTINEL:
            result = await router.run_async(
                self._execute_core, func, func_name, args, kwargs, self._listeners, report_miss
            )
        if self._stream_idle > 0:
            result = _wrap_stream(result, self._stream_idle, func_name, self._listeners)
        return result

    async def _on_rate_limited(
        self, func_name: str, listeners: list[ResilienceListener], blocker: str
    ) -> Any:
        """A weighted limit refused the call: fall back or raise."""
        has_listeners = self._has_listeners
        if has_listeners:
            _emit(
                listeners,
                EventType.RATE_LIMITED,
                func_name,
                detail=f"limit '{blocker}' exceeded",
            )
        err = RateLimitExceededError(f"Rate limit exceeded ({blocker})")
        fallback_cfg = self._fallback_cfg
        if fallback_cfg is not None:
            if has_listeners:
                _emit(listeners, EventType.FALLBACK_USED, func_name)
            return await _apply_fallback_async(fallback_cfg, err)
        raise err

    async def _on_total_timeout(
        self,
        func_name: str,
        listeners: list[ResilienceListener],
        cause: Optional[BaseException],
    ) -> Any:
        """Stop retrying because the overall deadline is spent: fall back or raise."""
        total = self._timeout_total
        has_listeners = self._has_listeners
        # An attempt that ran into the deadline has already reported its timeout
        if has_listeners and not isinstance(cause, ResilienceTimeoutError):
            _emit(listeners, EventType.TIMEOUT, func_name, detail=f"exceeded total {total}s budget")
        err = ResilienceTimeoutError(f"{func_name} exceeded total timeout budget of {total}s")
        err.__cause__ = cause
        fallback_cfg = self._fallback_cfg
        if fallback_cfg is not None:
            # A fallback for the error that was being retried still applies
            matched = _fallback_match(err, self._fallback_on)
            if matched is not None:
                if has_listeners:
                    _emit(listeners, EventType.FALLBACK_USED, func_name, error=err)
                return await _apply_fallback_async(fallback_cfg, matched)
        if has_listeners:
            _emit(listeners, EventType.FAILURE, func_name, error=err)
        raise err

    async def _execute_core(
        self, func: Callable[..., Any], func_name: str, *args: Any, **kwargs: Any
    ) -> Any:
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
            if rate_limiter is not None:
                weighted = self._weighted_limiter
                if weighted is not None:
                    costs, blocker = await weighted.reserve(args, kwargs)
                    if costs is None:
                        return await self._on_rate_limited(func_name, listeners, blocker)
                    if weighted.observes:
                        func = weighted.bind(func, costs)
                elif not await rate_limiter.acquire():
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
            if has_listeners:
                _start = time.monotonic()
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
                _emit(
                    listeners,
                    EventType.SUCCESS,
                    func_name,
                    attempt=1,
                    duration=time.monotonic() - _start,
                )
            return result
        except Exception as exc:
            if (
                circuit_breaker is not None
                and isinstance(exc, self._circuit_error_types)
                and not (self._circuit_ignore_on and isinstance(exc, self._circuit_ignore_on))
            ):
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

    def _resolve_delay(self, attempt: int, trigger: Union[BaseException, Any]) -> float:
        """Compute retry delay, honouring custom delay_func when set.

        Returns 0.0 for negative custom values; clamps to max_delay.
        Falls back to _compute_delay when delay_func is absent or returns None.
        """
        delay_func = self._delay_func
        if delay_func is not None:
            custom = delay_func(attempt, trigger)
            if custom is not None:
                if custom < 0:
                    return 0.0
                max_delay = self._retry_cfg.max_delay  # type: ignore[union-attr]
                if custom > max_delay:
                    return max_delay
                return custom
        return _compute_delay(self._retry_cfg, attempt)  # type: ignore[arg-type]

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
        ignore_on = self._ignore_on
        circuit_error_types = self._circuit_error_types
        circuit_ignore_on = self._circuit_ignore_on
        fallback_on = self._fallback_on
        fallback_cfg = self._fallback_cfg
        has_timeout = self._has_timeout
        timeout_per_attempt = self._timeout_per_attempt
        retry_on_result = self._retry_on_result
        slow_call_duration = self._slow_call_duration
        track_duration = circuit_breaker is not None and slow_call_duration > 0
        last_exc: Optional[Exception] = None
        call_start: float = 0.0
        # Overall deadline shared by all attempts and retry waits (0.0 = none)
        timeout_seconds: float = 0.0
        deadline: float = 0.0
        if has_timeout:
            timeout_seconds = self._timeout_seconds
            if self._timeout_total > 0:
                deadline = time.monotonic() + self._timeout_total

        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                # Re-check circuit breaker before retry attempts
                if circuit_breaker is not None and not circuit_breaker.allow_request():
                    if has_listeners:
                        _emit(listeners, EventType.CIRCUIT_OPEN, func_name)
                    err = CircuitOpenError("Circuit breaker is open")
                    if fallback_cfg is not None and isinstance(err, fallback_on):
                        if has_listeners:
                            _emit(listeners, EventType.FALLBACK_USED, func_name)
                        return await _apply_fallback_async(fallback_cfg, err)
                    raise err

                if deadline and time.monotonic() >= deadline:
                    # The retry sleep or the wait for a bulkhead slot overshot the deadline
                    return await self._on_total_timeout(func_name, listeners, last_exc)

            try:
                if track_duration:
                    call_start = time.monotonic()

                if has_timeout:
                    effective_timeout = timeout_seconds
                    if deadline:
                        # Never let one attempt outlive the overall deadline
                        remaining = deadline - time.monotonic()
                        if not timeout_per_attempt or remaining < effective_timeout:
                            effective_timeout = round(remaining, 3)
                    try:
                        result = await asyncio.wait_for(
                            func(*args, **kwargs), timeout=effective_timeout
                        )
                    except asyncio.TimeoutError as exc:
                        if has_listeners:
                            _emit(
                                listeners,
                                EventType.TIMEOUT,
                                func_name,
                                detail=f"exceeded {effective_timeout}s",
                            )
                        raise ResilienceTimeoutError(
                            f"{func_name} exceeded timeout of {effective_timeout}s"
                        ) from exc
                else:
                    result = await func(*args, **kwargs)

                duration = (time.monotonic() - call_start) if track_duration else 0.0

                # Check retry_on_result predicate
                if retry_on_result is not None and retry_on_result(result):
                    if attempt < max_attempts:
                        retry_budget = self._retry_budget
                        if retry_budget is not None and not retry_budget.acquire():
                            if has_listeners:
                                _emit(
                                    listeners,
                                    EventType.RETRY_EXHAUSTED,
                                    func_name,
                                    attempt=attempt,
                                    detail="retry budget exhausted",
                                )
                            return result
                        delay = self._resolve_delay(attempt, result)
                        if deadline and time.monotonic() + delay >= deadline:
                            # No time left for another attempt: hand back the last result
                            if retry_budget is not None:
                                retry_budget.refund()
                            if has_listeners:
                                _emit(
                                    listeners,
                                    EventType.RETRY_EXHAUSTED,
                                    func_name,
                                    attempt=attempt,
                                    detail="total timeout budget exhausted",
                                )
                            return result
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
                    _emit(
                        listeners,
                        EventType.SUCCESS,
                        func_name,
                        attempt=attempt,
                        duration=duration,
                    )
                return result

            except Exception as exc:
                last_exc = exc
                duration = (time.monotonic() - call_start) if track_duration else 0.0

                # Circuit breaker tracking — ignored exceptions must never record failure
                if (
                    circuit_breaker is not None
                    and isinstance(exc, circuit_error_types)
                    and not (circuit_ignore_on and isinstance(exc, circuit_ignore_on))
                ):
                    new_state = circuit_breaker.record_failure(duration)
                    if new_state == CircuitState.OPEN and has_listeners:
                        _emit(listeners, EventType.CIRCUIT_OPEN, func_name, error=exc)

                # ignore_on: re-raise immediately, no retry, no fallback chain
                if ignore_on and isinstance(exc, ignore_on):
                    if has_listeners:
                        _emit(listeners, EventType.FAILURE, func_name, attempt=attempt, error=exc)
                    raise

                if retry_cfg is not None and attempt < max_attempts and isinstance(exc, retry_on):
                    # Check retry budget before retrying
                    retry_budget = self._retry_budget
                    if retry_budget is not None and not retry_budget.acquire():
                        if has_listeners:
                            _emit(
                                listeners,
                                EventType.RETRY_EXHAUSTED,
                                func_name,
                                attempt=attempt,
                                error=exc,
                                detail="retry budget exhausted",
                            )
                        if fallback_cfg is not None and isinstance(exc, fallback_on):
                            if has_listeners:
                                _emit(listeners, EventType.FALLBACK_USED, func_name, error=exc)
                            return await _apply_fallback_async(fallback_cfg, exc)
                        raise

                    delay = self._resolve_delay(attempt, exc)
                    if deadline and time.monotonic() + delay >= deadline:
                        # No time left for another attempt: stop instead of sleeping
                        if retry_budget is not None:
                            retry_budget.refund()
                        return await self._on_total_timeout(func_name, listeners, exc)
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
