# Retry

The retry pattern automatically retries a failed operation with configurable delays, backoff strategies, and jitter. This handles transient failures like network blips and temporary service unavailability.

## Concepts

When a call fails with a retryable exception, the retry mechanism:

1. Waits for a calculated delay
2. Retries the operation
3. Repeats until success or max attempts are exhausted

The delay between retries grows using **exponential backoff**:

```
attempt 1: delay = 1.0s
attempt 2: delay = 1.0 * 2.0 = 2.0s
attempt 3: delay = 2.0 * 2.0 = 4.0s  (capped at max_delay)
```

**Jitter** adds randomness to prevent the [thundering herd problem](https://en.wikipedia.org/wiki/Thundering_herd_problem) — when many clients retry simultaneously after an outage.

## Configuration

```python
from pyresilience import RetryConfig

config = RetryConfig(
    max_attempts=3,           # 3 total attempts (1 initial + 2 retries)
    delay=1.0,                # 1 second initial delay
    backoff_factor=2.0,       # Double the delay each retry
    max_delay=60.0,           # Never wait more than 60 seconds
    jitter=True,              # Add randomized jitter
    retry_on=(Exception,),    # Which exceptions to retry
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_attempts` | `int` | `3` | Total number of attempts (including the first call) |
| `delay` | `float` | `1.0` | Initial delay between retries in seconds |
| `backoff_factor` | `float` | `2.0` | Multiplier applied to delay after each retry |
| `max_delay` | `float` | `60.0` | Maximum delay between retries in seconds |
| `jitter` | `bool` | `True` | Add random jitter to delay (10% floor to 1.0x of calculated delay — never produces zero-delay) |
| `retry_on` | `Sequence[Type]` | `(Exception,)` | Exception types that trigger a retry |
| `retry_on_result` | `Callable[[Any], bool]` | `None` | Predicate to retry based on return value |

## Usage

### Basic Retry

```python
from pyresilience import resilient, RetryConfig

@resilient(retry=RetryConfig(max_attempts=3, delay=1.0))
def fetch_data():
    return requests.get("https://api.example.com/data").json()
```

### Custom Exception Types

Only retry on specific exceptions:

```python
import requests

@resilient(retry=RetryConfig(
    max_attempts=5,
    retry_on=(requests.ConnectionError, requests.Timeout),
))
def call_api() -> dict:
    return requests.get("https://api.example.com").json()
```

A `ValueError` will not be retried — it will propagate immediately.

### Aggressive Retry for Queues

```python
@resilient(retry=RetryConfig(
    max_attempts=10,
    delay=2.0,
    backoff_factor=2.0,
    max_delay=120.0,
    jitter=True,
))
async def publish_message(msg: dict) -> None:
    await producer.send(msg)
```

### No Backoff (Fixed Delay)

```python
@resilient(retry=RetryConfig(
    max_attempts=3,
    delay=0.5,
    backoff_factor=1.0,  # No exponential increase
    jitter=False,
))
def simple_retry():
    return do_something()
```

### Retry on Result

Retry based on return values instead of (or in addition to) exceptions:

```python
@resilient(retry=RetryConfig(
    max_attempts=5,
    delay=1.0,
    retry_on_result=lambda r: r.get("status") == 429,  # Retry on rate limit
))
def call_api() -> dict:
    return requests.get("https://api.example.com").json()
```

The predicate receives the return value. If it returns `True`, the call is retried. On the last attempt, the result is returned regardless of the predicate.

```python
# Retry until a non-empty result
@resilient(retry=RetryConfig(
    max_attempts=3,
    delay=0.5,
    retry_on_result=lambda r: r is None or len(r) == 0,
))
def poll_queue() -> list:
    return queue.receive_messages()
```

## Events

| Event | When |
|-------|------|
| `EventType.RETRY` | A retry attempt is about to be made |
| `EventType.RETRY_EXHAUSTED` | All retry attempts have been used up |
| `EventType.SUCCESS` | The call succeeded (includes attempt number) |
| `EventType.FAILURE` | The call failed with a non-retryable exception |

```python
def on_event(event):
    if event.event_type == EventType.RETRY:
        print(f"Retrying {event.function_name} (attempt {event.attempt}): {event.detail}")
    elif event.event_type == EventType.RETRY_EXHAUSTED:
        print(f"All retries exhausted for {event.function_name}: {event.error}")
```

## Retry Budget

A retry budget limits the total number of retries across all decorated functions, preventing cascading retry storms during widespread outages.

```python
from pyresilience import resilient, RetryConfig, RetryBudgetConfig, RetryBudget

budget = RetryBudget(RetryBudgetConfig(max_retries=100, refill_rate=10))

@resilient(retry=RetryConfig(max_attempts=3, retry_budget=budget))
def call_service_a():
    return requests.get("https://a.example.com").json()

@resilient(retry=RetryConfig(max_attempts=3, retry_budget=budget))
def call_service_b():
    return requests.get("https://b.example.com").json()
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_retries` | `int` | `100` | Maximum retry tokens in the budget pool |
| `refill_rate` | `float` | `10` | Tokens refilled per second |

When the budget is exhausted, retry attempts are skipped and the last exception propagates immediately. The budget refills over time at the configured rate.

This is especially useful in microservice architectures where many functions share the same downstream dependency — if the dependency is down, the budget prevents all functions from retrying simultaneously.

## Backoff Strategies

### Exponential Backoff (default)

```python
RetryConfig(delay=1.0, backoff_factor=2.0)
# Delays: 1s, 2s, 4s, 8s, 16s, ...
```

### Linear Backoff

```python
RetryConfig(delay=1.0, backoff_factor=1.0)
# Delays: 1s, 1s, 1s, 1s, ...
```

### Aggressive Backoff

```python
RetryConfig(delay=0.1, backoff_factor=3.0, max_delay=30.0)
# Delays: 0.1s, 0.3s, 0.9s, 2.7s, 8.1s, 24.3s, 30s (capped), ...
```
