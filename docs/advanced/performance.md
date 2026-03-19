# Performance

pyresilience is designed to add minimal overhead to your function calls. Benchmarked on macOS (Apple Silicon) across Python 3.10 — 3.14.

## Overhead

Measured with 100k calls per benchmark. These are real numbers, not estimates.

| Pattern | Mean Latency (Python 3.14) |
|---------|----------:|
| No decorator (baseline) | 0.06us |
| Retry (happy path, no failures) | 0.53us |
| Circuit breaker (closed state) | 0.97us |
| Fallback (triggered) | 0.90us |
| Bulkhead (acquire/release) | 1.08us |
| Rate limiter (within limits) | 0.82us |
| Cache (hit) | 0.91us |
| **All 7 patterns combined (cache hit)** | **0.92us** |

For any real-world I/O operation (HTTP calls at ~50ms, DB queries at ~5ms), pyresilience's overhead is <0.02%.

## vs Competitors

### Happy Path (no failures, 100k calls)

| Library | Python 3.10 | Python 3.12 | Python 3.13 | Python 3.14 |
|---------|----------:|----------:|----------:|----------:|
| **pyresilience** | **0.67us** | **0.58us** | **0.55us** | **0.53us** |
| tenacity | 10.75us | 7.80us | 7.47us | 7.02us |
| backoff | 1.66us | 1.65us | 1.53us | 1.50us |
| stamina | 9.31us | 7.49us | 7.03us | 6.76us |
| pybreaker | 1.25us | 0.91us | 0.86us | 0.83us |

### Throughput (10k calls, 10 threads, ops/sec)

| Library | Python 3.10 | Python 3.12 | Python 3.13 | Python 3.14 |
|---------|----------:|----------:|----------:|----------:|
| **pyresilience** | **145,942** | **172,508** | **228,151** | **234,663** |
| tenacity | 44,980 | 73,735 | 80,909 | 82,010 |

### Async (50k calls)

| Library | Python 3.10 | Python 3.12 | Python 3.13 | Python 3.14 |
|---------|----------:|----------:|----------:|----------:|
| **pyresilience** | **0.79us** | **0.73us** | **0.66us** | **0.73us** |
| tenacity | 20.46us | 17.27us | 20.51us | 20.16us |

### Memory (1,000 decorated functions)

| Library | Python 3.10 | Python 3.12 | Python 3.13 | Python 3.14 |
|---------|----------:|----------:|----------:|----------:|
| **pyresilience** | **1,528 KB** | **1,290 KB** | **1,295 KB** | **1,052 KB** |
| tenacity | 2,416 KB | 2,192 KB | 2,336 KB | 2,254 KB |

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

## Thread Safety

All pyresilience components are thread-safe:

- **CircuitBreaker**: Uses `threading.Lock`
- **Bulkhead**: Uses `threading.Semaphore`
- **RateLimiter**: Uses `threading.Lock`
- **ResultCache**: Uses `threading.Lock`
- **Registry**: Uses `threading.Lock`
- **MetricsCollector**: Uses `threading.Lock`

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
