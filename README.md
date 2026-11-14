# pyresilience

<p align="center">
  <a href="https://github.com/AhsanSheraz/pyresilience/actions/workflows/ci.yml"><img src="https://github.com/AhsanSheraz/pyresilience/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://codecov.io/gh/AhsanSheraz/pyresilience"><img src="https://codecov.io/gh/AhsanSheraz/pyresilience/graph/badge.svg?token=egEaq767Fi" alt="Coverage"></a>
  <a href="https://pypi.org/project/pyresilience/"><img src="https://img.shields.io/pypi/v/pyresilience.svg?t=20260612" alt="PyPI version"></a>
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

Also works with `uv`, `poetry`, and `pdm`. Python 3.9+; CI tests 3.10 through 3.15 on Linux, macOS and Windows.

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
- **Built for LLM and rate-limited APIs** — Requests-per-minute and tokens-per-minute limits together, token usage settled after the call, limits that follow `Retry-After` and `x-ratelimit-*` headers, and fallback to another provider with a cooldown for the one that is down.
- **Scales past one process** — Share one circuit breaker, rate limit and retry budget across workers and replicas through a pluggable backend (in-memory or your Redis client).
- **Sync and async** — Same API for both. Auto-detects your function type.
- **Production observability** — Built-in event listeners for logging, metrics, and alerting. OpenTelemetry and Prometheus listeners included. Know when circuits open, retries fire, or rate limits hit.
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
from pyresilience import http_policy, db_policy, queue_policy, strict_policy, llm_policy

@resilient(**http_policy())       # 10s timeout, 3 retries, circuit breaker
def call_api(): ...

@resilient(**db_policy())         # 30s timeout, 2 retries, 10 concurrent max
def query_db(): ...

@resilient(**queue_policy())      # 15s timeout, 5 retries, high failure threshold
async def publish_message(): ...

@resilient(**strict_policy())     # 5s timeout, 1 retry, fail fast
def latency_critical(): ...

@resilient(**llm_policy())        # 429-aware retry honoring Retry-After + client-side rate limit
def ask_model(): ...
```

### HTTP 429 / Retry-After out of the box

Calling OpenAI, Anthropic, Stripe, or GitHub APIs? pyresilience handles rate limits natively —
no hand-rolled wait strategies:

```python
from pyresilience import resilient, RetryConfig
from pyresilience.contrib.http import retry_on_status, retry_after_delay

@resilient(retry=RetryConfig(
    max_attempts=4,
    retry_on_result=retry_on_status(429, 503),    # retry these statuses (requests/httpx/aiohttp)
    delay_func=retry_after_delay(max_wait=60.0),  # wait exactly what Retry-After asks
    ignore_on=(PermissionError,),                 # terminal errors: never retried
))
def call_api():
    return requests.get("https://api.example.com/data")
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

### Request Correlation

```python
from pyresilience import resilience_context

# Set trace/request ID for the current context — propagates through all resilience events
resilience_context.set({"trace_id": "abc-123", "request_id": "req-456"})
```

### OpenTelemetry & Prometheus

```python
from pyresilience.contrib.otel import OpenTelemetryListener
from pyresilience.contrib.prometheus import PrometheusListener

@resilient(retry=RetryConfig(max_attempts=3), listeners=[OpenTelemetryListener()])
def call_api(): ...

@resilient(retry=RetryConfig(max_attempts=3), listeners=[PrometheusListener()])
def call_db(): ...
```

## Production Features

### Retry Budget

Prevent retry storms across your service with a shared token bucket:

```python
from pyresilience import resilient, RetryConfig, RetryBudgetConfig, RetryBudget

@resilient(
    retry=RetryConfig(max_attempts=3),
    retry_budget=RetryBudgetConfig(max_retries=100, refill_rate=10),
)
def call_api(): ...
```

### Timeouts That Compose

A limit per attempt, an overall deadline, or both. The call stops retrying as soon as the time left cannot cover the next wait:

```python
from pyresilience import resilient, RetryConfig, TimeoutConfig

@resilient(
    retry=RetryConfig(max_attempts=4),
    timeout=TimeoutConfig(seconds=10, total_seconds=30),   # 10s per attempt, 30s overall
)
def call_api(): ...

@resilient(timeout=TimeoutConfig(seconds=30, stream_idle_seconds=15))
async def stream_completion(prompt: str):
    return client.stream(prompt)   # raises if no chunk arrives for 15s
```

### LLM-Grade Rate Limiting

Several limits at once, weighted by what a call really costs, and corrected by what the server reports:

```python
from pyresilience import resilient, RateLimit, RateLimiterConfig
from pyresilience.contrib.http import rate_limit_feedback

@resilient(rate_limiter=RateLimiterConfig(
    max_calls=60, period=60.0,                       # requests per minute
    max_wait=10.0,
    limits=[RateLimit(
        max_units=90_000, period=60.0, name="tokens",  # tokens per minute
        cost=lambda prompt: len(prompt) // 4 + 256,     # estimate, reserved up front
        actual_cost=lambda r: r.usage.total_tokens,     # settled after the call
    )],
    feedback=rate_limit_feedback(),                   # follow Retry-After and x-ratelimit-* headers
))
def complete(prompt: str): ...
```

Or in one line: `@resilient(**llm_policy(tokens_per_minute=90_000, token_cost=..., adaptive_rate_limit=True))`.

### Fallback to Another Provider

Alternatives receive the original arguments. A target that keeps failing is skipped during its cooldown:

```python
from pyresilience import resilient, FallbackConfig

@resilient(fallback=FallbackConfig(
    alternatives=[ask_backup_model, ask_small_model],
    handler="No model available right now.",
    cooldown=30.0,              # skip a failing provider for 30s
    cooldown_threshold=3,       # after 3 failures in a row
))
def ask(prompt: str) -> str:
    return primary_client.complete(prompt)
```

### Shared State Across Processes

With five replicas, a limit of 100 calls per minute is really 500, and a breaker with `failure_threshold=5` absorbs 25 failures. Share the state instead:

```python
import redis
from pyresilience import resilient, CircuitBreakerConfig, RateLimiterConfig, SharedStateConfig
from pyresilience.contrib.redis import RedisBackend

@resilient(
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
    rate_limiter=RateLimiterConfig(max_calls=100, period=60.0),
    shared_state=SharedStateConfig(backend=RedisBackend(redis.Redis()), key="payment-api"),
)
def charge(amount: float) -> dict: ...
```

Rate limits hold across processes, because every call is counted in the backend; circuit breaker and retry budget are synchronised in the background, with no backend I/O on the call path. pyresilience still has no dependencies: you pass in the Redis client you already use.

### Health Check

Inspect circuit breaker states across your registry:

```python
from pyresilience import ResilienceRegistry, health_check

registry = ResilienceRegistry()
# ... register and use services ...

status = health_check(registry)
# {"payment-api": {"circuit_breaker": {"state": "closed", "failure_count": 0}}}
```

### Graceful Shutdown

Drain in-flight calls before stopping:

```python
from pyresilience import shutdown

shutdown(wait=True, timeout=30)  # Wait up to 30s for in-flight calls to complete
```

## Performance

Benchmarked against tenacity, backoff, stamina, and pybreaker on macOS (Apple Silicon). Full benchmark code in [`benchmarks/`](benchmarks/).

### Decorator Overhead (no-op function, 100k calls)

| Library | Mean | vs pyresilience |
|---------|-----:|-----:|
| bare (no decorator) | 0.07μs | — |
| **pyresilience** | **0.64μs** | **1.0x** |
| pybreaker | 0.64μs | 1.0x |
| backoff | 1.29μs | 2.0x slower |
| stamina | 5.33μs | 8.3x slower |
| tenacity | 6.64μs | 10.4x slower |

**pyresilience is 10.4x faster than tenacity on the happy path.**

### Individual Pattern Overhead (100k calls)

| Pattern | Mean Latency |
|---------|----------:|
| Retry (happy path) | 0.64μs |
| Circuit Breaker | 1.03μs |
| Fallback (triggered) | 0.69μs |
| Bulkhead | 0.74μs |
| Rate Limiter | 0.89μs |
| Cache (hit) | 0.68μs |
| **All 7 patterns (cache hit)** | **0.67μs** |

### Throughput (10k calls, 10 threads)

| Library | ops/sec |
|---------|--------:|
| **pyresilience** | **223,934** |
| tenacity | 58,109 |

**pyresilience achieves 3.9x higher throughput under concurrent load.**

### Async Overhead (50k calls)

| Library | Mean |
|---------|-----:|
| **pyresilience** | **0.82μs** |
| tenacity | 11.83μs |

**pyresilience is 14.4x faster than tenacity for async functions.**

### Memory (1,000 decorated functions)

| Library | Memory |
|---------|-------:|
| **pyresilience** | **1,224 KB** |
| tenacity | 2,150 KB |

**pyresilience uses 43% less memory.**

### New in 0.5.0: Feature Overhead

Cost of one successful decorated call with the 0.5.0 features, from [`benchmarks/bench_new_features.py`](benchmarks/bench_new_features.py). Measured on Windows 11 (x86-64), minimum of 7 runs; a different machine than the tables above, so compare within this table only.

| Configuration | Python 3.14 | Python 3.15 |
|---------------|------------:|------------:|
| bare function (baseline) | 0.03μs | 0.02μs |
| Rate limiter: plain (one token per call) | 1.57μs | 1.23μs |
| Rate limiter: weighted cost | 2.47μs | 1.86μs |
| Rate limiter: three limits at once | 2.68μs | 2.21μs |
| Rate limiter: token reconcile + server feedback | 4.73μs | 3.74μs |
| Rate limiter: shared through a backend (in-memory) | 3.96μs | 3.26μs |
| Fallback: plain handler | 1.19μs | 0.93μs |
| Fallback: alternatives + cooldown (primary healthy) | 1.66μs | 1.27μs |
| Fallback: primary cooling down, alternative used | 1.60μs | 1.24μs |
| Shared circuit breaker + retry budget | 1.88μs | 1.34μs |
| Registry: state shared by sync and async (sync call) | 2.27μs | 1.77μs |
| Registry: state shared by sync and async (async call) | 2.99μs | 2.36μs |
| Timeout: per attempt (sync, worker thread) | 21.11μs | 21.34μs |
| Timeout: per attempt + overall deadline (sync) | 22.39μs | 20.88μs |
| Stream idle timeout (async, per item) | 2.51μs | 1.96μs |

The existing hot paths are unchanged: `benchmarks/bench_compare.py` (working tree against 0.4.1, median of 25 alternating rounds) puts every `bench_overhead.py` configuration between -1.6% and +2.9% of 0.4.1, which is run-to-run noise.

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
| Retry Budget | Yes | - | - | - | - |
| 429 + Retry-After handling | Yes | - | - | - | - |
| Per-attempt timeout + overall deadline | Yes | - | - | - | - |
| Token-aware, multi-limit rate limiting | Yes | - | - | - | - |
| Fallback to alternatives with cooldown | Yes | - | - | - | - |
| Shared state across processes | Yes | - | Breaker only | - | - |
| Context Propagation | Yes | - | - | - | - |
| Health Check | Yes | - | - | - | - |
| Prometheus | Yes | - | - | - | - |
| OpenTelemetry | Yes | - | - | - | - |
| Unified API | Yes | - | - | - | - |
| Zero Dependencies | Yes | Yes | - | - | - |
| Async | Yes | Yes | - | Yes | Yes |

*Comparison reflects built-in capabilities and unified API model, not every possible custom composition.*

## Documentation

Full guides, API reference, and examples at **[pyresilience.readthedocs.io](https://pyresilience.readthedocs.io/)**.

## License

MIT
