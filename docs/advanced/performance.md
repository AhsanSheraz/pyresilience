# Performance

pyresilience is designed to add minimal overhead to your function calls. For production workloads, optional backends can further improve performance.

## Overhead

pyresilience adds negligible overhead for the patterns themselves:

- **No patterns enabled**: ~1-2 microseconds (function wrapper only)
- **Retry (no actual retry)**: ~3-5 microseconds
- **Circuit breaker check**: ~2-3 microseconds (thread-safe lock acquisition)
- **Rate limiter check**: ~2-3 microseconds
- **Cache lookup**: ~3-5 microseconds (dict lookup + LRU update)

The actual latency of your function call will always dominate.

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
