# CircuitBreaker

The circuit breaker pattern prevents an application from repeatedly trying to execute an operation that is likely to fail. It allows the system to recover by temporarily blocking calls to a failing service.

## Concepts

The circuit breaker has three states:

```
CLOSED ──(failures >= threshold)──> OPEN
  ^                                    |
  |                            (recovery_timeout)
  |                                    |
  └──(successes >= threshold)── HALF_OPEN
```

| State | Behavior |
|-------|----------|
| **CLOSED** | Normal operation. Calls pass through. Failures are counted. |
| **OPEN** | All calls are immediately rejected with `RuntimeError`. No calls reach the protected function. |
| **HALF_OPEN** | A limited number of calls are allowed through to test if the service has recovered. |

### State Transitions

- **CLOSED -> OPEN**: When consecutive failures reach `failure_threshold`, or failure rate exceeds `failure_rate_threshold` within a sliding window
- **OPEN -> HALF_OPEN**: After `recovery_timeout` seconds have elapsed
- **HALF_OPEN -> CLOSED**: When `success_threshold` consecutive successes occur
- **HALF_OPEN -> OPEN**: On any failure during the half-open period

## Configuration

### Basic (consecutive count)

```python
from pyresilience import CircuitBreakerConfig

config = CircuitBreakerConfig(
    failure_threshold=5,      # Open after 5 consecutive failures
    recovery_timeout=30.0,    # Wait 30s before trying again
    success_threshold=2,      # Need 2 successes in half-open to close
    error_types=(Exception,), # Which exceptions count as failures
)
```

### Sliding Window (failure rate %)

```python
config = CircuitBreakerConfig(
    sliding_window_size=100,        # Track last 100 calls
    failure_rate_threshold=0.5,     # Open at 50% failure rate
    minimum_calls=10,               # Need at least 10 calls before evaluating
    recovery_timeout=30.0,
)
```

### Slow Call Detection

```python
config = CircuitBreakerConfig(
    sliding_window_size=100,
    failure_rate_threshold=0.5,
    slow_call_duration=2.0,         # Calls > 2s are "slow"
    slow_call_rate_threshold=0.8,   # Open if 80% of calls are slow
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `failure_threshold` | `int` | `5` | Consecutive failures before the circuit opens (used when `sliding_window_size=0`) |
| `recovery_timeout` | `float` | `30.0` | Seconds to wait in OPEN before transitioning to HALF_OPEN |
| `success_threshold` | `int` | `2` | Consecutive successes in HALF_OPEN needed to close the circuit |
| `error_types` | `Sequence[Type]` | `(Exception,)` | Exception types that count as failures |
| `sliding_window_size` | `int` | `0` | Size of sliding window (0 = use consecutive count mode) |
| `failure_rate_threshold` | `float` | `0.5` | Failure rate (0.0–1.0) to trip the circuit in sliding window mode |
| `minimum_calls` | `int` | `0` | Minimum calls in window before evaluating thresholds |
| `slow_call_duration` | `float` | `0.0` | Duration in seconds above which a call is considered "slow" (0 = disabled) |
| `slow_call_rate_threshold` | `float` | `1.0` | Slow call rate (0.0–1.0) to trip the circuit |

## Usage

### Basic Usage

```python
from pyresilience import resilient, CircuitBreakerConfig

@resilient(circuit_breaker=CircuitBreakerConfig(
    failure_threshold=5,
    recovery_timeout=30.0,
))
def call_payment_service(amount: float) -> dict:
    return requests.post("/charge", json={"amount": amount}).json()
```

### With Specific Error Types

Only count certain exceptions as failures:

```python
import requests

@resilient(circuit_breaker=CircuitBreakerConfig(
    failure_threshold=3,
    error_types=(requests.ConnectionError, requests.Timeout),
))
def call_api() -> dict:
    return requests.get("https://api.example.com").json()
```

`ValueError` or `json.JSONDecodeError` won't trip the circuit — only connection and timeout errors will.

### With Fallback

Provide a fallback when the circuit is open:

```python
from pyresilience import resilient, CircuitBreakerConfig, FallbackConfig

@resilient(
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
    fallback=FallbackConfig(handler=lambda e: {"status": "degraded"}),
)
def get_status() -> dict:
    return requests.get("https://api.example.com/status").json()
```

When the circuit is open, instead of raising `RuntimeError`, the fallback value is returned.

### Async Usage

```python
@resilient(circuit_breaker=CircuitBreakerConfig(failure_threshold=5))
async def async_call() -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get("https://api.example.com") as resp:
            return await resp.json()
```

## Metrics

Access real-time circuit breaker metrics via the `.metrics` property:

```python
from pyresilience._circuit_breaker import CircuitBreaker

cb = CircuitBreaker(CircuitBreakerConfig(
    sliding_window_size=100,
    failure_rate_threshold=0.5,
))

# After some calls...
print(cb.metrics)
# {"failure_rate": 0.15, "slow_call_rate": 0.0, "total_calls": 47, "state": "closed"}
```

## Events

The circuit breaker emits these events:

| Event | When |
|-------|------|
| `EventType.CIRCUIT_OPEN` | Circuit transitions to OPEN (or a call is rejected while OPEN) |
| `EventType.CIRCUIT_HALF_OPEN` | Circuit transitions to HALF_OPEN |
| `EventType.CIRCUIT_CLOSED` | Circuit transitions back to CLOSED |
| `EventType.SLOW_CALL` | A call exceeded `slow_call_duration` |

```python
from pyresilience import resilient, CircuitBreakerConfig, EventType

def on_event(event):
    if event.event_type == EventType.CIRCUIT_OPEN:
        alert_ops_team(f"Circuit opened for {event.function_name}")

@resilient(
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
    listeners=[on_event],
)
def critical_service():
    ...
```

## Direct Usage

You can also use `CircuitBreaker` directly without the decorator:

```python
from pyresilience import CircuitBreaker, CircuitBreakerConfig

cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3))

if cb.allow_request():
    try:
        result = do_something()
        cb.record_success()
    except Exception:
        cb.record_failure()
        raise

# Check state
print(cb.state)  # CircuitState.CLOSED
```
