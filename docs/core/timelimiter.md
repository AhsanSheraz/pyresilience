# TimeLimiter (Timeout)

The time limiter pattern enforces a maximum execution time for each call. If the call exceeds the timeout, it is cancelled and a `TimeoutError` is raised.

## Concepts

The timeout wraps each individual call attempt (not the total time across retries):

```
@resilient(retry=RetryConfig(max_attempts=3), timeout=TimeoutConfig(seconds=5))

Attempt 1: [─── 5s max ───] TIMEOUT!
Attempt 2: [── 3s ──] SUCCESS!
```

### Implementation

| Mode | How it works |
|------|-------------|
| **Sync** | Runs the function in a thread pool, uses `future.result(timeout=...)` with best-effort thread cancellation |
| **Async** | Uses `asyncio.wait_for(coro, timeout=...)` |

!!! note "Thread Cancellation (Sync)"
    On CPython, when a sync function exceeds its timeout, pyresilience uses `ctypes.pythonapi.PyThreadState_SetAsyncExc` for best-effort thread interruption. This raises an exception in the worker thread so it can clean up. However, blocking C extensions (e.g., `socket.recv()` without a timeout) cannot be interrupted. The original exception chain is preserved via `from exc`.

## Configuration

```python
from pyresilience import TimeoutConfig

config = TimeoutConfig(
    seconds=30.0,       # Maximum execution time
    per_attempt=True,    # True = per attempt, False = total deadline
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `seconds` | `float` | `30.0` | Maximum time in seconds before the call is aborted |
| `per_attempt` | `bool` | `True` | Whether timeout applies per attempt or as a total deadline |

## Usage

### Basic Timeout

```python
from pyresilience import resilient, TimeoutConfig

@resilient(timeout=TimeoutConfig(seconds=5.0))
def slow_operation() -> dict:
    return requests.get("https://slow-api.example.com").json()
```

### With Retry

Each retry attempt gets its own timeout:

```python
@resilient(
    retry=RetryConfig(max_attempts=3, delay=1.0),
    timeout=TimeoutConfig(seconds=10),
)
def call_api() -> dict:
    return requests.get("https://api.example.com").json()
```

Total maximum time: 3 attempts * 10s timeout + 2 delays = ~32s worst case.

### Async Timeout

```python
@resilient(timeout=TimeoutConfig(seconds=5.0))
async def async_fetch(url: str) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.json()
```

### Per-Attempt vs Total Deadline

By default (`per_attempt=True`), each retry attempt gets the full timeout:

```
@resilient(retry=RetryConfig(max_attempts=3), timeout=TimeoutConfig(seconds=5))

Attempt 1: [─── 5s max ───] TIMEOUT!
Attempt 2: [─── 5s max ───] TIMEOUT!
Attempt 3: [── 3s ──] SUCCESS!
Total: up to 15s + delays
```

With `per_attempt=False`, the timeout is a total deadline shared across all attempts:

```
@resilient(retry=RetryConfig(max_attempts=3), timeout=TimeoutConfig(seconds=5, per_attempt=False))

Attempt 1: [── 3s ──] TIMEOUT!
Attempt 2: [─ 1.5s ─] TIMEOUT! (remaining budget)
Attempt 3: TIMEOUT! (no budget left)
Total: 5s max
```

Use `per_attempt=False` when you have a strict SLA and need to bound total latency:

```python
@resilient(
    retry=RetryConfig(max_attempts=3, delay=0.5),
    timeout=TimeoutConfig(seconds=5.0, per_attempt=False),
)
def call_with_deadline() -> dict:
    return requests.get("https://api.example.com").json()
```

### Strict Timeout (Fail Fast)

For latency-sensitive paths:

```python
@resilient(timeout=TimeoutConfig(seconds=1.0))
def cache_lookup(key: str) -> dict:
    return redis_client.get(key)
```

## Events

| Event | When |
|-------|------|
| `EventType.TIMEOUT` | A call exceeded the configured timeout |

```python
def on_event(event):
    if event.event_type == EventType.TIMEOUT:
        print(f"{event.function_name} timed out: {event.detail}")
        # detail contains "exceeded {seconds}s"
```

## Exception

```python
try:
    result = slow_function()
except TimeoutError as e:
    print(e)  # "slow_function exceeded timeout of 5.0s"
```

!!! note
    pyresilience raises `builtins.TimeoutError`, not `asyncio.TimeoutError`. This is consistent across sync and async modes.
