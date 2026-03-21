"""pyresilience — Unified resilience patterns for Python.

One decorator to combine retry, timeout, circuit breaker, fallback, and bulkhead.
Defines the full safety policy for a dependency, not just retries.
"""

from pyresilience._cache import AsyncResultCache, ResultCache
from pyresilience._circuit_breaker import CircuitBreaker
from pyresilience._compat import has_orjson, has_uvloop, install_uvloop
from pyresilience._decorator import resilient
from pyresilience._exceptions import (
    BulkheadFullError,
    CircuitOpenError,
    ResilienceError,
    ResilienceTimeoutError,
)
from pyresilience._executor import enable_in_flight_tracking, get_in_flight_count, shutdown
from pyresilience._health import health_check
from pyresilience._logging import JsonEventLogger, MetricsCollector, resilience_context
from pyresilience._presets import db_policy, http_policy, queue_policy, strict_policy
from pyresilience._rate_limiter import AsyncRateLimiter, RateLimiter, RateLimitExceededError
from pyresilience._registry import ResilienceRegistry
from pyresilience._retry_budget import RetryBudget
from pyresilience._types import (
    BulkheadConfig,
    CacheConfig,
    CircuitBreakerConfig,
    CircuitState,
    EventType,
    FallbackConfig,
    RateLimiterConfig,
    ResilienceConfig,
    ResilienceEvent,
    ResilienceListener,
    RetryBudgetConfig,
    RetryConfig,
    TimeoutConfig,
)

__version__ = "0.3.2"

__all__ = [
    "AsyncRateLimiter",
    "AsyncResultCache",
    "BulkheadConfig",
    "BulkheadFullError",
    "CacheConfig",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitOpenError",
    "CircuitState",
    "EventType",
    "FallbackConfig",
    "JsonEventLogger",
    "MetricsCollector",
    "RateLimitExceededError",
    "RateLimiter",
    "RateLimiterConfig",
    "ResilienceConfig",
    "ResilienceError",
    "ResilienceEvent",
    "ResilienceListener",
    "ResilienceRegistry",
    "ResilienceTimeoutError",
    "ResultCache",
    "RetryBudget",
    "RetryBudgetConfig",
    "RetryConfig",
    "TimeoutConfig",
    "db_policy",
    "enable_in_flight_tracking",
    "get_in_flight_count",
    "has_orjson",
    "has_uvloop",
    "health_check",
    "http_policy",
    "install_uvloop",
    "queue_policy",
    "resilience_context",
    "resilient",
    "shutdown",
    "strict_policy",
]
