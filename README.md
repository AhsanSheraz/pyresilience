# pyresilience

[![CI](https://github.com/AhsanSheraz/pyresilience/actions/workflows/ci.yml/badge.svg)](https://github.com/AhsanSheraz/pyresilience/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/AhsanSheraz/pyresilience/graph/badge.svg)](https://codecov.io/gh/AhsanSheraz/pyresilience)
[![PyPI](https://img.shields.io/pypi/v/pyresilience)](https://pypi.org/project/pyresilience/)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/pyresilience)](https://pypi.org/project/pyresilience/)
[![Python](https://img.shields.io/pypi/pyversions/pyresilience)](https://pypi.org/project/pyresilience/)
[![Documentation](https://readthedocs.org/projects/pyresilience/badge/?version=latest)](https://pyresilience.readthedocs.io/en/latest/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Unified resilience patterns for Python** — retry, circuit breaker, timeout, fallback, bulkhead, rate limiter, and cache in one decorator. Python's [Resilience4j](https://resilience4j.readme.io/).

> **157 tests** | **98% coverage** | **0 dependencies** | **<5 microsecond overhead** | **Python 3.9 — 3.14**

---

## Try It in 5 Seconds

```bash
pip install pyresilience
```

```python
from pyresilience import resilient

@resilient
def call_api():
    return requests.get("https://api.example.com/data").json()
# That's it. 3 retries with exponential backoff, out of the box.
```

---

## The Problem: Decorator Soup

Every Python service calling external APIs ends up like this:

```python
# Before: stacking 3 libraries with 3 configs and no shared state
from tenacity import retry, stop_after_attempt, wait_exponential
from pybreaker import CircuitBreaker
from wrapt_timeout_decorator import timeout

breaker = CircuitBreaker(fail_max=5, reset_timeout=30)

@timeout(10)
@breaker
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1))
def call_api(endpoint: str) -> dict:
    return requests.get(endpoint).json()

# No fallbacks. No rate limiting. No caching. No shared metrics.
# Each decorator is its own island.
```

```python
# After: one decorator, one config, full visibility
from pyresilience import resilient, RetryConfig, TimeoutConfig, CircuitBreakerConfig, FallbackConfig

@resilient(
    retry=RetryConfig(max_attempts=3, delay=1.0, backoff_factor=2.0),
    timeout=TimeoutConfig(seconds=10),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5, recovery_timeout=30),
    fallback=FallbackConfig(handler=lambda e: {"error": str(e), "cached": True}),
)
def call_api(endpoint: str) -> dict:
    return requests.get(endpoint).json()
```

---

## Who Is This For?

- **Microservice developers** calling external APIs, databases, or message queues
- **API integrators** dealing with rate limits, flaky services, and timeouts
- **Platform teams** wanting consistent resilience across all services
- **Anyone using `tenacity` + `pybreaker`** who wants one unified library instead

Works with **FastAPI**, **Django**, **Flask**, or any Python code (sync and async).

---

## How It Works

All patterns execute in a well-defined order:

```
Request
  |
  v
[Cache] -----> hit? --> return cached result
  |
  miss
  |
  v
[Circuit Breaker] --> open? --> reject / fallback
  |
  v
[Rate Limiter] -----> exceeded? --> reject / fallback
  |
  v
[Bulkhead] ---------> full? --> reject / fallback
  |
  v
[Retry Loop]
  |
  v
[Timeout] ----------> exceeded? --> TimeoutError (may retry)
  |
  v
[Your Function]
  |
  v
Store in cache --> Return result
```

---

## Install

```bash
pip install pyresilience        # pip
uv pip install pyresilience     # uv
poetry add pyresilience         # poetry

# Optional: faster event loop + JSON serialization
pip install pyresilience[fast]
```

## Quick Start

```python
from pyresilience import resilient, RetryConfig, TimeoutConfig, CircuitBreakerConfig, FallbackConfig

@resilient(
    retry=RetryConfig(max_attempts=3, delay=1.0, backoff_factor=2.0),
    timeout=TimeoutConfig(seconds=10),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5, recovery_timeout=30),
    fallback=FallbackConfig(handler=lambda e: {"error": str(e), "cached": True}),
)
def call_api(endpoint: str) -> dict:
    return requests.get(endpoint).json()

# Works with async too — auto-detected
@resilient(
    retry=RetryConfig(max_attempts=3),
    timeout=TimeoutConfig(seconds=5),
)
async def async_call(url: str) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.json()
```

## All 7 Patterns

| Pattern | What it does | Example |
|---------|-------------|---------|
| **Retry** | Exponential backoff with jitter | `RetryConfig(max_attempts=3)` |
| **Timeout** | Per-call time limits | `TimeoutConfig(seconds=10)` |
| **Circuit Breaker** | Stop calling failing services | `CircuitBreakerConfig(failure_threshold=5)` |
| **Fallback** | Graceful degradation | `FallbackConfig(handler=lambda e: None)` |
| **Bulkhead** | Concurrency limiting | `BulkheadConfig(max_concurrent=10)` |
| **Rate Limiter** | Calls per time window | `RateLimiterConfig(max_calls=100, period=60)` |
| **Cache** | LRU result caching with TTL | `CacheConfig(max_size=256, ttl=300)` |

Plus: **Registry**, **Presets**, **Event System**, **JSON Logging**, **Metrics Collection**

## Presets: Zero-Config for Common Patterns

Don't want to tune parameters? Use opinionated presets:

```python
from pyresilience import resilient
from pyresilience.presets import http_policy, db_policy, queue_policy

@resilient(**http_policy())     # 10s timeout, 3 retries, circuit breaker
def call_api(url: str) -> dict:
    return requests.get(url).json()

@resilient(**db_policy())       # 30s timeout, 2 retries, bulkhead of 10
def query_db(sql: str) -> list:
    return cursor.execute(sql).fetchall()

@resilient(**queue_policy())    # 15s timeout, 5 retries, high failure tolerance
async def publish(msg: dict) -> None:
    await producer.send(msg)
```

## Framework Integrations

### FastAPI

```python
from fastapi import Depends, FastAPI
from pyresilience import ResilienceConfig, RetryConfig, CircuitBreakerConfig
from pyresilience.contrib.fastapi import ResilientDependency

app = FastAPI()
payment = ResilientDependency(ResilienceConfig(
    retry=RetryConfig(max_attempts=3),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
))

@app.post("/charge")
async def charge(amount: float, r=Depends(payment)):
    return await r.call(payment_service.charge, amount)
```

### Django

```python
# settings.py
MIDDLEWARE = ['pyresilience.contrib.django.ResilientMiddleware']
PYRESILIENCE_CONFIG = {'timeout_seconds': 30, 'circuit_failure_threshold': 10}
```

### Flask

```python
from pyresilience.contrib.flask import resilient_route

@app.route("/data")
@resilient_route(retry=RetryConfig(max_attempts=3), timeout=TimeoutConfig(seconds=10))
def get_data():
    return external_api.get_data()
```

## Registry: Shared State Across Functions

```python
from pyresilience import ResilienceRegistry, ResilienceConfig, RetryConfig, CircuitBreakerConfig

registry = ResilienceRegistry()
registry.register("payment-api", ResilienceConfig(
    retry=RetryConfig(max_attempts=3),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
))

@registry.decorator("payment-api")
async def charge_card(amount: float) -> dict: ...

@registry.decorator("payment-api")
async def refund_card(amount: float) -> dict: ...

# Both share the same circuit breaker —
# if charge_card trips it, refund_card is also blocked
```

## Observability

```python
from pyresilience import resilient, RetryConfig, JsonEventLogger, MetricsCollector

logger = JsonEventLogger()
metrics = MetricsCollector()

@resilient(retry=RetryConfig(max_attempts=3), listeners=[logger, metrics])
def monitored_call():
    return do_work()

print(metrics.summary())
# {'total_events': 5, 'success_rate': 0.8, 'p99_latency': 1.23, ...}
```

---

## Resilience4j Feature Parity

| Resilience4j Module | pyresilience | Status |
|---------------------|-------------|--------|
| CircuitBreaker | `CircuitBreakerConfig` | Complete |
| Retry | `RetryConfig` | Complete |
| Bulkhead | `BulkheadConfig` | Complete |
| TimeLimiter | `TimeoutConfig` | Complete |
| RateLimiter | `RateLimiterConfig` | Complete |
| Cache | `CacheConfig` | Complete |
| Registry | `ResilienceRegistry` | Complete |

## Python Ecosystem Comparison

| Feature | pyresilience | tenacity | backoff | pybreaker | stamina | aiobreaker |
|---------|:----------:|:--------:|:-------:|:---------:|:-------:|:----------:|
| Retry | Yes | Yes | Yes | - | Yes | - |
| Circuit Breaker | Yes | - | - | Yes | - | Yes |
| Timeout | Yes | - | - | - | - | - |
| Fallback | Yes | - | - | - | - | - |
| Bulkhead | Yes | - | - | - | - | - |
| Rate Limiter | Yes | - | - | - | - | - |
| Cache | Yes | - | - | - | - | - |
| Registry | Yes | - | - | - | - | - |
| Unified API | Yes | - | - | - | - | - |
| Async | Yes | Yes | Yes | - | Yes | Yes |
| Zero Deps | Yes | Yes | - | - | - | - |
| Type-Safe | Yes | Partial | Partial | - | Yes | - |
| Presets | Yes | - | - | - | - | - |
| Observability | Yes | - | - | - | - | - |
| Framework Integrations | Yes | - | - | - | - | - |

---

## Production Ready

| | |
|---|---|
| **Tests** | 157 tests, 98% code coverage |
| **CI** | Linux, macOS, Windows x Python 3.9 — 3.14 (18 matrix jobs) |
| **Type Safety** | Strict mypy, `py.typed` (PEP 561) |
| **Dependencies** | Zero — pure Python stdlib |
| **Performance** | <5 microsecond overhead per call |
| **Backends** | Optional uvloop (C) + orjson (Rust) via `[fast]` |
| **Linting** | ruff (lint + format) |

---

## Documentation

For comprehensive guides, API reference, and advanced usage:

**[Read the full documentation at pyresilience.readthedocs.io](https://pyresilience.readthedocs.io/)**

- [Getting Started](https://pyresilience.readthedocs.io/en/latest/getting-started/quickstart/) — Installation, quick start, comparison with other libraries
- [Core Modules](https://pyresilience.readthedocs.io/en/latest/core/circuitbreaker/) — Deep dive into each resilience pattern
- [Advanced](https://pyresilience.readthedocs.io/en/latest/advanced/registry/) — Registry, presets, observability, combining patterns, framework integrations, performance
- [API Reference](https://pyresilience.readthedocs.io/en/latest/api/) — Complete configuration reference
- [Examples](https://github.com/AhsanSheraz/pyresilience/tree/main/examples) — Real-world usage examples

## License

MIT
