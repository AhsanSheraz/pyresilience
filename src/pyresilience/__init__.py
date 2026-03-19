"""pyresilience — Unified resilience patterns for Python.

One decorator to combine retry, timeout, circuit breaker, fallback, and bulkhead.
Defines the full safety policy for a dependency, not just retries.
"""

from pyresilience._bulkhead import BulkheadFullError
from pyresilience._cache import AsyncResultCache, ResultCache
from pyresilience._circuit_breaker import CircuitBreaker
from pyresilience._compat import has_orjson, has_uvloop, install_uvloop
from pyresilience._decorator import resilient
from pyresilience._logging import JsonEventLogger, MetricsCollector
from pyresilience._presets import db_policy, http_policy, queue_policy, strict_policy
from pyresilience._rate_limiter import AsyncRateLimiter, RateLimiter, RateLimitExceededError
from pyresilience._registry import ResilienceRegistry
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
    RetryConfig,
    TimeoutConfig,
)

__version__ = "0.1.2"

__all__ = [
    "AsyncRateLimiter",
    "AsyncResultCache",
    "BulkheadConfig",
    "BulkheadFullError",
    "CacheConfig",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
    "EventType",
    "FallbackConfig",
    "JsonEventLogger",
    "MetricsCollector",
    "RateLimitExceededError",
    "RateLimiter",
    "RateLimiterConfig",
    "ResilienceConfig",
    "ResilienceEvent",
    "ResilienceListener",
    "ResilienceRegistry",
    "ResultCache",
    "RetryConfig",
    "TimeoutConfig",
    "db_policy",
    "has_orjson",
    "has_uvloop",
    "http_policy",
    "install_uvloop",
    "queue_policy",
    "resilient",
    "strict_policy",
]
