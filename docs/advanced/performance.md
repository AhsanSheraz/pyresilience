# Performance

pyresilience is designed to add minimal overhead to your function calls. Benchmarked on macOS (Apple Silicon) across Python 3.10 — 3.14.

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
- **RateLimiter**: Uses `threading.Lock`
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
