"""pyresilience — Unified resilience patterns for Python.

One decorator to combine retry, timeout, circuit breaker, fallback, and bulkhead.
"""

from pyresilience._bulkhead import BulkheadFullError
from pyresilience._circuit_breaker import CircuitBreaker
from pyresilience._decorator import resilient
from pyresilience._types import (
    BulkheadConfig,
    CircuitBreakerConfig,
    CircuitState,
    EventType,
    FallbackConfig,
    ResilienceConfig,
    ResilienceEvent,
    ResilienceListener,
    RetryConfig,
    TimeoutConfig,
)

__version__ = "0.1.0"

__all__ = [
    "BulkheadConfig",
    "BulkheadFullError",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
    "EventType",
    "FallbackConfig",
    "ResilienceConfig",
    "ResilienceEvent",
    "ResilienceListener",
    "RetryConfig",
    "TimeoutConfig",
    "resilient",
]
