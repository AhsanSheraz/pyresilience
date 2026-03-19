# pyresilience

[![CI](https://github.com/AhsanSheraz/pyresilience/actions/workflows/ci.yml/badge.svg)](https://github.com/AhsanSheraz/pyresilience/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/AhsanSheraz/pyresilience/graph/badge.svg)](https://codecov.io/gh/AhsanSheraz/pyresilience)
[![PyPI](https://img.shields.io/pypi/v/pyresilience)](https://pypi.org/project/pyresilience/)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/pyresilience)](https://pypi.org/project/pyresilience/)
[![Python](https://img.shields.io/pypi/pyversions/pyresilience)](https://pypi.org/project/pyresilience/)
[![Documentation](https://readthedocs.org/projects/pyresilience/badge/?version=latest)](https://pyresilience.readthedocs.io/en/latest/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Unified resilience patterns for Python.** One decorator for retry, circuit breaker, timeout, fallback, bulkhead, rate limiter, and cache. Python's [Resilience4j](https://resilience4j.readme.io/).

---

## Install

```bash
pip install pyresilience
```

Also works with `uv`, `poetry`, and `pdm`. Optional performance backends: `pip install pyresilience[fast]`

## Quick Example

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

One decorator. Retries with backoff. Times out at 10s. Opens the circuit after 5 failures. Works with async too.

## Why Not Just `tenacity` + `pybreaker`?

```python
# Before: 3 libraries, 3 configs, no shared state
@timeout(10)
@breaker
@retry(stop=stop_after_attempt(3), wait=wait_exponential())
def call_api(): ...
# No fallback. No rate limiting. No caching. No metrics.

# After: one decorator, full resilience
@resilient(retry=..., timeout=..., circuit_breaker=..., fallback=..., rate_limiter=..., cache=...)
def call_api(): ...
```

## Features

| Pattern | Config | What it does |
|---------|--------|-------------|
| **Retry** | `RetryConfig` | Exponential backoff with jitter |
| **Timeout** | `TimeoutConfig` | Per-call time limits |
| **Circuit Breaker** | `CircuitBreakerConfig` | Stop calling failing services |
| **Fallback** | `FallbackConfig` | Graceful degradation |
| **Bulkhead** | `BulkheadConfig` | Concurrency limiting |
| **Rate Limiter** | `RateLimiterConfig` | Token bucket rate limiting |
| **Cache** | `CacheConfig` | LRU result caching with TTL |

**Plus:** [Registry](https://pyresilience.readthedocs.io/en/latest/advanced/registry/) for shared state | [Presets](https://pyresilience.readthedocs.io/en/latest/advanced/presets/) (`http_policy`, `db_policy`, `queue_policy`) | [Observability](https://pyresilience.readthedocs.io/en/latest/advanced/observability/) (JSON logging, metrics) | [Framework integrations](https://pyresilience.readthedocs.io/en/latest/advanced/frameworks/) (FastAPI, Django, Flask)

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

## Production Ready

176 tests | 96% coverage | strict mypy | zero dependencies | <5us overhead | Python 3.9 — 3.14 | Linux, macOS, Windows

## Documentation

**[pyresilience.readthedocs.io](https://pyresilience.readthedocs.io/)** — Getting started, core module guides, API reference, framework integrations, examples, and more.

## License

MIT
