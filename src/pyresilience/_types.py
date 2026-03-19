"""Type definitions for pyresilience."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence, Type, Union


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


@dataclass(frozen=True)
class ResilienceEvent:
    """An event emitted by a resilience component."""

    event_type: EventType
    function_name: str
    attempt: int = 0
    error: Optional[BaseException] = None
    detail: str = ""


# Callback type for event listeners
ResilienceListener = Callable[[ResilienceEvent], None]


@dataclass
class RetryConfig:
    """Configuration for retry behavior.

    Args:
        max_attempts: Maximum number of attempts (including the first call).
        delay: Initial delay between retries in seconds.
        backoff_factor: Multiplier applied to delay after each retry.
        max_delay: Maximum delay between retries in seconds.
        jitter: If True, add random jitter to delay.
        retry_on: Exception types to retry on. Defaults to (Exception,).
        retry_on_result: Optional predicate function that receives the result and
            returns True if the call should be retried. Useful for retrying on
            specific return values (e.g., HTTP 429 responses) without raising exceptions.
    """

    max_attempts: int = 3
    delay: float = 1.0
    backoff_factor: float = 2.0
    max_delay: float = 60.0
    jitter: bool = True
    retry_on: Sequence[Type[BaseException]] = (Exception,)
    retry_on_result: Optional[Callable[[Any], bool]] = None


@dataclass
class TimeoutConfig:
    """Configuration for timeout behavior.

    Args:
        seconds: Maximum time in seconds before a call is aborted.
        pool_size: Thread pool size for sync timeouts. Defaults to 4.
    """

    seconds: float = 30.0
    pool_size: int = 4


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


@dataclass
class FallbackConfig:
    """Configuration for fallback behavior.

    Args:
        handler: A callable that receives the exception and returns a fallback value,
                 or a static value to return on failure.
        fallback_on: Exception types that trigger the fallback.
    """

    handler: Union[Callable[..., Any], Any] = None
    fallback_on: Sequence[Type[BaseException]] = (Exception,)


@dataclass
class BulkheadConfig:
    """Configuration for bulkhead (concurrency limiting) behavior.

    Args:
        max_concurrent: Maximum number of concurrent executions.
        max_wait: Maximum seconds to wait for a slot. 0 means fail immediately.
    """

    max_concurrent: int = 10
    max_wait: float = 0.0


@dataclass
class RateLimiterConfig:
    """Configuration for rate limiting behavior.

    Args:
        max_calls: Maximum number of calls allowed per period.
        period: Time period in seconds.
        max_wait: Maximum seconds to wait for a token. 0 means fail immediately.
    """

    max_calls: int = 10
    period: float = 1.0
    max_wait: float = 0.0


@dataclass
class CacheConfig:
    """Configuration for result caching behavior.

    Args:
        max_size: Maximum number of cached entries (LRU eviction).
        ttl: Time-to-live in seconds. 0 means no expiration.
    """

    max_size: int = 256
    ttl: float = 300.0


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
    listeners: list[ResilienceListener] = field(default_factory=list)
