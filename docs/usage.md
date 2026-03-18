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

## Combining Patterns

```python
from pyresilience import (
    resilient, RetryConfig, TimeoutConfig,
    CircuitBreakerConfig, FallbackConfig,
)

@resilient(
    retry=RetryConfig(max_attempts=3, delay=0.5),
    timeout=TimeoutConfig(seconds=10),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
    fallback=FallbackConfig(handler=lambda e: None),
)
def resilient_api_call(endpoint: str):
    return requests.get(endpoint).json()
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

## Event Listeners

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
