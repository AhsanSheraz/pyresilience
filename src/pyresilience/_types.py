"""Type definitions for pyresilience."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional, Sequence, Type, Union

if TYPE_CHECKING:
    from pyresilience._backend import StateBackend

# Name of the primary rate limit (``RateLimiterConfig.max_calls`` per ``period``)
PRIMARY_LIMIT_NAME = "calls"


class CircuitState(enum.Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class EventType(enum.Enum):
    """Types of resilience events."""

    RETRY = "retry"
    RETRY_EXHAUSTED = "retry_exhausted"
    TIMEOUT = "timeout"
    CIRCUIT_OPEN = "circuit_open"
    CIRCUIT_HALF_OPEN = "circuit_half_open"
    CIRCUIT_CLOSED = "circuit_closed"
    FALLBACK_USED = "fallback_used"
    BULKHEAD_REJECTED = "bulkhead_rejected"
    RATE_LIMITED = "rate_limited"
    CACHE_HIT = "cache_hit"
    CACHE_MISS = "cache_miss"
    SLOW_CALL = "slow_call"
    SUCCESS = "success"
    FAILURE = "failure"
    COOLDOWN = "cooldown"


@dataclass(frozen=True)
class ResilienceEvent:
    """An event emitted by a resilience component."""

    event_type: EventType
    function_name: str
    attempt: int = 0
    error: Optional[BaseException] = None
    detail: str = ""
    context: Optional[dict[str, Any]] = None
    duration: Optional[float] = None


# Callback type for event listeners
ResilienceListener = Callable[[ResilienceEvent], None]


@dataclass
class RetryConfig:
    """Configuration for retry behavior.

    Args:
        max_attempts: Total number of execution attempts (including the initial call).
            For example, max_attempts=3 means 1 initial call + 2 retries.
        delay: Initial delay between retries in seconds.
        backoff_factor: Multiplier applied to delay after each retry.
        max_delay: Maximum delay between retries in seconds.
        jitter: If True, add random jitter to delay.
        retry_on: Exception types to retry on. Defaults to (Exception,).
        retry_on_result: Optional predicate function that receives the result and
            returns True if the call should be retried. Useful for retrying on
            specific return values (e.g., HTTP 429 responses) without raising exceptions.
        ignore_on: Exception types that are never retried, even if they match retry_on.
            Takes precedence over retry_on. Useful for terminal client errors
            (auth, quota, validation).
        delay_func: Optional callable (attempt, trigger) -> delay seconds or None.
            trigger is the raised exception (exception-driven retries) or the raw
            retry_on_result value (result-driven retries). Return None to fall back to
            exponential backoff. Non-None returns are clamped to [0, max_delay].
            Enables honoring HTTP Retry-After.
    """

    max_attempts: int = 3
    delay: float = 1.0
    backoff_factor: float = 2.0
    max_delay: float = 60.0
    jitter: bool = True
    retry_on: Sequence[Type[BaseException]] = (Exception,)
    retry_on_result: Optional[Callable[[Any], bool]] = None
    ignore_on: Sequence[Type[BaseException]] = ()
    delay_func: Optional[Callable[[int, Union[BaseException, Any]], Optional[float]]] = None

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.delay < 0:
            raise ValueError("delay must be >= 0")
        if self.max_delay < 0:
            raise ValueError("max_delay must be >= 0")


@dataclass
class TimeoutConfig:
    """Configuration for timeout behavior.

    Args:
        seconds: Maximum time in seconds before a call is aborted.
        pool_size: Thread pool size for sync timeouts. Defaults to 4.
        per_attempt: If True (default), ``seconds`` applies to each retry attempt
            individually. If False, ``seconds`` is one deadline for the whole call,
            retries and retry waits included.
        total_seconds: Optional overall deadline for the whole call (all attempts plus
            retry waits), enforced together with the per-attempt ``seconds``. Each
            attempt gets ``min(seconds, time left)``. Requires ``per_attempt=True``.
            When the time left cannot cover the next retry wait, the call stops
            retrying and raises ``ResilienceTimeoutError``.
        stream_idle_seconds: Optional idle limit for streamed results. When the
            function returns an iterator or async iterator, waiting longer than this
            for the first item or between two items raises ``ResilienceTimeoutError``.
    """

    seconds: float = 30.0
    pool_size: int = 4
    per_attempt: bool = True
    total_seconds: Optional[float] = None
    stream_idle_seconds: Optional[float] = None

    def __post_init__(self) -> None:
        if self.seconds <= 0:
            raise ValueError("seconds must be > 0")
        if self.pool_size < 1:
            raise ValueError("pool_size must be >= 1")
        if self.total_seconds is not None:
            if self.total_seconds <= 0:
                raise ValueError("total_seconds must be > 0")
            if not self.per_attempt:
                raise ValueError("total_seconds requires per_attempt=True")
        if self.stream_idle_seconds is not None and self.stream_idle_seconds <= 0:
            raise ValueError("stream_idle_seconds must be > 0")


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior.

    Supports two modes:
    - **Consecutive count** (default): Opens after ``failure_threshold`` consecutive failures.
    - **Sliding window**: Opens when failure rate exceeds ``failure_rate_threshold`` within
      the last ``sliding_window_size`` calls. Enable by setting ``sliding_window_size > 0``.

    Args:
        failure_threshold: Consecutive failures before opening (used when sliding_window_size=0).
        recovery_timeout: Seconds to wait before transitioning to half-open.
        success_threshold: Consecutive successes in half-open needed to close the circuit.
        error_types: Exception types that count as failures.
        sliding_window_size: Number of recent calls to track. 0 disables sliding window
            and uses consecutive failure count instead.
        failure_rate_threshold: Failure rate (0.0-1.0) that triggers opening when using
            sliding window. E.g., 0.5 means "open at 50% failure rate".
        minimum_calls: Minimum calls in the sliding window before the failure rate is
            evaluated. Prevents opening on the first few calls.
        slow_call_duration: Calls exceeding this duration (seconds) count as slow calls.
            0.0 disables slow call detection.
        slow_call_rate_threshold: Rate of slow calls (0.0-1.0) that triggers opening.
            E.g., 0.5 means "open when 50% of calls are slow".
        ignore_on: Exception types that never count as circuit failures, even if they
            match error_types. Takes precedence over error_types.
    """

    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    success_threshold: int = 2
    error_types: Sequence[Type[BaseException]] = (Exception,)
    sliding_window_size: int = 0
    failure_rate_threshold: float = 0.5
    minimum_calls: int = 0
    slow_call_duration: float = 0.0
    slow_call_rate_threshold: float = 1.0
    ignore_on: Sequence[Type[BaseException]] = ()

    def __post_init__(self) -> None:
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if self.recovery_timeout < 0:
            raise ValueError("recovery_timeout must be >= 0")
        if not 0.0 <= self.failure_rate_threshold <= 1.0:
            raise ValueError("failure_rate_threshold must be between 0.0 and 1.0")


@dataclass
class FallbackConfig:
    """Configuration for fallback behavior.

    Order for a failing call: each alternative in turn, then the handler. If
    neither produces a value, the last error is raised.

    Args:
        handler: A callable that receives the exception and returns a fallback value,
                 or a static value to return on failure.
        fallback_on: Exception types that trigger the fallback.
        alternatives: Callables tried in order with the original arguments when the
            call fails, for example the same request against another provider or
            model. The first one that succeeds supplies the result. Use async
            callables with async functions.
        cooldown: Seconds a target (the decorated function or an alternative) is
            skipped after ``cooldown_threshold`` consecutive failures. While the
            decorated function cools down, calls go straight to the alternatives and
            the handler. 0 (default) disables cooldown. A cooldown never fails a call
            by itself: when nothing else is available, the function is called anyway.
        cooldown_threshold: Consecutive failures that start a cooldown.
    """

    handler: Union[Callable[..., Any], Any] = None
    fallback_on: Sequence[Type[BaseException]] = (Exception,)
    alternatives: Sequence[Callable[..., Any]] = ()
    cooldown: float = 0.0
    cooldown_threshold: int = 1

    def __post_init__(self) -> None:
        if self.cooldown < 0:
            raise ValueError("cooldown must be >= 0")
        if self.cooldown_threshold < 1:
            raise ValueError("cooldown_threshold must be >= 1")
        if self.handler is None and not self.alternatives:
            # When nothing can produce a fallback value, disable fallback triggers
            # to prevent silently returning None on exceptions
            self.fallback_on = ()


@dataclass
class BulkheadConfig:
    """Configuration for bulkhead (concurrency limiting) behavior.

    Args:
        max_concurrent: Maximum number of concurrent executions.
        max_wait: Maximum seconds to wait for a slot. 0 means fail immediately.
    """

    max_concurrent: int = 10
    max_wait: float = 0.0

    def __post_init__(self) -> None:
        if self.max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")


@dataclass
class RateLimit:
    """An additional rate limit enforced together with the primary limit.

    Use it for a second window (per minute and per day) or a second resource
    (requests and tokens).

    Args:
        max_units: Units allowed per period (calls, tokens, bytes, ...).
        period: Time period in seconds.
        name: Name used in events, errors and server feedback. Defaults to
            ``limit<N>`` (``limit1`` for the first additional limit).
        cost: Optional callable that receives the call's ``*args, **kwargs`` and
            returns how many units the call consumes. Defaults to 1 unit per call.
        actual_cost: Optional callable that receives the call's result and returns
            the units really consumed, or None to keep the estimate. The difference
            to ``cost`` is given back or charged after the call.
    """

    max_units: float
    period: float
    name: str = ""
    cost: Optional[Callable[..., float]] = None
    actual_cost: Optional[Callable[[Any], Optional[float]]] = None

    def __post_init__(self) -> None:
        if self.max_units <= 0:
            raise ValueError("max_units must be > 0")
        if self.period <= 0:
            raise ValueError("period must be > 0")


@dataclass(frozen=True)
class RateLimitFeedback:
    """What the server reported about its own limits.

    Returned by ``RateLimiterConfig.feedback`` to steer the client-side limiter.

    Args:
        retry_after: Seconds during which no call should be sent. Pauses the limiter.
        remaining: Limit name -> units the server says are left. The local level of
            that limit is lowered to this value when it is higher; it is never raised.
    """

    retry_after: Optional[float] = None
    remaining: Optional[Mapping[str, float]] = None


@dataclass
class RateLimiterConfig:
    """Configuration for rate limiting behavior.

    The primary limit is ``max_calls`` per ``period`` and is named ``"calls"``.
    A call proceeds only when every limit has capacity; nothing is consumed when
    any limit rejects it.

    Args:
        max_calls: Maximum number of calls allowed per period.
        period: Time period in seconds.
        max_wait: Maximum seconds to wait for capacity. 0 means fail immediately.
        cost: Optional callable that receives the call's ``*args, **kwargs`` and
            returns how many units of the primary limit the call consumes.
            Defaults to 1 unit per call.
        actual_cost: Optional callable that receives the call's result and returns
            the units of the primary limit really consumed, or None to keep the
            estimate.
        limits: Additional limits enforced together with the primary limit.
        feedback: Optional callable that receives each attempt's result or raised
            exception and returns a ``RateLimitFeedback`` (or None). Lets the limiter
            follow ``Retry-After`` and rate-limit headers; see
            ``pyresilience.contrib.http.rate_limit_feedback``.
        charge_retries: If True, every retry attempt is debited against the limits
            without waiting, so retries slow down later calls. If False (default),
            capacity is taken once per call.
    """

    max_calls: int = 10
    period: float = 1.0
    max_wait: float = 0.0
    cost: Optional[Callable[..., float]] = None
    actual_cost: Optional[Callable[[Any], Optional[float]]] = None
    limits: Sequence[RateLimit] = ()
    feedback: Optional[Callable[[Any], Optional[RateLimitFeedback]]] = None
    charge_retries: bool = False

    def __post_init__(self) -> None:
        if self.max_calls < 1:
            raise ValueError("max_calls must be >= 1")
        if self.period <= 0:
            raise ValueError("period must be > 0")
        names = [PRIMARY_LIMIT_NAME]
        for index, limit in enumerate(self.limits, start=1):
            names.append(limit.name or f"limit{index}")
        if len(set(names)) != len(names):
            raise ValueError("limit names must be unique")


@dataclass
class CacheConfig:
    """Configuration for result caching behavior.

    Args:
        max_size: Maximum number of cached entries (LRU eviction).
        ttl: Time-to-live in seconds. 0 means no expiration.
    """

    max_size: int = 256
    ttl: float = 300.0

    def __post_init__(self) -> None:
        if self.max_size < 1:
            raise ValueError("max_size must be >= 1")
        if self.ttl < 0:
            raise ValueError("ttl must be >= 0")


@dataclass
class RetryBudgetConfig:
    """Configuration for global retry budget.

    Limits total retry attempts across all decorated functions using a token bucket.

    Args:
        max_retries: Maximum retry tokens in the bucket.
        refill_rate: Tokens refilled per second.
    """

    max_retries: int = 100
    refill_rate: float = 10.0

    def __post_init__(self) -> None:
        if self.max_retries < 1:
            raise ValueError("max_retries must be >= 1")
        if self.refill_rate <= 0:
            raise ValueError("refill_rate must be > 0")


@dataclass
class SharedStateConfig:
    """Share resilience state between processes through a state backend.

    Without it, every process keeps its own circuit breaker, rate limits and retry
    budget, so limits and thresholds are multiplied by the number of processes.

    - Rate limits become exact across processes: each call is counted in the
      backend (fixed windows of one ``period``) on top of the local limiter.
    - Circuit breaker and retry budget are exchanged in the background every
      ``sync_interval`` seconds; the call path does no backend I/O for them.

    Args:
        backend: Where the shared state lives, for example ``InMemoryBackend()`` or
            ``pyresilience.contrib.redis.RedisBackend(client)``.
        key: Name of the state in the backend. Everything that uses the same
            backend and key shares state. Defaults to the registry name, or to
            ``module.qualname`` of the function decorated with ``@resilient``.
        sync_interval: Seconds between background passes. 0 starts no background
            thread; call ``sync_now()`` yourself.
        fail_open: What rate limiting does while the backend cannot be reached.
            True (default): keep serving on this process's local limit. False:
            reject calls with ``RateLimitExceededError``. Circuit breaker and retry
            budget always keep working on local state.
    """

    backend: StateBackend
    key: str = ""
    sync_interval: float = 1.0
    fail_open: bool = True
    _syncer: Any = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.sync_interval < 0:
            raise ValueError("sync_interval must be >= 0")

    def sync_now(self) -> None:
        """Run one synchronisation pass now for everything bound to this config."""
        from pyresilience._shared import _syncer_for

        _syncer_for(self).sync_now()


@dataclass
class ResilienceConfig:
    """Combined resilience configuration for the @resilient decorator.

    All fields are optional. Only enabled patterns are applied.
    """

    retry: Optional[RetryConfig] = None
    timeout: Optional[TimeoutConfig] = None
    circuit_breaker: Optional[CircuitBreakerConfig] = None
    fallback: Optional[FallbackConfig] = None
    bulkhead: Optional[BulkheadConfig] = None
    rate_limiter: Optional[RateLimiterConfig] = None
    cache: Optional[CacheConfig] = None
    retry_budget: Optional[RetryBudgetConfig] = None
    listeners: list[ResilienceListener] = field(default_factory=list)
    shared_state: Optional[SharedStateConfig] = None
