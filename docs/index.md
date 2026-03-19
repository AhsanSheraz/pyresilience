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
import requests
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

## Why Not Just Tenacity + PyBreaker?

With separate libraries, you end up stacking decorators that don't share state:

```python
# Three libraries, three configs, no coordination
from tenacity import retry, stop_after_attempt, wait_exponential
from pybreaker import CircuitBreaker
from wrapt_timeout_decorator import timeout

breaker = CircuitBreaker(fail_max=5)

@timeout(10)
@breaker
@retry(stop=stop_after_attempt(3), wait=wait_exponential())
def call_api():
    return requests.get("https://api.example.com/data").json()
# No fallback. No rate limiting. No caching. No shared metrics.
# The circuit breaker doesn't know about retries. Timeouts don't coordinate with backoff.
```

With pyresilience, everything is coordinated through one decorator:

```python
import requests
from pyresilience import resilient, RetryConfig, TimeoutConfig, CircuitBreakerConfig
from pyresilience import FallbackConfig, RateLimiterConfig, CacheConfig

@resilient(
    retry=RetryConfig(max_attempts=3, delay=1.0),
    timeout=TimeoutConfig(seconds=10),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
    fallback=FallbackConfig(handler=lambda e: {"error": "service unavailable"}),
    rate_limiter=RateLimiterConfig(max_calls=100, period=60.0),
    cache=CacheConfig(max_size=256, ttl=300.0),
)
def call_api():
    return requests.get("https://api.example.com/data").json()
# One decorator. All patterns. Shared state. Unified metrics.
```

The circuit breaker counts retried failures correctly. Rate limiting respects bulkhead limits. Cache short-circuits the entire pipeline. One event system observes everything.

## Observability at a Glance

Every resilience event — retries, circuit state changes, rate limit hits — can be observed with listeners:

```python
from pyresilience import resilient, RetryConfig, CircuitBreakerConfig
from pyresilience import JsonEventLogger, MetricsCollector, EventType

logger = JsonEventLogger()
metrics = MetricsCollector()

def alert_on_circuit_open(event):
    if event.event_type == EventType.CIRCUIT_OPEN:
        print(f"ALERT: Circuit opened for {event.function_name}")

@resilient(
    retry=RetryConfig(max_attempts=3),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
    listeners=[logger, metrics, alert_on_circuit_open],
)
def payment_service(amount: float):
    return process_payment(amount)

# After some calls, check metrics:
# metrics.summary() -> {"total_events": 150, "success_rate": 0.95, ...}
```

See [Observability](advanced/observability.md) for the full event system, JSON logging, and metrics collection.

## FastAPI Integration

Use pyresilience with FastAPI's dependency injection for per-route resilience:

```python
from fastapi import Depends, FastAPI
from pyresilience import ResilienceConfig, RetryConfig, CircuitBreakerConfig
from pyresilience.contrib.fastapi import ResilientDependency

app = FastAPI()

payment_resilience = ResilientDependency(ResilienceConfig(
    retry=RetryConfig(max_attempts=3),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
))

@app.post("/charge")
async def charge(
    amount: float,
    resilience: ResilientDependency = Depends(payment_resilience),
):
    return await resilience.call(payment_service.charge, amount)
```

Also supports [Django and Flask](advanced/frameworks.md).

## Next Steps

- [Installation](getting-started/installation.md) — Get started in 30 seconds
- [Quick Start](getting-started/quickstart.md) — Your first resilient function
- [Core Modules](core/circuitbreaker.md) — Deep dive into each pattern
- [Observability](advanced/observability.md) — Logging, metrics, and alerting
- [Framework Integrations](advanced/frameworks.md) — FastAPI, Django, Flask
