# Performance

pyresilience is designed to add minimal overhead to your function calls. Benchmarked on macOS (Apple Silicon) across Python 3.10 — 3.14; the 0.5.0 feature table below was measured on Windows with Python 3.14 and 3.15.

## Overhead

Measured with 100k calls per benchmark. These are real numbers, not estimates.

| Pattern | Mean Latency |
|---------|----------:|
| No decorator (baseline) | 0.07μs |
| Retry (happy path, no failures) | 0.64μs |
| Circuit breaker (closed state) | 1.03μs |
| Fallback (triggered) | 0.69μs |
| Bulkhead (acquire/release) | 0.74μs |
| Rate limiter (within limits) | 0.89μs |
| Cache (hit) | 0.68μs |
| **All 7 patterns combined (cache hit)** | **0.67μs** |

For any real-world I/O operation (HTTP calls at ~50ms, DB queries at ~5ms), pyresilience's overhead is <0.02%.

## vs Competitors

### Happy Path (no failures, 100k calls)

| Library | Mean | vs pyresilience |
|---------|-----:|-----:|
| **pyresilience** | **0.64μs** | **1.0x** |
| pybreaker | 0.64μs | 1.0x |
| backoff | 1.29μs | 2.0x slower |
| stamina | 5.33μs | 8.3x slower |
| tenacity | 6.64μs | 10.4x slower |

### Throughput (10k calls, 10 threads, ops/sec)

| Library | ops/sec | vs pyresilience |
|---------|--------:|-----:|
| **pyresilience** | **223,934** | **1.0x** |
| tenacity | 58,109 | 3.9x slower |

### Async (50k calls)

| Library | Mean | vs pyresilience |
|---------|-----:|-----:|
| **pyresilience** | **0.82μs** | **1.0x** |
| tenacity | 11.83μs | 14.4x slower |

### Memory (1,000 decorated functions)

| Library | Memory |
|---------|-------:|
| **pyresilience** | **1,224 KB** |
| tenacity | 2,150 KB |

## 0.5.0 Feature Overhead

Cost of one successful decorated call with the features added in 0.5.0, from
`benchmarks/bench_new_features.py`. Measured on Windows 11 (x86-64) with Python 3.14.4 and
3.15.1, minimum of 7 alternating runs. This is a different machine than the tables above, so
compare within this table only.

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

What the numbers say:

- **Weighted and multi-limit rate limiting** costs about 0.6 to 1.1μs more than the plain limiter. The plain limiter is still used whenever the configuration needs nothing more.
- **Reconciliation and server feedback** wrap the call to observe its result, which adds about 2μs.
- **Shared rate limits** add one backend round trip per call. The figure above is for the in-memory backend; with Redis expect the network round trip (typically 0.2 to 1 ms).
- **Shared circuit breaker and retry budget** cost nothing on the call path beyond two counters; the exchange with the backend runs in a background thread.
- **The overall deadline** adds no measurable cost to a call with a timeout. Sync timeouts are dominated by the hop through a worker thread; async timeouts are not.
- **The stream idle timeout** costs about 2 to 2.5μs per item for async streams (`asyncio.wait_for` per item). A sync stream hands every item from its reader thread to the caller, which cost about 15μs per item on this machine.

### Hot Path Check Against 0.4.1

`benchmarks/bench_compare.py` times the `bench_overhead.py` configurations against two source
trees in short alternating rounds. Working tree against 0.4.1, Python 3.14, same machine,
median of 25 rounds for each side:

| Configuration | 0.4.1 | 0.5.0 | Change |
|---------------|------:|------:|-------:|
| `@resilient` (default retry) | 1.01μs | 1.00μs | -0.6% |
| Retry only | 1.26μs | 1.26μs | -0.4% |
| Retry + `ignore_on` | 1.26μs | 1.27μs | +0.8% |
| Retry + `delay_func` | 1.28μs | 1.26μs | -1.6% |
| Retry + timeout (sync) | 21.39μs | 22.01μs | +2.9% |
| Retry + circuit breaker | 1.81μs | 1.82μs | +0.1% |
| All patterns (no cache) | 23.74μs | 23.81μs | +0.3% |
| Cache (hit) | 2.37μs | 2.36μs | -0.1% |

Every configuration is within 3% of 0.4.1, which is run-to-run noise. The table shows medians
because the fastest round is not stable for the sync timeout rows, where every call hops
through a worker thread. Features that are not configured cost nothing measurable.

### Python 3.15

Python 3.15 is supported and tested in CI. On the same machine most benchmark
configurations ran 18 to 29% faster than on Python 3.14 (retry + circuit breaker: 1.31μs
against 1.72μs; weighted rate limiter: 1.86μs against 2.47μs). Sync timeouts do not improve:
they are bound by the hop through a worker thread.

## Optional Performance Backends

### uvloop

[uvloop](https://github.com/MagicStack/uvloop) is a C-based event loop that's 2-4x faster than the default `asyncio` loop.

```bash
pip install pyresilience[fast]
```

```python
from pyresilience import install_uvloop

install_uvloop()  # Sets uvloop as the default event loop policy
```

!!! note
    uvloop is only available on **Linux and macOS** (not Windows). pyresilience gracefully handles this — `install_uvloop()` returns `False` on unsupported platforms.

    Listener exceptions are logged as warnings (via `logging.warning()`) to prevent broken observability from being silently swallowed, while still protecting the application from listener failures.

### orjson

[orjson](https://github.com/ijl/orjson) is a Rust-based JSON library that's ~10x faster than stdlib `json`. It's automatically used by `JsonEventLogger` when available.

```bash
pip install pyresilience[fast]
```

No code changes needed — `JsonEventLogger` auto-detects orjson.

### Detection

Check what's available at runtime:

```python
from pyresilience import has_uvloop, has_orjson

print(f"uvloop: {has_uvloop()}")  # True/False
print(f"orjson: {has_orjson()}")  # True/False
```

## Cache Stampede Prevention

When a popular cache key expires, many threads/coroutines may simultaneously attempt to recompute the value (thundering herd). pyresilience uses **per-key locking with a double-check pattern**: only one thread/coroutine computes per cache key while others wait for the result. This eliminates redundant work and protects downstream services from load spikes.

## Sync Timeout Thread Cancellation

When a sync function exceeds its timeout, pyresilience uses `ctypes.pythonapi.PyThreadState_SetAsyncExc` for best-effort thread interruption on CPython. This raises an exception in the worker thread, allowing cleanup to occur. Note that blocking C extensions (e.g., `socket.recv()` without a timeout) cannot be interrupted by this mechanism. The original exception chain is preserved via `from exc`.

## Thread Safety

All pyresilience components are thread-safe:

- **CircuitBreaker**: Uses `threading.Lock` for all state transitions — safe for free-threaded Python 3.13+
- **Bulkhead**: Atomic counter with `threading.Lock` (non-waiting), `threading.Semaphore` (waiting)
- **RateLimiter**: Uses `threading.Lock` (also the weighted limiter, whose single lock is shared by sync and async callers)
- **Fallback cooldown**: Uses `threading.Lock`
- **Shared state**: `InMemoryBackend` uses `threading.Lock`; backend increments must be atomic
- **ResultCache**: Uses `threading.Lock`
- **Registry**: Uses `threading.Lock`
- **MetricsCollector**: Uses `threading.Lock` + `contextvars` for async-safe latency tracking. Latencies bounded to 10,000 entries.

You can safely share these across threads without external synchronization.

## Async Performance

For async code, pyresilience uses native asyncio primitives:

- **Timeout**: `asyncio.wait_for()` (no threads)
- **Bulkhead**: `asyncio.Semaphore`
- **Rate limiter**: `asyncio.sleep()` for waiting
- **Retry delay**: `asyncio.sleep()` (non-blocking)

## Best Practices

### 1. Use presets for common patterns

Presets are tuned for typical use cases and avoid over-configuration:

```python
@resilient(**http_policy())  # Tuned defaults
def call_api(): ...
```

### 2. Cache aggressively for read-heavy workloads

```python
@resilient(cache=CacheConfig(max_size=1000, ttl=60.0))
def get_config(key: str) -> str: ...
```

### 3. Use bulkheads to protect connection pools

```python
@resilient(bulkhead=BulkheadConfig(max_concurrent=pool_size))
def db_query(sql: str): ...
```

### 4. Keep listeners lightweight

Listeners run synchronously in the calling thread. Avoid heavy I/O in listeners:

```python
# Good: append to list, increment counter
def fast_listener(event):
    metrics.append(event)

# Bad: HTTP call in listener
def slow_listener(event):
    requests.post("https://monitoring.example.com", json=event)  # Don't do this
```
