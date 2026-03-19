# Cache

The cache pattern stores successful function results and returns them on subsequent calls with the same arguments, avoiding redundant calls to slow backends.

## Concepts

The cache sits at the outermost layer of the execution pipeline. Before any other resilience pattern is applied, the cache is checked:

```
call(args) ──> Cache HIT? ──yes──> Return cached result
                   |
                   no
                   |
                   v
           Execute with all other patterns
                   |
                   v
           Store result in cache
```

The cache uses:

- **LRU eviction** — Least Recently Used entries are evicted when the cache reaches `max_size`
- **TTL expiration** — Entries expire after `ttl` seconds

## Configuration

```python
from pyresilience import CacheConfig

config = CacheConfig(
    max_size=256,   # Maximum number of cached entries
    ttl=300.0,      # Time-to-live: 5 minutes
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_size` | `int` | `256` | Maximum number of cached entries. Oldest entries are evicted (LRU). |
| `ttl` | `float` | `300.0` | Time-to-live in seconds. `0` means entries never expire. |

## Usage

### Basic Caching

```python
from pyresilience import resilient, CacheConfig

@resilient(cache=CacheConfig(max_size=100, ttl=60.0))
def get_user(user_id: int) -> dict:
    return requests.get(f"https://api.example.com/users/{user_id}").json()

get_user(42)  # Calls API
get_user(42)  # Returns cached result (API not called)
get_user(99)  # Different args, calls API
```

### Cache Key Generation

Cache keys are generated from function arguments automatically:

```python
@resilient(cache=CacheConfig())
def search(query: str, page: int = 1) -> list:
    return api.search(query, page)

search("python", page=1)  # Cached separately from:
search("python", page=2)  # Different key due to different args
```

### No Expiration

For data that rarely changes:

```python
@resilient(cache=CacheConfig(max_size=1000, ttl=0))
def get_config(key: str) -> str:
    return config_service.get(key)
```

With `ttl=0`, entries never expire (only evicted by LRU when `max_size` is reached).

### Short TTL for Real-Time Data

```python
@resilient(cache=CacheConfig(max_size=50, ttl=5.0))
def get_stock_price(symbol: str) -> float:
    return market_api.get_price(symbol)
```

### Cache + Retry + Circuit Breaker

Cache prevents redundant calls even when the service is healthy. If the cache misses, other patterns protect the call:

```python
@resilient(
    cache=CacheConfig(max_size=256, ttl=300.0),
    retry=RetryConfig(max_attempts=3),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
    timeout=TimeoutConfig(seconds=10),
)
def get_product(product_id: int) -> dict:
    return requests.get(f"https://api.example.com/products/{product_id}").json()
```

### Async Caching

```python
@resilient(cache=CacheConfig(max_size=100, ttl=60.0))
async def async_get_user(user_id: int) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.example.com/users/{user_id}") as resp:
            return await resp.json()
```

## Stampede Prevention

When a cache key expires under high concurrency, many threads or coroutines may simultaneously attempt to recompute the value (thundering herd). pyresilience prevents this with **per-key locking and a double-check pattern**: only one thread/coroutine computes per cache key while others wait for the result. This eliminates redundant work and protects downstream services from load spikes.

No configuration is needed — stampede prevention is always active.

## Events

| Event | When |
|-------|------|
| `EventType.CACHE_HIT` | A cached result was returned |
| `EventType.CACHE_MISS` | No cached result found, executing the function |

```python
def on_event(event):
    if event.event_type == EventType.CACHE_HIT:
        print(f"Cache hit for {event.function_name}")
    elif event.event_type == EventType.CACHE_MISS:
        print(f"Cache miss for {event.function_name}")
```

## Direct Usage

Use the cache directly without the decorator:

```python
from pyresilience import ResultCache, CacheConfig

cache = ResultCache(CacheConfig(max_size=100, ttl=60.0))

# Store and retrieve
key = ResultCache.make_key("user", 42)
cache.put(key, {"name": "Alice"})
result = cache.get(key)  # {"name": "Alice"}

# Invalidate
cache.invalidate(key)

# Statistics
print(cache.stats)
# {'hits': 1, 'misses': 0, 'hit_rate': 1.0, 'size': 0, 'max_size': 100}

# Clear all
cache.clear()
```

## Cache Statistics

Monitor cache effectiveness:

```python
cache = ResultCache(CacheConfig(max_size=100, ttl=60.0))

# After some usage:
stats = cache.stats
print(f"Hit rate: {stats['hit_rate']:.1%}")  # "Hit rate: 85.0%"
print(f"Size: {stats['size']}/{stats['max_size']}")  # "Size: 42/100"
```
