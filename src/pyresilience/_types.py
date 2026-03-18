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
    """

    max_attempts: int = 3
    delay: float = 1.0
    backoff_factor: float = 2.0
    max_delay: float = 60.0
    jitter: bool = True
    retry_on: Sequence[Type[BaseException]] = (Exception,)


@dataclass
class TimeoutConfig:
    """Configuration for timeout behavior.

    Args:
        seconds: Maximum time in seconds before a call is aborted.
    """

    seconds: float = 30.0


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior.

    Args:
        failure_threshold: Number of consecutive failures before opening the circuit.
        recovery_timeout: Seconds to wait before transitioning to half-open.
        success_threshold: Consecutive successes in half-open needed to close the circuit.
        error_types: Exception types that count as failures.
    """

    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    success_threshold: int = 2
    error_types: Sequence[Type[BaseException]] = (Exception,)


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
class ResilienceConfig:
    """Combined resilience configuration for the @resilient decorator.

    All fields are optional. Only enabled patterns are applied.
    """

    retry: Optional[RetryConfig] = None
    timeout: Optional[TimeoutConfig] = None
    circuit_breaker: Optional[CircuitBreakerConfig] = None
    fallback: Optional[FallbackConfig] = None
    bulkhead: Optional[BulkheadConfig] = None
    listeners: list[ResilienceListener] = field(default_factory=list)
