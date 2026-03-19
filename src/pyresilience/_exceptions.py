"""Exception hierarchy for pyresilience.

All rejection errors inherit from ResilienceError, allowing users to catch
any pyresilience-specific rejection with a single except clause.
"""

from __future__ import annotations


class ResilienceError(Exception):
    """Base for all pyresilience errors."""


class CircuitOpenError(ResilienceError):
    """Raised when the circuit breaker is open and rejecting requests."""


class BulkheadFullError(ResilienceError):
    """Raised when the bulkhead has no available slots."""


class RateLimitExceededError(ResilienceError):
    """Raised when a call is rejected by the rate limiter."""


class ResilienceTimeoutError(ResilienceError, TimeoutError):
    """Raised when a call exceeds its timeout.

    Inherits from both ResilienceError and TimeoutError for backward
    compatibility with code that catches TimeoutError.
    """
