# pyresilience

**Unified resilience patterns for Python** — retry, circuit breaker, timeout, fallback, bulkhead, rate limiter, and cache in one decorator. Python's [Resilience4j](https://resilience4j.readme.io/).

## Why pyresilience?

Python has great individual libraries for retry (tenacity), circuit breaking (pybreaker), and timeouts. But combining them means stacking decorators, managing separate configs, and losing visibility across patterns. **pyresilience** unifies everything into a single `@resilient()` decorator with zero dependencies.

## Resilience4j Feature Parity

| Resilience4j Module | pyresilience | Description |
|---------------------|-------------|-------------|
| CircuitBreaker | `CircuitBreakerConfig` | Stop calling failing services, auto-recover |
| Retry | `RetryConfig` | Exponential backoff with jitter |
| Bulkhead | `BulkheadConfig` | Concurrency limiting |
| TimeLimiter | `TimeoutConfig` | Per-call time limits |
| RateLimiter | `RateLimiterConfig` | Token bucket rate limiting |
| Cache | `CacheConfig` | LRU result caching with TTL |
| Registry | `ResilienceRegistry` | Centralized named instances |

## Quick Start

```python
from pyresilience import resilient, RetryConfig, TimeoutConfig, CircuitBreakerConfig

@resilient(
    retry=RetryConfig(max_attempts=3, delay=1.0),
    timeout=TimeoutConfig(seconds=10),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
)
def call_api(url: str) -> dict:
    return requests.get(url).json()
```

## Features

- **Retry** with exponential backoff and jitter
- **Timeout** for sync and async functions
- **Circuit Breaker** with half-open recovery
- **Fallback** with static values or callable handlers
- **Bulkhead** for concurrency limiting
- **Rate Limiter** with token bucket algorithm
- **Cache** with LRU eviction and TTL
- **Registry** for shared resilience state across functions
- **Presets** — `http_policy()`, `db_policy()`, `queue_policy()`, `strict_policy()`
- **Observability** — `JsonEventLogger`, `MetricsCollector`, event listeners
- **Zero dependencies** — pure Python, stdlib only
- **Optional performance backends** — `uvloop` + `orjson` via `pip install pyresilience[fast]`
- **Full type safety** — strict mypy compatible
- **Async-first** — works with both sync and async code
- **Python 3.9+**
