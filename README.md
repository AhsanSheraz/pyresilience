# pyresilience

[![CI](https://github.com/AhsanSheraz/pyresilience/actions/workflows/ci.yml/badge.svg)](https://github.com/AhsanSheraz/pyresilience/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/AhsanSheraz/pyresilience/graph/badge.svg)](https://codecov.io/gh/AhsanSheraz/pyresilience)
[![PyPI](https://img.shields.io/pypi/v/pyresilience.svg)](https://pypi.org/project/pyresilience/)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/pyresilience.svg)](https://pypi.org/project/pyresilience/)
[![Python](https://img.shields.io/pypi/pyversions/pyresilience.svg)](https://pypi.org/project/pyresilience/)
[![Documentation](https://readthedocs.org/projects/pyresilience/badge/?version=latest)](https://pyresilience.readthedocs.io/en/latest/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**All resilience patterns. One decorator. Zero dependencies.**

Stop juggling `tenacity` for retries, `pybreaker` for circuit breakers, and custom code for everything else. pyresilience gives you retry, circuit breaker, timeout, fallback, bulkhead, rate limiter, and cache — all through a single `@resilient()` decorator that works with sync and async.

---

## Install

```bash
pip install pyresilience
```

Also works with `uv`, `poetry`, and `pdm`.

## Quick Start

```python
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
- **Zero dependencies** — Pure Python. Nothing to conflict with your stack.
- **Sync and async** — Same API for both. No separate libraries or different patterns to learn.
- **Production observability** — Built-in event listeners for logging, metrics, and alerting. Know when circuits open, retries fire, or rate limits hit.
- **Framework integrations** — Drop-in support for [FastAPI](https://pyresilience.readthedocs.io/en/latest/advanced/frameworks/), [Django](https://pyresilience.readthedocs.io/en/latest/advanced/frameworks/), and [Flask](https://pyresilience.readthedocs.io/en/latest/advanced/frameworks/).

## All Seven Patterns

| Pattern | Config | What it does |
|---------|--------|-------------|
| **Retry** | `RetryConfig` | Exponential backoff with jitter |
| **Timeout** | `TimeoutConfig` | Per-call time limits |
| **Circuit Breaker** | `CircuitBreakerConfig` | Stop calling failing services |
| **Fallback** | `FallbackConfig` | Graceful degradation |
| **Bulkhead** | `BulkheadConfig` | Concurrency limiting |
| **Rate Limiter** | `RateLimiterConfig` | Token bucket rate limiting |
| **Cache** | `CacheConfig` | LRU result caching with TTL |

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

## Documentation

Full guides, API reference, and examples at **[pyresilience.readthedocs.io](https://pyresilience.readthedocs.io/)**.

## License

MIT
