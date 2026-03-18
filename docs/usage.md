# Usage

## Basic Retry

```python
from pyresilience import resilient, RetryConfig

@resilient(retry=RetryConfig(max_attempts=3, delay=1.0))
def fetch_data():
    return requests.get("https://api.example.com/data").json()
```

## Timeout

```python
from pyresilience import resilient, TimeoutConfig

@resilient(timeout=TimeoutConfig(seconds=5.0))
def slow_operation():
    # Will raise TimeoutError if exceeds 5 seconds
    return compute_something()
```

## Circuit Breaker

```python
from pyresilience import resilient, CircuitBreakerConfig

@resilient(circuit_breaker=CircuitBreakerConfig(
    failure_threshold=5,
    recovery_timeout=30.0,
    success_threshold=2,
))
def call_external_service():
    return requests.get("https://api.example.com").json()
```

## Fallback

```python
from pyresilience import resilient, FallbackConfig

@resilient(fallback=FallbackConfig(handler=lambda e: {"status": "cached"}))
def get_status():
    return requests.get("https://api.example.com/status").json()
```

## Bulkhead

```python
from pyresilience import resilient, BulkheadConfig

@resilient(bulkhead=BulkheadConfig(max_concurrent=10))
def limited_operation():
    return process_request()
```

## Rate Limiter

Limit call rate using a token bucket algorithm. Useful for respecting API rate limits.

```python
from pyresilience import resilient, RateLimiterConfig

# Allow 10 calls per second, reject immediately if exceeded
@resilient(rate_limiter=RateLimiterConfig(max_calls=10, period=1.0))
def call_api():
    return requests.get("https://api.example.com").json()

# Allow 100 calls per minute, wait up to 5s for a token
@resilient(rate_limiter=RateLimiterConfig(max_calls=100, period=60.0, max_wait=5.0))
async def rate_limited_call():
    ...
```

## Cache

Cache function results with TTL and LRU eviction. Avoids redundant calls to slow backends.

```python
from pyresilience import resilient, CacheConfig

# Cache up to 256 results for 5 minutes
@resilient(cache=CacheConfig(max_size=256, ttl=300.0))
def get_user(user_id: int) -> dict:
    return db.query(f"SELECT * FROM users WHERE id = {user_id}")

get_user(42)  # executes query
get_user(42)  # returns cached result
```

## Registry

Share resilience state (circuit breakers, rate limiters) across multiple functions:

```python
from pyresilience import ResilienceRegistry, ResilienceConfig, RetryConfig, CircuitBreakerConfig

registry = ResilienceRegistry()
registry.register("payment-api", ResilienceConfig(
    retry=RetryConfig(max_attempts=3),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
))

@registry.decorator("payment-api")
async def charge_card(amount: float) -> dict:
    ...

@registry.decorator("payment-api")
async def refund_card(amount: float) -> dict:
    ...

# Both share the same circuit breaker state
```

## Combining Patterns

```python
from pyresilience import (
    resilient, RetryConfig, TimeoutConfig,
    CircuitBreakerConfig, FallbackConfig,
    RateLimiterConfig, CacheConfig,
)

@resilient(
    retry=RetryConfig(max_attempts=3, delay=0.5),
    timeout=TimeoutConfig(seconds=10),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
    rate_limiter=RateLimiterConfig(max_calls=20, period=1.0),
    cache=CacheConfig(max_size=100, ttl=60.0),
    fallback=FallbackConfig(handler=lambda e: None),
)
def resilient_api_call(endpoint: str):
    return requests.get(endpoint).json()
```

Execution order: Cache check > Circuit Breaker > Rate Limiter > Bulkhead > Retry > Timeout > Function

## Presets

Opinionated defaults for common integration patterns:

```python
from pyresilience import resilient
from pyresilience.presets import http_policy, db_policy, queue_policy, strict_policy

@resilient(**http_policy())
def call_api(url: str) -> dict:
    return requests.get(url).json()

@resilient(**db_policy())
def query_db(sql: str) -> list:
    return cursor.execute(sql).fetchall()

@resilient(**queue_policy())
async def publish_message(msg: dict) -> None:
    await producer.send(msg)

@resilient(**strict_policy())
def latency_sensitive() -> dict:
    ...
```

## Async Support

All patterns work with async functions automatically:

```python
@resilient(
    retry=RetryConfig(max_attempts=3),
    timeout=TimeoutConfig(seconds=5),
)
async def async_fetch(url: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.json()
```

## Observability

### Event Listeners

```python
from pyresilience import resilient, RetryConfig, ResilienceEvent

def log_event(event: ResilienceEvent):
    print(f"[{event.event_type.value}] {event.function_name} "
          f"attempt={event.attempt} {event.detail}")

@resilient(
    retry=RetryConfig(max_attempts=3),
    listeners=[log_event],
)
def monitored_function():
    return do_work()
```

### Structured JSON Logging

```python
from pyresilience import resilient, RetryConfig, JsonEventLogger

logger = JsonEventLogger()

@resilient(retry=RetryConfig(max_attempts=3), listeners=[logger])
def api_call():
    return do_work()
```

### Metrics Collection

```python
from pyresilience import resilient, RetryConfig, MetricsCollector

metrics = MetricsCollector()

@resilient(retry=RetryConfig(max_attempts=3), listeners=[metrics])
def api_call():
    return do_work()

# After calls:
print(metrics.summary())
# {'total_events': 5, 'success_rate': 0.8, 'p99_latency': 1.23, ...}
```
