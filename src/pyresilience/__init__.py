"""pyresilience — Unified resilience patterns for Python.

One decorator to combine retry, timeout, circuit breaker, fallback, and bulkhead.
Defines the full safety policy for a dependency, not just retries.
"""

from pyresilience._backend import InMemoryBackend, StateBackend
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
from pyresilience._presets import db_policy, http_policy, llm_policy, queue_policy, strict_policy
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
    RateLimit,
    RateLimiterConfig,
    RateLimitFeedback,
    ResilienceConfig,
    ResilienceEvent,
    ResilienceListener,
    RetryBudgetConfig,
    RetryConfig,
    SharedStateConfig,
    TimeoutConfig,
)

__version__ = "0.5.0"

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
    "InMemoryBackend",
    "JsonEventLogger",
    "MetricsCollector",
    "RateLimit",
    "RateLimitExceededError",
    "RateLimitFeedback",
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
    "SharedStateConfig",
    "StateBackend",
    "TimeoutConfig",
    "db_policy",
    "enable_in_flight_tracking",
    "get_in_flight_count",
    "has_orjson",
    "has_uvloop",
    "health_check",
    "http_policy",
    "install_uvloop",
    "llm_policy",
    "queue_policy",
    "resilience_context",
    "resilient",
    "shutdown",
    "strict_policy",
]
