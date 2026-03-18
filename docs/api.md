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
    rate_limiter=RateLimiterConfig(...),
    cache=CacheConfig(...),
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

### `RateLimiterConfig`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_calls` | `int` | `10` | Max calls allowed per period |
| `period` | `float` | `1.0` | Time period in seconds |
| `max_wait` | `float` | `0.0` | Max wait for token (0=reject immediately) |

### `CacheConfig`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_size` | `int` | `256` | Max cached entries (LRU eviction) |
| `ttl` | `float` | `300.0` | Time-to-live in seconds (0=no expiration) |

## Registry

### `ResilienceRegistry`

Centralized management of named resilience configurations.

| Method | Description |
|--------|-------------|
| `register(name, config)` | Register a named config |
| `get(name)` | Get config by name (returns `None` if missing) |
| `get_or_default(name)` | Get config, fall back to default |
| `set_default(config)` | Set the default config |
| `decorator(name)` | Create a decorator using the named config |
| `unregister(name)` | Remove a named config |
| `clear()` | Remove all configs |
| `names` | List all registered names |

## Presets

### `http_policy(**kwargs)`

Optimized for HTTP API calls: 10s timeout, 3 retries, circuit breaker at 5 failures.

### `db_policy(**kwargs)`

Optimized for database calls: 30s timeout, 2 retries, bulkhead of 10, circuit at 3 failures.

### `queue_policy(**kwargs)`

Optimized for message queues: 15s timeout, 5 retries, circuit at 10 failures.

### `strict_policy(**kwargs)`

Fail-fast policy: 5s timeout, 1 retry, no jitter.

## Observability

### `JsonEventLogger`

`ResilienceListener` that emits structured JSON log lines. Uses `orjson` if available, falls back to stdlib `json`.

### `MetricsCollector`

In-memory metrics collector.

| Method/Property | Description |
|----------------|-------------|
| `summary()` | Overall metrics dict |
| `get_counts(function_name=None)` | Event counts |
| `get_latencies(function_name=None)` | Latency percentiles |
| `reset()` | Reset all metrics |

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

`RETRY`, `RETRY_EXHAUSTED`, `TIMEOUT`, `CIRCUIT_OPEN`, `CIRCUIT_HALF_OPEN`, `CIRCUIT_CLOSED`, `FALLBACK_USED`, `BULKHEAD_REJECTED`, `RATE_LIMITED`, `CACHE_HIT`, `CACHE_MISS`, `SUCCESS`, `FAILURE`

## Exceptions

### `BulkheadFullError`

Raised when the bulkhead has no available slots and `max_wait` is exceeded.

### `RateLimitExceededError`

Raised when the rate limiter rejects a call (no tokens available and `max_wait` exceeded).
