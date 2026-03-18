# pyresilience

**Unified resilience patterns for Python** — retry, circuit breaker, timeout, fallback, and bulkhead in one decorator.

## Why pyresilience?

Python has great individual libraries for retry (tenacity), but no unified solution combining all resilience patterns. In Java, Resilience4j solves this beautifully. **pyresilience** brings that same power to Python.

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
- **Event System** for observability
- **Zero dependencies** — pure Python, stdlib only
- **Full type safety** — strict mypy compatible
- **Async-first** — works with both sync and async code
