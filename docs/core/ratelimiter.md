# RateLimiter

The rate limiter pattern controls the rate of calls to a function using a token bucket algorithm. Unlike the bulkhead (which limits concurrent calls), the rate limiter limits calls per time period.

## Concepts

The rate limiter uses a **token bucket** algorithm:

- The bucket holds a maximum number of tokens (equal to `max_calls`)
- Each call consumes one token
- Tokens are refilled continuously at a rate of `max_calls / period`
- If no tokens are available, the call is either rejected or waits

```
Token Bucket (max_calls=5, period=1.0)

Time 0.0s: [*] [*] [*] [*] [*]  (5 tokens)
Call 1:     [*] [*] [*] [*] [ ]  (4 tokens)
Call 2:     [*] [*] [*] [ ] [ ]  (3 tokens)
Call 3:     [*] [*] [ ] [ ] [ ]  (2 tokens)
Call 4:     [*] [ ] [ ] [ ] [ ]  (1 token)
Call 5:     [ ] [ ] [ ] [ ] [ ]  (0 tokens)
Call 6:     REJECTED! (or waits for refill)

Time 0.2s: [*] [ ] [ ] [ ] [ ]  (1 token refilled)
Call 6:     [ ] [ ] [ ] [ ] [ ]  (succeeds now)
```

### Rate Limiter vs Bulkhead

| | Rate Limiter | Bulkhead |
|---|---|---|
| **Limits** | Calls per time window | Concurrent calls |
| **Use case** | API rate limits, throttling | Connection pool protection |
| **Example** | 100 requests/minute | 10 concurrent requests |
| **Algorithm** | Token bucket | Semaphore |

## Configuration

```python
from pyresilience import RateLimiterConfig

config = RateLimiterConfig(
    max_calls=10,    # 10 calls per period
    period=1.0,      # Per 1 second
    max_wait=0.0,    # Reject immediately if no tokens (0 = no waiting)
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_calls` | `int` | `10` | Maximum number of calls allowed per period |
| `period` | `float` | `1.0` | Time period in seconds |
| `max_wait` | `float` | `0.0` | Maximum seconds to wait for a token. `0` means reject immediately. |

## Usage

### Basic Rate Limiting

```python
from pyresilience import resilient, RateLimiterConfig

# Allow 10 requests per second
@resilient(rate_limiter=RateLimiterConfig(max_calls=10, period=1.0))
def call_api(endpoint: str) -> dict:
    return requests.get(endpoint).json()
```

### With Waiting

Allow callers to wait for a token instead of immediate rejection:

```python
# 100 calls per minute, wait up to 5 seconds for a token
@resilient(rate_limiter=RateLimiterConfig(
    max_calls=100,
    period=60.0,
    max_wait=5.0,
))
def call_api() -> dict:
    return requests.get("https://api.example.com").json()
```

### Async Rate Limiting

```python
@resilient(rate_limiter=RateLimiterConfig(max_calls=50, period=1.0))
async def async_call() -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get("https://api.example.com") as resp:
            return await resp.json()
```

### With Fallback

Return a queued/deferred response instead of rejecting:

```python
from pyresilience import (
    resilient, RateLimiterConfig, FallbackConfig, RateLimitExceededError
)

@resilient(
    rate_limiter=RateLimiterConfig(max_calls=10, period=1.0),
    fallback=FallbackConfig(
        handler=lambda e: {"status": "rate_limited", "retry_after": 1},
        fallback_on=(RateLimitExceededError,),
    ),
)
def call_api() -> dict:
    return requests.get("https://api.example.com").json()
```

### Combined with Circuit Breaker

```python
@resilient(
    rate_limiter=RateLimiterConfig(max_calls=100, period=60.0),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
    retry=RetryConfig(max_attempts=3),
)
def robust_call() -> dict:
    return requests.get("https://api.example.com").json()
```

## Events

| Event | When |
|-------|------|
| `EventType.RATE_LIMITED` | A call was rejected because the rate limit was exceeded |

## Exception

```python
from pyresilience import RateLimitExceededError

try:
    result = my_function()
except RateLimitExceededError:
    # Rate limit exceeded, try again later
    time.sleep(1)
```

## Direct Usage

Use the rate limiter without the decorator:

```python
from pyresilience import RateLimiter, RateLimiterConfig

rl = RateLimiter(RateLimiterConfig(max_calls=10, period=1.0))

if rl.acquire():
    result = do_something()
else:
    print("Rate limit exceeded")

# Reset to full capacity
rl.reset()
```
