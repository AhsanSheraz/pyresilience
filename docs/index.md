# pyresilience

**Unified resilience patterns for Python** — retry, circuit breaker, timeout, fallback, bulkhead, rate limiter, and cache in one decorator.

pyresilience is Python's equivalent of Java's [Resilience4j](https://resilience4j.readme.io/). Instead of stacking multiple decorators from different libraries, define your entire resilience policy in a single `@resilient()` call.

## Why pyresilience?

In Java, Resilience4j is the standard for fault tolerance — it combines circuit breakers, retries, rate limiters, and more into one cohesive library. Python has been missing this.

Existing Python libraries solve individual problems well:

- **tenacity** — retry only
- **pybreaker** — circuit breaker only
- **wrapt_timeout_decorator** — timeout only

But combining them means stacking decorators, managing separate configs, and losing visibility across patterns. **pyresilience** unifies everything.

## Feature Parity with Resilience4j

| Resilience4j Module | pyresilience Equivalent | Description |
|---------------------|------------------------|-------------|
| CircuitBreaker | `CircuitBreakerConfig` | Prevents calls to failing services |
| Retry | `RetryConfig` | Retries failed calls with backoff |
| Bulkhead | `BulkheadConfig` | Limits concurrent executions |
| TimeLimiter | `TimeoutConfig` | Enforces per-call time limits |
| RateLimiter | `RateLimiterConfig` | Limits call rate per time window |
| Cache | `CacheConfig` | Caches successful results |
| Registry | `ResilienceRegistry` | Manages named resilience instances |

## At a Glance

```python
from pyresilience import resilient, RetryConfig, TimeoutConfig, CircuitBreakerConfig

@resilient(
    retry=RetryConfig(max_attempts=3, delay=1.0),
    timeout=TimeoutConfig(seconds=10),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
)
def call_payment_api(amount: float) -> dict:
    return requests.post("/charge", json={"amount": amount}).json()
```

This single decorator:

1. **Retries** up to 3 times with exponential backoff
2. **Times out** each attempt after 10 seconds
3. **Opens the circuit** after 5 consecutive failures, blocking further calls until recovery

All patterns work together, with a unified event system for observability.

## Key Features

- **All 7 Resilience4j patterns** in one library
- **One decorator** — `@resilient()` combines everything
- **Zero dependencies** — pure Python stdlib
- **Full async support** — auto-detects sync vs async
- **Type-safe** — strict mypy compatible, `py.typed` marker
- **Opinionated presets** — `http_policy()`, `db_policy()`, `queue_policy()`
- **Structured observability** — JSON logging, metrics collection
- **Optional performance backends** — uvloop + orjson
- **Python 3.9+** — tested on 3.9 through 3.14

## Next Steps

- [Installation](getting-started/installation.md) — Get started in 30 seconds
- [Quick Start](getting-started/quickstart.md) — Your first resilient function
- [Core Modules](core/circuitbreaker.md) — Deep dive into each pattern
