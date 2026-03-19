# Quick Start

## Your First Resilient Function

The simplest usage — add retry with default settings:

```python
import requests
from pyresilience import resilient

@resilient
def fetch_data():
    return requests.get("https://api.example.com/data").json()
```

When used without arguments, `@resilient` applies default retry (3 attempts, 1s delay, exponential backoff with jitter).

## Configuring Patterns

Pass configuration objects to enable specific patterns:

```python
import requests
from pyresilience import resilient, RetryConfig, TimeoutConfig

@resilient(
    retry=RetryConfig(max_attempts=3, delay=0.5),
    timeout=TimeoutConfig(seconds=10),
)
def call_api(endpoint: str) -> dict:
    return requests.get(endpoint).json()
```

## Async Support

The decorator auto-detects async functions — no changes needed:

```python
import aiohttp
from pyresilience import resilient, RetryConfig, TimeoutConfig

@resilient(
    retry=RetryConfig(max_attempts=3),
    timeout=TimeoutConfig(seconds=5),
)
async def async_fetch(url: str) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.json()
```

## Full Example

Combine all patterns for production-grade resilience:

```python
from pyresilience import (
    resilient,
    RetryConfig,
    TimeoutConfig,
    CircuitBreakerConfig,
    FallbackConfig,
    BulkheadConfig,
    RateLimiterConfig,
    CacheConfig,
)

@resilient(
    retry=RetryConfig(max_attempts=3, delay=0.5, backoff_factor=2.0),
    timeout=TimeoutConfig(seconds=10),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5, recovery_timeout=30),
    fallback=FallbackConfig(handler=lambda e: {"error": str(e), "cached": True}),
    bulkhead=BulkheadConfig(max_concurrent=20),
    rate_limiter=RateLimiterConfig(max_calls=100, period=60.0),
    cache=CacheConfig(max_size=256, ttl=300.0),
)
def get_user_profile(user_id: int) -> dict:
    import requests
    return requests.get(f"https://api.example.com/users/{user_id}").json()
```

This single decorator:

1. Checks the **cache** for a previously stored result
2. Checks the **circuit breaker** — fails fast if the service is down
3. Checks the **rate limiter** — respects API rate limits
4. Acquires a **bulkhead** slot — limits to 20 concurrent calls
5. **Retries** up to 3 times with exponential backoff on failure
6. **Times out** each attempt after 10 seconds
7. Returns a **fallback** value if all else fails
8. Stores successful results in the **cache**

## Using Presets

For common integration patterns, use opinionated presets instead of manual config:

```python
from pyresilience import resilient
from pyresilience.presets import http_policy, db_policy

@resilient(**http_policy())
def call_api(url: str) -> dict:
    return requests.get(url).json()

@resilient(**db_policy())
def query_db(sql: str) -> list:
    return cursor.execute(sql).fetchall()
```

See [Presets](../advanced/presets.md) for all available presets and their defaults.

## Next Steps

- Explore each [Core Module](../core/circuitbreaker.md) in depth
- Learn about [Observability](../advanced/observability.md)
- Use the [Registry](../advanced/registry.md) to share state across functions
