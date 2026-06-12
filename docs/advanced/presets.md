# Presets

Presets are opinionated default configurations for common integration patterns. Instead of tuning every parameter, pick a preset that matches your use case.

## Available Presets

### `http_policy()`

Optimized for HTTP API calls — fast timeout, moderate retries, standard circuit breaker.

```python
from pyresilience import resilient
from pyresilience.presets import http_policy

@resilient(**http_policy())
def call_api(url: str) -> dict:
    return requests.get(url).json()
```

| Parameter | Default | Why |
|-----------|---------|-----|
| Timeout | 10s | APIs should respond quickly |
| Max retries | 3 | Enough to handle transient failures |
| Retry delay | 0.5s | Start fast, backoff exponentially |
| Backoff factor | 2.0 | Standard exponential backoff |
| Max delay | 30s | Don't wait too long between retries |
| Circuit failure threshold | 5 | Open after 5 failures |
| Circuit recovery | 30s | Check again after 30 seconds |
| Jitter | Yes | Prevent thundering herd |

**Customizable:**

```python
@resilient(**http_policy(
    timeout_seconds=5.0,
    max_retries=5,
    circuit_failure_threshold=10,
    rate_limit=RateLimiterConfig(max_calls=100, period=60.0),
    cache=CacheConfig(max_size=256, ttl=300.0),
))
def call_api(): ...
```

### `db_policy()`

Optimized for database calls — longer timeout, fewer retries, connection pool protection.

```python
from pyresilience.presets import db_policy

@resilient(**db_policy())
def query_db(sql: str) -> list:
    return cursor.execute(sql).fetchall()
```

| Parameter | Default | Why |
|-----------|---------|-----|
| Timeout | 30s | Queries can be slow |
| Max retries | 2 | Fewer retries to avoid connection pile-up |
| Retry delay | 1.0s | Longer initial delay |
| Backoff factor | 1.5 | Less aggressive than HTTP |
| Max delay | 10s | Don't wait too long |
| Circuit failure threshold | 3 | Trip faster — DB issues are serious |
| Circuit recovery | 60s | Give the DB more time to recover |
| Bulkhead | 10 concurrent | Protect connection pool |

### `queue_policy()`

Optimized for message queue producers/consumers — more retries, higher failure tolerance.

```python
from pyresilience.presets import queue_policy

@resilient(**queue_policy())
async def publish_message(msg: dict) -> None:
    await producer.send(msg)
```

| Parameter | Default | Why |
|-----------|---------|-----|
| Timeout | 15s | Moderate timeout |
| Max retries | 5 | Messages should eventually be delivered |
| Retry delay | 2.0s | Longer delay for queue recovery |
| Backoff factor | 2.0 | Standard exponential |
| Max delay | 60s | Allow long waits for queue recovery |
| Circuit failure threshold | 10 | Higher tolerance — queues are bursty |
| Circuit recovery | 60s | Standard recovery time |

### `strict_policy()`

Fail-fast policy for latency-sensitive paths where slow is worse than failing.

```python
from pyresilience.presets import strict_policy

@resilient(**strict_policy())
def cache_lookup(key: str) -> dict:
    return redis_client.get(key)
```

| Parameter | Default | Why |
|-----------|---------|-----|
| Timeout | 5s | Fail fast |
| Max attempts | 1 | No retries (1 total attempt) |
| Retry delay | 0.1s | Minimal delay |
| Backoff factor | 1.0 | No backoff |
| Max delay | 0.5s | Cap very low |
| Circuit failure threshold | 3 | Trip quickly |
| Circuit recovery | 60s | Standard recovery |
| Jitter | No | Deterministic for debugging |

### `llm_policy()`

Optimized for LLM and rate-limited HTTP APIs (OpenAI, Anthropic, Stripe, GitHub, ...) — retries
on 429/5xx responses, honors the server's `Retry-After` header, and throttles client-side so you
hit the rate limit less often in the first place.

```python
from pyresilience import resilient, llm_policy

@resilient(**llm_policy())
def ask_model(prompt: str):
    return client.chat.completions.create(model="...", messages=[...])
```

| Parameter | Default | Why |
|-----------|---------|-----|
| Timeout | 60s | LLM responses can be slow |
| Max attempts | 4 | Rate limits usually clear within a few retries |
| Retry delay | 1.0s | Base for exponential backoff when no `Retry-After` is present |
| Retry on status | 429, 500, 502, 503, 504 | Retries these response codes via `retry_on_status()` |
| `Retry-After` handling | On, capped at 60s | `retry_after_delay()` parses the header; falls back to backoff |
| Rate limiter | 60 calls / 60s | Client-side smoothing to avoid 429s proactively |
| Circuit failure threshold | 5 | Stop hammering a failing provider |
| Circuit recovery | 30s | Re-probe after a short cool-down |

**Customizable:**

```python
@resilient(**llm_policy(
    max_calls=500, period=60.0,                  # paid-tier rate limits
    retry_on_status_codes=(429,),                # only retry rate limits
    ignore_on=(AuthError, QuotaExceededError),   # terminal errors: no retry, no circuit failure
    max_concurrent=8,                            # optional bulkhead
))
def ask_model(prompt: str): ...
```

`ignore_on` propagates to **both** the retry and the circuit breaker configs — terminal client
errors fail fast and don't trip the circuit. See [HTTP & LLM Helpers](http.md) for the underlying
`retry_on_status()` / `retry_after_delay()` building blocks.

## Custom Presets

Create your own presets following the same pattern:

```python
from pyresilience._types import RetryConfig, TimeoutConfig, CircuitBreakerConfig, RateLimiterConfig

def my_api_policy(**overrides):
    defaults = {
        "retry": RetryConfig(max_attempts=3, delay=0.5),
        "timeout": TimeoutConfig(seconds=15),
        "circuit_breaker": CircuitBreakerConfig(failure_threshold=5),
        "rate_limiter": RateLimiterConfig(max_calls=50, period=1.0),
    }
    defaults.update(overrides)
    return defaults
```
