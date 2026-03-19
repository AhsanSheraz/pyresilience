# pyresilience

<p align="center">
  <a href="https://github.com/AhsanSheraz/pyresilience/actions/workflows/ci.yml"><img src="https://github.com/AhsanSheraz/pyresilience/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://codecov.io/gh/AhsanSheraz/pyresilience"><img src="https://codecov.io/gh/AhsanSheraz/pyresilience/graph/badge.svg?token=egEaq767Fi" alt="Coverage"></a>
  <a href="https://pypi.org/project/pyresilience/"><img src="https://img.shields.io/pypi/v/pyresilience.svg?cacheSeconds=0" alt="PyPI version"></a>
  <a href="https://pypi.org/project/pyresilience/"><img src="https://img.shields.io/pypi/pyversions/pyresilience.svg" alt="Python versions"></a>
  <a href="https://pypi.org/project/pyresilience/"><img src="https://img.shields.io/pypi/dm/pyresilience.svg" alt="Downloads"></a>
  <a href="https://github.com/AhsanSheraz/pyresilience/blob/main/LICENSE"><img src="https://img.shields.io/pypi/l/pyresilience.svg" alt="License"></a>
  <a href="https://pyresilience.readthedocs.io/en/latest/"><img src="https://readthedocs.org/projects/pyresilience/badge/?version=latest" alt="Documentation"></a>
</p>

**All resilience patterns. One decorator. Zero dependencies.**

Inspired by Java's [Resilience4j](https://resilience4j.readme.io/). Stop juggling `tenacity` for retries, `pybreaker` for circuit breakers, and custom code for everything else. pyresilience gives you retry, circuit breaker, timeout, fallback, bulkhead, rate limiter, and cache — all through a single `@resilient()` decorator that works with both sync and async functions.

---

## Install

```bash
pip install pyresilience
```

Also works with `uv`, `poetry`, and `pdm`.

## Quick Start

```python
import requests
from pyresilience import resilient, RetryConfig, TimeoutConfig, CircuitBreakerConfig

@resilient(
    retry=RetryConfig(max_attempts=3, delay=1.0),
    timeout=TimeoutConfig(seconds=10),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
)
def call_api(endpoint: str) -> dict:
    return requests.get(endpoint).json()
```

Retries with exponential backoff. Times out at 10s. Opens the circuit after 5 failures. That's it.

## Why pyresilience?

- **One library instead of many** — No need to wire together `tenacity` + `pybreaker` + custom timeout/fallback/rate limiting code. One config, one decorator.
- **Patterns that work together** — Circuit breaker state is shared across retries. Rate limiting respects bulkhead limits. Cache short-circuits the entire pipeline. Everything is coordinated.
- **Zero dependencies** — Pure Python stdlib. Nothing to conflict with your stack.
- **Sync and async** — Same API for both. Auto-detects your function type.
- **Production observability** — Built-in event listeners for logging, metrics, and alerting. Know when circuits open, retries fire, or rate limits hit.
- **Thread-safe and async-safe** — All stateful components use locks. Async-safe latency tracking via `contextvars`. Cache stampede prevention via per-key locking.
- **Framework integrations** — Drop-in support for [FastAPI](https://pyresilience.readthedocs.io/en/latest/advanced/frameworks/), [Django](https://pyresilience.readthedocs.io/en/latest/advanced/frameworks/), and [Flask](https://pyresilience.readthedocs.io/en/latest/advanced/frameworks/).

## All Seven Patterns

```python
from pyresilience import resilient, RetryConfig, TimeoutConfig, CircuitBreakerConfig
from pyresilience import FallbackConfig, BulkheadConfig, RateLimiterConfig, CacheConfig

@resilient(
    retry=RetryConfig(max_attempts=3, delay=1.0, backoff_factor=2.0),
    timeout=TimeoutConfig(seconds=10),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5, recovery_timeout=30),
    fallback=FallbackConfig(handler=lambda e: {"status": "degraded"}, fallback_on=[Exception]),
    bulkhead=BulkheadConfig(max_concurrent=10),
    rate_limiter=RateLimiterConfig(max_calls=100, period=60.0),
    cache=CacheConfig(ttl=300.0, max_size=1000),
)
def call_service(endpoint: str) -> dict:
    return requests.get(endpoint).json()
```

| Pattern | Config | What it does |
|---------|--------|-------------|
| **Retry** | `RetryConfig` | Exponential backoff with jitter |
| **Timeout** | `TimeoutConfig` | Per-call time limits |
| **Circuit Breaker** | `CircuitBreakerConfig` | Stop calling failing services |
| **Fallback** | `FallbackConfig` | Graceful degradation |
| **Bulkhead** | `BulkheadConfig` | Concurrency limiting |
| **Rate Limiter** | `RateLimiterConfig` | Token bucket rate limiting |
| **Cache** | `CacheConfig` | LRU result caching with TTL |

## Async Support

The same decorator works with async functions — no changes needed:

```python
import aiohttp
from pyresilience import resilient, RetryConfig, CircuitBreakerConfig

@resilient(
    retry=RetryConfig(max_attempts=3, delay=0.5),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
)
async def call_api(url: str) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.json()
```

## Built-in Presets

Skip the configuration for common use cases:

```python
from pyresilience import resilient
from pyresilience import http_policy, db_policy, queue_policy, strict_policy

@resilient(**http_policy())       # 10s timeout, 3 retries, circuit breaker
def call_api(): ...

@resilient(**db_policy())         # 30s timeout, 2 retries, 10 concurrent max
def query_db(): ...

@resilient(**queue_policy())      # 15s timeout, 5 retries, high failure threshold
async def publish_message(): ...

@resilient(**strict_policy())     # 5s timeout, 1 retry, fail fast
def latency_critical(): ...
```

## Observability

```python
from pyresilience import resilient, RetryConfig, JsonEventLogger, MetricsCollector

logger = JsonEventLogger()
metrics = MetricsCollector()

@resilient(retry=RetryConfig(max_attempts=3), listeners=[logger, metrics])
def my_func():
    ...

# After calls:
print(metrics.summary())
# {"my_func": {"events": {"retry": 2, "success": 1}, "success_rate": 1.0, "avg_latency_ms": 15.2}}
```

## Performance

Benchmarked against tenacity, backoff, stamina, and pybreaker on macOS (Apple Silicon). Full benchmark code in [`benchmarks/`](benchmarks/).

### Decorator Overhead (no-op function, 100k calls)

| Library | Mean | vs pyresilience |
|---------|-----:|-----:|
| bare (no decorator) | 0.05μs | — |
| **pyresilience** | **0.73μs** | **1.0x** |
| backoff | 1.34μs | 1.8x slower |
| pybreaker | 0.64μs | 0.9x |
| stamina | 6.15μs | 8.4x slower |
| tenacity | 7.89μs | 10.8x slower |

**pyresilience is 10.8x faster than tenacity on the happy path.**

### Individual Pattern Overhead (100k calls)

| Pattern | Mean Latency |
|---------|----------:|
| Retry (happy path) | 0.73μs |
| Circuit Breaker | 0.95μs |
| Fallback (triggered) | 0.68μs |
| Bulkhead | 0.66μs |
| Rate Limiter | 0.79μs |
| Cache (hit) | 0.58μs |
| **All 7 patterns (cache hit)** | **0.60μs** |

### Throughput (10k calls, 10 threads)

| Library | ops/sec |
|---------|--------:|
| **pyresilience** | **152,208** |
| tenacity | 66,916 |

**pyresilience achieves 2.3x higher throughput under concurrent load.**

### Async Overhead (50k calls)

| Library | Mean |
|---------|-----:|
| **pyresilience** | **0.69μs** |
| tenacity | 12.14μs |

**pyresilience is 17.6x faster than tenacity for async functions.**

### Memory (1,000 decorated functions)

| Library | Memory |
|---------|-------:|
| **pyresilience** | **1,208 KB** |
| tenacity | 2,181 KB |

**pyresilience uses 45% less memory.**

## Comparison

| | pyresilience | tenacity | pybreaker | backoff | stamina |
|---|:---:|:---:|:---:|:---:|:---:|
| Retry | Yes | Yes | - | Yes | Yes |
| Circuit Breaker | Yes | - | Yes | - | - |
| Timeout | Yes | - | - | - | - |
| Fallback | Yes | - | - | - | - |
| Bulkhead | Yes | - | - | - | - |
| Rate Limiter | Yes | - | - | - | - |
| Cache | Yes | - | - | - | - |
| Unified API | Yes | - | - | - | - |
| Zero Dependencies | Yes | Yes | - | - | - |
| Async | Yes | Yes | - | Yes | Yes |

*Comparison reflects built-in capabilities and unified API model, not every possible custom composition.*

## Documentation

Full guides, API reference, and examples at **[pyresilience.readthedocs.io](https://pyresilience.readthedocs.io/)**.

## License

MIT
