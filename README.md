# pyresilience

[![CI](https://github.com/AhsanSheraz/pyresilience/actions/workflows/ci.yml/badge.svg)](https://github.com/AhsanSheraz/pyresilience/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pyresilience)](https://pypi.org/project/pyresilience/)
[![Python](https://img.shields.io/pypi/pyversions/pyresilience)](https://pypi.org/project/pyresilience/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Unified resilience patterns for Python** — retry, circuit breaker, timeout, fallback, and bulkhead in one decorator. Python's missing [Resilience4j](https://resilience4j.readme.io/).

## Why?

Python has `tenacity` for retry, `pybreaker` for circuit breaking, and `wrapt_timeout_decorator` for timeouts. But combining them means stacking decorators, managing separate configs, and losing visibility across patterns. **pyresilience** unifies everything into a single `@resilient()` decorator with zero dependencies.

## Install

```bash
pip install pyresilience
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

Plus:
- **Event system** for observability (`ResilienceListener`)
- **Zero dependencies** — pure Python stdlib
- **Full async support** — auto-detects sync vs async
- **Type-safe** — strict mypy compatible, `py.typed` marker
- **Python 3.9+**

## Observability

```python
from pyresilience import resilient, RetryConfig, ResilienceEvent

def on_event(event: ResilienceEvent):
    print(f"[{event.event_type.value}] {event.function_name} attempt={event.attempt}")

@resilient(retry=RetryConfig(max_attempts=3), listeners=[on_event])
def monitored_call():
    return do_work()
```

## Documentation

Full docs at [pyresilience.readthedocs.io](https://pyresilience.readthedocs.io/)

## License

MIT
