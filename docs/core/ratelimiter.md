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
| `cost` | `Callable[..., float]` | `None` | Receives the call's arguments and returns how many units of the primary limit the call consumes. Default: 1 per call |
| `actual_cost` | `Callable[[Any], Optional[float]]` | `None` | Receives the call's result and returns the units really consumed |
| `limits` | `Sequence[RateLimit]` | `()` | Additional limits enforced together with the primary one |
| `feedback` | `Callable[[Any], Optional[RateLimitFeedback]]` | `None` | Reads what the server reported about its limits from each attempt's result or exception |
| `charge_retries` | `bool` | `False` | Debit every retry attempt against the limits |

The primary limit (`max_calls` per `period`) is named `"calls"`. Each additional limit is a `RateLimit`:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_units` | `float` | required | Units allowed per period (calls, tokens, bytes, ...) |
| `period` | `float` | required | Time period in seconds |
| `name` | `str` | `"limit<N>"` | Name used in events, errors and server feedback |
| `cost` | `Callable[..., float]` | `None` | Units a call consumes, computed from its arguments. Default: 1 per call |
| `actual_cost` | `Callable[[Any], Optional[float]]` | `None` | Units really consumed, computed from the result |

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

### Several Limits at Once

A call proceeds only when **every** limit has capacity. When one limit rejects it, nothing is consumed from the others.

```python
from pyresilience import resilient, RateLimit, RateLimiterConfig

# 10 calls per second AND 1,000 calls per day
@resilient(rate_limiter=RateLimiterConfig(
    max_calls=10,
    period=1.0,
    limits=[RateLimit(max_units=1000, period=86400.0, name="daily")],
))
def call_api() -> dict: ...
```

### Weighted Calls

Not every call costs the same. `cost` receives the call's arguments and returns its weight:

```python
# A batch of 50 items uses 50 units of a 500-items-per-minute limit
@resilient(rate_limiter=RateLimiterConfig(
    max_calls=500,
    period=60.0,
    cost=lambda items: len(items),
))
def send_batch(items: list) -> None: ...
```

A call whose cost is larger than a limit's whole capacity can never pass and is rejected immediately, without waiting.

### Token Limits for LLM APIs

LLM providers limit requests per minute **and** tokens per minute. Reserve an estimate before the call and settle the difference afterwards:

```python
@resilient(rate_limiter=RateLimiterConfig(
    max_calls=60,               # requests per minute
    period=60.0,
    max_wait=10.0,
    limits=[RateLimit(
        max_units=90_000,       # tokens per minute
        period=60.0,
        name="tokens",
        cost=lambda prompt, **kw: len(prompt) // 4 + kw.get("max_tokens", 256),
        actual_cost=lambda response: response.usage.total_tokens,
    )],
))
def complete(prompt: str, *, max_tokens: int = 256):
    return client.responses.create(model="...", input=prompt, max_output_tokens=max_tokens)
```

- `cost` runs before the call and reserves the estimate.
- `actual_cost` runs after a successful call. Unused tokens are given back; extra tokens are charged, which can put the limit into debt and delay later calls.
- A failed call keeps its estimate charged.
- With retries, the call has one reservation. It stays open across failed attempts and is settled by the first attempt that reports its usage; a later attempt that reports usage is debited what it used.
- An exception raised by a `cost` function propagates to the caller.

### Following the Server

The server knows its limits better than any client-side estimate. A `feedback` function reads each attempt's response (or the response attached to a raised exception) and reports it back to the limiter:

```python
from pyresilience import RateLimiterConfig, RateLimit
from pyresilience.contrib.http import rate_limit_feedback

RateLimiterConfig(
    max_calls=60,
    period=60.0,
    limits=[RateLimit(90_000, 60.0, name="tokens", cost=estimate_tokens)],
    feedback=rate_limit_feedback(),
)
```

`rate_limit_feedback()` understands `Retry-After`, OpenAI-style `x-ratelimit-*`, Anthropic-style `anthropic-ratelimit-*`, plain `x-ratelimit-remaining` / `x-ratelimit-reset` and the IETF `RateLimit-*` headers. See [HTTP & LLM Helpers](../advanced/http.md#rate_limit_feedback).

What the limiter does with the report:

| Server says | Limiter does |
|---|---|
| `Retry-After: 20` | Pauses: no call is sent for 20 seconds. Callers wait if `max_wait` allows, else they are rejected |
| 3 requests remaining | Lowers the local `"calls"` level to 3 when it was higher |
| 0 tokens remaining, resets in 12s | Pauses for 12 seconds |

A level is only ever lowered by feedback, never raised. You can write your own function returning a `RateLimitFeedback(retry_after=..., remaining={...})`.

### Charging Retries

By default capacity is taken once per call, and retries are free. With `charge_retries=True` each retry attempt is debited as well, without waiting, so a burst of retries slows down the calls that follow:

```python
@resilient(
    retry=RetryConfig(max_attempts=4),
    rate_limiter=RateLimiterConfig(max_calls=60, period=60.0, charge_retries=True),
)
def call_api() -> dict: ...
```

### Sharing Limits Between Processes

With several replicas, each process has its own bucket and the real rate is multiplied by the replica count. `SharedStateConfig` counts every call in a shared backend so the limit holds for the whole fleet. See [Shared State](../advanced/shared-state.md).

## Events

| Event | When |
|-------|------|
| `EventType.RATE_LIMITED` | A call was rejected because the rate limit was exceeded |

When the configuration uses `cost`, `limits`, `feedback` or `charge_retries`, the event's `detail` and the `RateLimitExceededError` message name the limit that rejected the call, for example `limit 'tokens' exceeded`, or `server feedback` while the limiter is paused.

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
