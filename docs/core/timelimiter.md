# TimeLimiter (Timeout)

The time limiter pattern enforces a maximum execution time for each call. If the call exceeds the timeout, it is cancelled and a `TimeoutError` is raised.

## Concepts

By default the timeout wraps each individual call attempt (not the total time across retries). An overall deadline and a stream idle limit can be added on top:

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
    seconds=30.0,              # Maximum execution time
    per_attempt=True,          # True = per attempt, False = total deadline
    total_seconds=None,        # Overall deadline on top of the per-attempt limit
    stream_idle_seconds=None,  # Max gap between items of a streamed result
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `seconds` | `float` | `30.0` | Maximum time in seconds before the call is aborted |
| `per_attempt` | `bool` | `True` | Whether `seconds` applies per attempt or as a total deadline |
| `total_seconds` | `Optional[float]` | `None` | Overall deadline for all attempts and retry waits, enforced together with the per-attempt `seconds`. Requires `per_attempt=True` |
| `stream_idle_seconds` | `Optional[float]` | `None` | Idle limit for results that are iterators or async iterators |
| `pool_size` | `int` | `4` | Thread pool size for sync timeouts |

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

### Per-Attempt Limit and Overall Deadline Together

`total_seconds` bounds the whole call while `seconds` still bounds every attempt. Each attempt gets `min(seconds, time left)`:

```python
@resilient(
    retry=RetryConfig(max_attempts=4, delay=1.0),
    timeout=TimeoutConfig(seconds=10.0, total_seconds=30.0),
)
def call_api() -> dict:
    return requests.get("https://api.example.com").json()
```

```
seconds=10, total_seconds=30

Attempt 1: [─── 10s max ───] TIMEOUT!          wait 1s
Attempt 2: [─── 10s max ───] TIMEOUT!          wait 2s
Attempt 3: [── 7s left ──]   TIMEOUT!          next wait (4s) does not fit
           raise ResilienceTimeoutError("... exceeded total timeout budget of 30.0s")
Total: 30s max
```

When the time left cannot cover the next retry wait, the call stops retrying at once and raises `ResilienceTimeoutError`, chained from the last error. It does not sleep past the deadline. The same applies to `per_attempt=False`. If a fallback is configured for the error, it is used instead.

Two details: an attempt that is cut short by the deadline emits one `TIMEOUT` event, whose detail names the time the attempt really had. And with a bulkhead, the wait for a slot after a retry sleep is bounded by `BulkheadConfig.max_wait`, not by the deadline; if the deadline has passed when the slot is granted, the call stops without another attempt.

With `retry_on_result`, the last result is returned when the budget runs out, as it is when attempts run out.

### Stream Idle Timeout

A call that returns a stream finishes quickly; the waiting happens while the stream is consumed. `stream_idle_seconds` bounds the wait for the first item and between two items:

```python
@resilient(timeout=TimeoutConfig(seconds=30.0, stream_idle_seconds=15.0))
async def stream_completion(prompt: str):
    return client.stream(prompt)   # an async iterator

async for chunk in await stream_completion("hello"):
    ...   # ResilienceTimeoutError if no chunk arrives for 15s
```

- Applies when the function returns an iterator, generator, async iterator or async generator. Other results are returned unchanged.
- The wait for the first item is the time to first token.
- Each sync stream is read by its own daemon thread, started with the first item, so any number of streams can run at once. A read that is abandoned keeps that thread busy until the underlying stream returns.
- After a timeout the stream is finished. Retries and fallbacks do not cover a stream that already started.
- `with` / `async with`, `close()`, `aclose()` and other attributes are passed through to the wrapped stream.

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
        # detail contains "exceeded {seconds}s", "exceeded total {seconds}s budget"
        # or "stream idle for more than {seconds}s"
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
