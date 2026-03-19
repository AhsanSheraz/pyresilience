# Combining Patterns

One of pyresilience's key advantages is combining multiple resilience patterns in a single decorator with a well-defined execution order.

## Execution Order

When multiple patterns are configured, they execute in this order:

```
Incoming call
     |
     v
 [1. Cache] ──── hit? ──> return cached result
     |
     miss
     |
     v
 [2. Circuit Breaker] ──── open? ──> reject / fallback
     |
     closed/half-open
     |
     v
 [3. Rate Limiter] ──── exceeded? ──> reject / fallback
     |
     allowed
     |
     v
 [4. Bulkhead] ──── full? ──> reject / fallback
     |
     slot acquired
     |
     v
 [5. Retry Loop]
     |
     v
 [6. Timeout] ──── exceeded? ──> TimeoutError (may retry)
     |
     v
 [7. Function Call]
     |
     v
 Store in cache (if configured)
     |
     v
 Return result
```

### Why This Order?

1. **Cache first** — avoid unnecessary work entirely
2. **Circuit breaker** — fail fast if the dependency is known to be down
3. **Rate limiter** — respect upstream rate limits before consuming resources
4. **Bulkhead** — protect local resources (connections, threads)
5. **Retry** — handle transient failures within the protected scope
6. **Timeout** — each retry attempt gets its own timeout

## Common Combinations

### HTTP API Client

```python
@resilient(
    retry=RetryConfig(max_attempts=3, delay=0.5, backoff_factor=2.0),
    timeout=TimeoutConfig(seconds=10),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5, recovery_timeout=30),
    fallback=FallbackConfig(handler=lambda e: {"error": str(e)}),
)
def call_api(endpoint: str) -> dict:
    return requests.get(endpoint).json()
```

### Database with Connection Protection

```python
@resilient(
    retry=RetryConfig(max_attempts=2, delay=1.0),
    timeout=TimeoutConfig(seconds=30),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=3),
    bulkhead=BulkheadConfig(max_concurrent=10, max_wait=5.0),
)
def query_db(sql: str) -> list:
    return connection.execute(sql).fetchall()
```

### Rate-Limited External API

```python
@resilient(
    retry=RetryConfig(max_attempts=3),
    timeout=TimeoutConfig(seconds=15),
    rate_limiter=RateLimiterConfig(max_calls=100, period=60.0, max_wait=5.0),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=10),
)
async def call_third_party_api(query: str) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.example.com/search?q={query}") as resp:
            return await resp.json()
```

### Cached + Protected Reads

```python
@resilient(
    cache=CacheConfig(max_size=1000, ttl=300.0),
    retry=RetryConfig(max_attempts=2),
    timeout=TimeoutConfig(seconds=5),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
)
def get_product(product_id: int) -> dict:
    return requests.get(f"https://api.example.com/products/{product_id}").json()
```

### Maximum Resilience

All patterns enabled:

```python
@resilient(
    cache=CacheConfig(max_size=256, ttl=300.0),
    retry=RetryConfig(max_attempts=3, delay=0.5, backoff_factor=2.0, jitter=True),
    timeout=TimeoutConfig(seconds=10),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5, recovery_timeout=30),
    rate_limiter=RateLimiterConfig(max_calls=100, period=60.0),
    bulkhead=BulkheadConfig(max_concurrent=20),
    fallback=FallbackConfig(handler=lambda e: None),
    listeners=[JsonEventLogger(), MetricsCollector()],
)
def mission_critical_call(request_id: str) -> dict:
    return requests.post("https://api.example.com/process", json={"id": request_id}).json()
```

## Fallback Behavior

The fallback is checked when:

- The **circuit breaker** is open
- The **rate limiter** rejects a call
- The **bulkhead** is full
- All **retries** are exhausted
- A non-retryable exception occurs

```python
from pyresilience import (
    FallbackConfig,
    BulkheadFullError,
    RateLimitExceededError,
)

@resilient(
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
    rate_limiter=RateLimiterConfig(max_calls=10, period=1.0),
    bulkhead=BulkheadConfig(max_concurrent=5),
    fallback=FallbackConfig(
        handler=lambda e: {"status": "degraded", "reason": type(e).__name__},
        fallback_on=(Exception, BulkheadFullError, RateLimitExceededError),
    ),
)
def resilient_call() -> dict:
    return requests.get("https://api.example.com").json()
```

## Pattern Interactions

### Retry + Circuit Breaker

Each failed attempt counts toward the circuit breaker's failure threshold:

```
Attempt 1: ConnectionError → circuit records failure (1/5)
Attempt 2: ConnectionError → circuit records failure (2/5)
Attempt 3: ConnectionError → circuit records failure (3/5)
(retries exhausted)

Next call:
Attempt 1: ConnectionError → circuit records failure (4/5)
...
```

### Cache + Retry

Cache hits bypass the entire retry/timeout/circuit breaker pipeline:

```
Call 1: CACHE_MISS → execute (with retries) → SUCCESS → store in cache
Call 2: CACHE_HIT → return immediately (no retries needed)
```

### Timeout + Retry

Each retry attempt gets its own timeout:

```
Attempt 1: [──── 10s timeout ────] TIMEOUT
Attempt 2: [──── 10s timeout ────] TIMEOUT
Attempt 3: [── 3s ──] SUCCESS
```

Total worst case: `max_attempts * timeout + (max_attempts - 1) * max_delay`
