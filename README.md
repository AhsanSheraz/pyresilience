# pyresilience

[![CI](https://github.com/AhsanSheraz/pyresilience/actions/workflows/ci.yml/badge.svg)](https://github.com/AhsanSheraz/pyresilience/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/AhsanSheraz/pyresilience/graph/badge.svg)](https://codecov.io/gh/AhsanSheraz/pyresilience)
[![PyPI](https://img.shields.io/pypi/v/pyresilience)](https://pypi.org/project/pyresilience/)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/pyresilience)](https://pypi.org/project/pyresilience/)
[![Python](https://img.shields.io/pypi/pyversions/pyresilience)](https://pypi.org/project/pyresilience/)
[![Documentation](https://readthedocs.org/projects/pyresilience/badge/?version=latest)](https://pyresilience.readthedocs.io/en/latest/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Unified resilience patterns for Python** — retry, circuit breaker, timeout, fallback, bulkhead, rate limiter, and cache in one decorator. Python's [Resilience4j](https://resilience4j.readme.io/).

## Why?

Python has `tenacity` for retry, `pybreaker` for circuit breaking, and `wrapt_timeout_decorator` for timeouts. But combining them means stacking decorators, managing separate configs, and losing visibility across patterns. **pyresilience** unifies everything into a single `@resilient()` decorator with zero dependencies.

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

# Works with async too
@resilient(
    retry=RetryConfig(max_attempts=3),
    timeout=TimeoutConfig(seconds=5),
)
async def async_call(url: str) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.json()
```

## Features

| Pattern | What it does |
|---------|-------------|
| **Retry** | Exponential backoff with jitter, configurable exceptions |
| **Timeout** | Per-call time limits (thread-based sync, native async) |
| **Circuit Breaker** | Stop calling failing services, auto-recover via half-open |
| **Fallback** | Graceful degradation with static values or callables |
| **Bulkhead** | Concurrency limiting to prevent resource exhaustion |
| **Rate Limiter** | Token bucket rate limiting (calls per time window) |
| **Cache** | LRU result caching with TTL to avoid redundant calls |

Plus:
- **Registry** for centralized management of named resilience instances
- **Event system** for observability (`ResilienceListener`)
- **Opinionated presets** — `http_policy()`, `db_policy()`, `queue_policy()`, `strict_policy()`
- **Structured logging** — `JsonEventLogger` and `MetricsCollector`
- **Zero dependencies** — pure Python stdlib
- **Optional performance backends** — `uvloop` + `orjson` via `pip install pyresilience[fast]`
- **Full async support** — auto-detects sync vs async
- **Type-safe** — strict mypy compatible, `py.typed` marker
- **Python 3.9+**

## Rate Limiter

Limit call rate using a token bucket algorithm:

```python
from pyresilience import resilient, RateLimiterConfig

@resilient(rate_limiter=RateLimiterConfig(max_calls=10, period=1.0))
def call_api(endpoint: str) -> dict:
    return requests.get(endpoint).json()

# With waiting instead of immediate rejection:
@resilient(rate_limiter=RateLimiterConfig(max_calls=10, period=1.0, max_wait=5.0))
async def rate_limited_call() -> dict:
    ...
```

## Cache

Cache function results with TTL and LRU eviction:

```python
from pyresilience import resilient, CacheConfig

@resilient(cache=CacheConfig(max_size=256, ttl=300.0))
def get_user(user_id: int) -> dict:
    return db.query(f"SELECT * FROM users WHERE id = {user_id}")

# Second call with same args returns cached result
get_user(42)  # hits DB
get_user(42)  # returns cached, DB not called
```

## Registry

Share resilience state (circuit breakers, rate limiters) across functions:

```python
from pyresilience import ResilienceRegistry, ResilienceConfig, RetryConfig, CircuitBreakerConfig

registry = ResilienceRegistry()
registry.register("payment-api", ResilienceConfig(
    retry=RetryConfig(max_attempts=3),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
))

@registry.decorator("payment-api")
async def charge_card(amount: float) -> dict:
    ...

@registry.decorator("payment-api")
async def refund_card(amount: float) -> dict:
    ...

# Both functions share the same circuit breaker —
# if charge_card trips the circuit, refund_card is also blocked
```

## Presets

Opinionated defaults for common integration patterns:

```python
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
```

## Observability

```python
from pyresilience import resilient, RetryConfig, JsonEventLogger, MetricsCollector

logger = JsonEventLogger()
metrics = MetricsCollector()

@resilient(retry=RetryConfig(max_attempts=3), listeners=[logger, metrics])
def monitored_call():
    return do_work()

# After calls:
print(metrics.summary())
# {'total_events': 5, 'success_rate': 0.8, 'p99_latency': 1.23, ...}
```

## Documentation

For comprehensive guides, API reference, and advanced usage:

**[Read the full documentation at pyresilience.readthedocs.io](https://pyresilience.readthedocs.io/)**

- [Getting Started](https://pyresilience.readthedocs.io/en/latest/getting-started/quickstart/) — Installation, quick start, comparison with other libraries
- [Core Modules](https://pyresilience.readthedocs.io/en/latest/core/circuitbreaker/) — Deep dive into each resilience pattern (CircuitBreaker, Retry, Bulkhead, TimeLimiter, RateLimiter, Cache)
- [Advanced](https://pyresilience.readthedocs.io/en/latest/advanced/registry/) — Registry, presets, observability, combining patterns, framework integrations (FastAPI, Django, Flask), performance tuning
- [API Reference](https://pyresilience.readthedocs.io/en/latest/api/) — Complete configuration reference for all patterns
- [Examples](https://github.com/AhsanSheraz/pyresilience/tree/main/examples) — Real-world usage examples

## License

MIT
