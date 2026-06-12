"""Dependency-specific resilience presets.

Instead of tuning low-level knobs, use opinionated presets for common
integration patterns. This is what makes pyresilience more than
"another retry decorator."

Usage::

    from pyresilience import resilient
    from pyresilience.presets import http_policy, db_policy, queue_policy

    @resilient(**http_policy())
    def call_api(url: str) -> dict:
        return requests.get(url).json()

    @resilient(**db_policy())
    def query_db(sql: str) -> list:
        return cursor.execute(sql).fetchall()

    @resilient(**queue_policy())
    async def publish_message(msg: dict) -> None:
        await producer.send(msg)
"""

from __future__ import annotations

from typing import Any, Optional, Sequence, Type

from pyresilience._types import (
    BulkheadConfig,
    CacheConfig,
    CircuitBreakerConfig,
    FallbackConfig,
    RateLimiterConfig,
    ResilienceListener,
    RetryConfig,
    TimeoutConfig,
)


def http_policy(
    *,
    timeout_seconds: float = 10.0,
    max_attempts: int = 3,
    retry_delay: float = 0.5,
    circuit_failure_threshold: int = 5,
    circuit_recovery_seconds: float = 30.0,
    max_concurrent: Optional[int] = None,
    rate_limit: Optional[RateLimiterConfig] = None,
    cache: Optional[CacheConfig] = None,
    fallback: Optional[FallbackConfig] = None,
    listeners: Optional[list[ResilienceListener]] = None,
    retry_on: Optional[Sequence[Type[BaseException]]] = None,
) -> dict[str, Any]:
    """Resilience policy optimized for HTTP API calls.

    Defaults:
    - 10s timeout (APIs should respond quickly)
    - 3 retries with 0.5s initial delay, exponential backoff
    - Circuit breaker: opens after 5 failures, 30s recovery
    - Jitter enabled to avoid thundering herd
    - Only retries on Exception (not KeyboardInterrupt etc.)

    Args:
        timeout_seconds: Max time per request.
        max_attempts: Total attempts (including first).
        retry_delay: Initial retry delay in seconds.
        circuit_failure_threshold: Failures before circuit opens.
        circuit_recovery_seconds: Time before trying again after circuit opens.
        max_concurrent: Optional concurrency limit (bulkhead).
        fallback: Optional fallback config.
        listeners: Optional event listeners.
        retry_on: Exception types to retry on. Defaults to (Exception,).
    """
    policy: dict[str, Any] = {
        "retry": RetryConfig(
            max_attempts=max_attempts,
            delay=retry_delay,
            backoff_factor=2.0,
            max_delay=30.0,
            jitter=True,
            retry_on=tuple(retry_on) if retry_on else (Exception,),
        ),
        "timeout": TimeoutConfig(seconds=timeout_seconds),
        "circuit_breaker": CircuitBreakerConfig(
            failure_threshold=circuit_failure_threshold,
            recovery_timeout=circuit_recovery_seconds,
            success_threshold=2,
        ),
    }
    if max_concurrent is not None:
        policy["bulkhead"] = BulkheadConfig(max_concurrent=max_concurrent)
    if rate_limit is not None:
        policy["rate_limiter"] = rate_limit
    if cache is not None:
        policy["cache"] = cache
    if fallback is not None:
        policy["fallback"] = fallback
    if listeners is not None:
        policy["listeners"] = listeners
    return policy


def db_policy(
    *,
    timeout_seconds: float = 30.0,
    max_attempts: int = 2,
    retry_delay: float = 1.0,
    circuit_failure_threshold: int = 3,
    circuit_recovery_seconds: float = 60.0,
    max_concurrent: int = 10,
    fallback: Optional[FallbackConfig] = None,
    listeners: Optional[list[ResilienceListener]] = None,
    retry_on: Optional[Sequence[Type[BaseException]]] = None,
) -> dict[str, Any]:
    """Resilience policy optimized for database calls.

    Defaults:
    - 30s timeout (queries can be slower)
    - 2 retries with 1s delay (fewer retries to avoid connection pile-up)
    - Circuit breaker: opens after 3 failures, 60s recovery
    - Bulkhead: max 10 concurrent connections (protect connection pool)
    - Less aggressive backoff than HTTP

    Args:
        timeout_seconds: Max time per query.
        max_attempts: Total attempts (including first).
        retry_delay: Initial retry delay in seconds.
        circuit_failure_threshold: Failures before circuit opens.
        circuit_recovery_seconds: Time before trying again after circuit opens.
        max_concurrent: Max concurrent database calls (bulkhead).
        fallback: Optional fallback config.
        listeners: Optional event listeners.
        retry_on: Exception types to retry on. Defaults to (Exception,).
    """
    policy: dict[str, Any] = {
        "retry": RetryConfig(
            max_attempts=max_attempts,
            delay=retry_delay,
            backoff_factor=1.5,
            max_delay=10.0,
            jitter=True,
            retry_on=tuple(retry_on) if retry_on else (Exception,),
        ),
        "timeout": TimeoutConfig(seconds=timeout_seconds),
        "circuit_breaker": CircuitBreakerConfig(
            failure_threshold=circuit_failure_threshold,
            recovery_timeout=circuit_recovery_seconds,
            success_threshold=1,
        ),
        "bulkhead": BulkheadConfig(max_concurrent=max_concurrent, max_wait=5.0),
    }
    if fallback is not None:
        policy["fallback"] = fallback
    if listeners is not None:
        policy["listeners"] = listeners
    return policy


def queue_policy(
    *,
    timeout_seconds: float = 15.0,
    max_attempts: int = 5,
    retry_delay: float = 2.0,
    circuit_failure_threshold: int = 10,
    circuit_recovery_seconds: float = 60.0,
    max_concurrent: Optional[int] = None,
    fallback: Optional[FallbackConfig] = None,
    listeners: Optional[list[ResilienceListener]] = None,
    retry_on: Optional[Sequence[Type[BaseException]]] = None,
) -> dict[str, Any]:
    """Resilience policy optimized for message queue producers/consumers.

    Defaults:
    - 15s timeout
    - 5 retries with 2s delay (queues are often transient-failure-heavy)
    - Circuit breaker: opens after 10 failures, 60s recovery (queues are bursty)
    - More aggressive retry (messages should eventually be delivered)
    - Higher failure threshold (queue brokers have more transient issues)

    Args:
        timeout_seconds: Max time per publish/consume.
        max_attempts: Total attempts (including first).
        retry_delay: Initial retry delay in seconds.
        circuit_failure_threshold: Failures before circuit opens.
        circuit_recovery_seconds: Time before trying again after circuit opens.
        max_concurrent: Optional concurrency limit (bulkhead).
        fallback: Optional fallback config.
        listeners: Optional event listeners.
        retry_on: Exception types to retry on. Defaults to (Exception,).
    """
    policy: dict[str, Any] = {
        "retry": RetryConfig(
            max_attempts=max_attempts,
            delay=retry_delay,
            backoff_factor=2.0,
            max_delay=60.0,
            jitter=True,
            retry_on=tuple(retry_on) if retry_on else (Exception,),
        ),
        "timeout": TimeoutConfig(seconds=timeout_seconds),
        "circuit_breaker": CircuitBreakerConfig(
            failure_threshold=circuit_failure_threshold,
            recovery_timeout=circuit_recovery_seconds,
            success_threshold=3,
        ),
    }
    if max_concurrent is not None:
        policy["bulkhead"] = BulkheadConfig(max_concurrent=max_concurrent)
    if fallback is not None:
        policy["fallback"] = fallback
    if listeners is not None:
        policy["listeners"] = listeners
    return policy


def llm_policy(
    *,
    timeout_seconds: float = 60.0,
    max_attempts: int = 4,
    retry_delay: float = 1.0,
    max_calls: int = 60,
    period: float = 60.0,
    circuit_failure_threshold: int = 5,
    circuit_recovery_seconds: float = 30.0,
    max_concurrent: Optional[int] = None,
    retry_on_status_codes: Sequence[int] = (429, 500, 502, 503, 504),
    retry_after_max_wait: float = 60.0,
    fallback: Optional[FallbackConfig] = None,
    listeners: Optional[list[ResilienceListener]] = None,
    retry_on: Optional[Sequence[Type[BaseException]]] = None,
    ignore_on: Optional[Sequence[Type[BaseException]]] = None,
) -> dict[str, Any]:
    """Resilience policy optimized for LLM/HTTP API calls with 429/Retry-After-aware retrying.

    Designed for calls to LLM providers (OpenAI, Anthropic, etc.) and other HTTP APIs
    that use rate-limiting (HTTP 429) and Retry-After headers. Includes client-side
    rate limiting to stay within provider quotas and a circuit breaker to avoid
    hammering a degraded backend.

    Defaults:
    - 60s timeout (LLM inference can be slow)
    - 4 total attempts (1 initial + 3 retries)
    - 1s initial retry delay, honouring Retry-After headers up to ``retry_after_max_wait``
    - Retries on HTTP status codes 429, 500, 502, 503, 504 via result predicate
    - Client-side rate limit: 60 calls per 60s (1 RPS by default)
    - Circuit breaker: opens after 5 failures, 30s recovery
    - Retry-After header parsing: delays respect the server-supplied value

    Args:
        timeout_seconds: Max time per LLM call. Defaults to 60.0.
        max_attempts: Total attempts including the first call. Defaults to 4.
        retry_delay: Initial retry delay in seconds. Defaults to 1.0.
        max_calls: Max calls allowed within ``period`` (rate limiter). Defaults to 60.
        period: Rate-limiter window in seconds. Defaults to 60.0.
        circuit_failure_threshold: Consecutive failures before circuit opens. Defaults to 5.
        circuit_recovery_seconds: Seconds before retrying after circuit opens. Defaults to 30.0.
        max_concurrent: Optional concurrency limit (bulkhead). None disables it.
        retry_on_status_codes: HTTP status codes that trigger a retry via result predicate.
            Defaults to (429, 500, 502, 503, 504).
        retry_after_max_wait: Upper bound (seconds) for Retry-After-derived delays.
            Defaults to 60.0.
        fallback: Optional fallback config.
        listeners: Optional event listeners.
        retry_on: Additional exception types to retry on. Defaults to (Exception,).
        ignore_on: Exception types that are never retried and never counted as circuit failures.
            Useful for terminal errors like auth failures or invalid-request errors.
    """
    # Lazy import — contrib.http is an optional dependency; avoids import at module load time
    from pyresilience.contrib.http import retry_after_delay, retry_on_status

    retry_config = RetryConfig(
        max_attempts=max_attempts,
        delay=retry_delay,
        max_delay=retry_after_max_wait,
        retry_on_result=retry_on_status(*retry_on_status_codes),
        delay_func=retry_after_delay(max_wait=retry_after_max_wait),
        retry_on=tuple(retry_on) if retry_on is not None else (Exception,),
        ignore_on=tuple(ignore_on) if ignore_on is not None else (),
    )
    circuit_breaker_config = CircuitBreakerConfig(
        failure_threshold=circuit_failure_threshold,
        recovery_timeout=circuit_recovery_seconds,
        ignore_on=tuple(ignore_on) if ignore_on is not None else (),
    )

    policy: dict[str, Any] = {
        "retry": retry_config,
        "timeout": TimeoutConfig(seconds=timeout_seconds),
        "circuit_breaker": circuit_breaker_config,
        "rate_limiter": RateLimiterConfig(max_calls=max_calls, period=period),
    }
    if max_concurrent is not None:
        policy["bulkhead"] = BulkheadConfig(max_concurrent=max_concurrent)
    if fallback is not None:
        policy["fallback"] = fallback
    if listeners is not None:
        policy["listeners"] = listeners
    return policy


def strict_policy(
    *,
    timeout_seconds: float = 5.0,
    max_attempts: int = 1,
    circuit_failure_threshold: int = 3,
    circuit_recovery_seconds: float = 60.0,
    listeners: Optional[list[ResilienceListener]] = None,
) -> dict[str, Any]:
    """Strict resilience policy — fail fast, minimal retries.

    Use for latency-sensitive paths where slow is worse than failing.

    Defaults:
    - 5s timeout
    - No retries (1 total attempt) by default
    - Circuit breaker: opens after 3 failures, 60s recovery
    - No jitter (fail fast)
    """
    policy: dict[str, Any] = {
        "retry": RetryConfig(
            max_attempts=max_attempts,
            delay=0.1,
            backoff_factor=1.0,
            max_delay=0.5,
            jitter=False,
        ),
        "timeout": TimeoutConfig(seconds=timeout_seconds),
        "circuit_breaker": CircuitBreakerConfig(
            failure_threshold=circuit_failure_threshold,
            recovery_timeout=circuit_recovery_seconds,
            success_threshold=1,
        ),
    }
    if listeners is not None:
        policy["listeners"] = listeners
    return policy
