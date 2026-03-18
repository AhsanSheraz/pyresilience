# API Reference

## Decorator

### `resilient`

The main decorator that applies resilience patterns.

```python
@resilient(
    retry=RetryConfig(...),
    timeout=TimeoutConfig(...),
    circuit_breaker=CircuitBreakerConfig(...),
    fallback=FallbackConfig(...),
    bulkhead=BulkheadConfig(...),
    listeners=[...],
)
```

Can also be used bare: `@resilient` applies default retry (3 attempts).

## Configuration Classes

### `RetryConfig`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_attempts` | `int` | `3` | Maximum attempts including first call |
| `delay` | `float` | `1.0` | Initial delay in seconds |
| `backoff_factor` | `float` | `2.0` | Multiplier for delay after each retry |
| `max_delay` | `float` | `60.0` | Maximum delay cap |
| `jitter` | `bool` | `True` | Add randomized jitter |
| `retry_on` | `Sequence[Type]` | `(Exception,)` | Exception types to retry |

### `TimeoutConfig`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `seconds` | `float` | `30.0` | Timeout duration |

### `CircuitBreakerConfig`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `failure_threshold` | `int` | `5` | Failures before opening |
| `recovery_timeout` | `float` | `30.0` | Seconds before half-open |
| `success_threshold` | `int` | `2` | Successes to close from half-open |
| `error_types` | `Sequence[Type]` | `(Exception,)` | Failures that count |

### `FallbackConfig`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `handler` | `Callable or Any` | `None` | Fallback value or `fn(exc)` |
| `fallback_on` | `Sequence[Type]` | `(Exception,)` | Exceptions triggering fallback |

### `BulkheadConfig`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_concurrent` | `int` | `10` | Max concurrent executions |
| `max_wait` | `float` | `0.0` | Max wait for slot (0=fail immediately) |

## Events

### `ResilienceEvent`

| Field | Type | Description |
|-------|------|-------------|
| `event_type` | `EventType` | Type of event |
| `function_name` | `str` | Decorated function name |
| `attempt` | `int` | Current attempt number |
| `error` | `BaseException?` | The exception, if any |
| `detail` | `str` | Additional detail |

### `EventType`

`RETRY`, `RETRY_EXHAUSTED`, `TIMEOUT`, `CIRCUIT_OPEN`, `CIRCUIT_HALF_OPEN`, `CIRCUIT_CLOSED`, `FALLBACK_USED`, `BULKHEAD_REJECTED`, `SUCCESS`, `FAILURE`

## Exceptions

### `BulkheadFullError`

Raised when the bulkhead has no available slots and `max_wait` is exceeded.
