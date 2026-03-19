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
| `retry_on_result` | `Callable[[Any], bool]` | `None` | Predicate to retry based on return value |

### `TimeoutConfig`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `seconds` | `float` | `30.0` | Timeout duration |
| `per_attempt` | `bool` | `True` | Per-attempt timeout (`True`) or total deadline (`False`) |
| `pool_size` | `int` | `4` | Thread pool size for sync timeouts |

### `CircuitBreakerConfig`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `failure_threshold` | `int` | `5` | Failures before opening (consecutive count mode) |
| `recovery_timeout` | `float` | `30.0` | Seconds before half-open |
| `success_threshold` | `int` | `2` | Successes to close from half-open |
| `error_types` | `Sequence[Type]` | `(Exception,)` | Failures that count |
| `sliding_window_size` | `int` | `0` | Sliding window size (0 = consecutive count mode) |
| `failure_rate_threshold` | `float` | `0.5` | Failure rate to trip (sliding window mode) |
| `minimum_calls` | `int` | `0` | Min calls before evaluating thresholds |
| `slow_call_duration` | `float` | `0.0` | Slow call threshold in seconds (0 = disabled) |
| `slow_call_rate_threshold` | `float` | `1.0` | Slow call rate to trip the circuit |

### `CircuitBreaker` (direct usage)

| Method | Description |
|--------|-------------|
| `allow_request()` | Check if a call is allowed |
| `record_success()` | Record a successful call |
| `record_failure()` | Record a failed call |
| `reset()` | Reset to CLOSED state with zeroed counters |
| `force_open()` | Force transition to OPEN state |
| `force_close()` | Force transition to CLOSED state |
| `state` | Current `CircuitState` |
| `metrics` | Real-time metrics dict (failure_rate, slow_call_rate, total_calls, state) |

### `FallbackConfig`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `handler` | `Callable or Any` | `None` | Fallback value, `fn(exc)`, or async `fn(exc)`. When `None`, `fallback_on` is auto-cleared to `()` |
| `fallback_on` | `Sequence[Type]` | `(Exception,)` | Exceptions triggering fallback. Auto-cleared when `handler=None` |

`FallbackConfig()` is safe to call with no arguments. The handler can be an async function when decorating async functions.

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

### `RetryBudgetConfig`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_retries` | `int` | `100` | Maximum retry tokens in the budget pool |
| `refill_rate` | `float` | `10` | Tokens refilled per second |

### `RetryBudget`

Shared retry budget instance. Created with `RetryBudget(RetryBudgetConfig(...))`.

| Method | Description |
|--------|-------------|
| `acquire()` | Consume a retry token. Returns `True` if granted, `False` if exhausted |
| `available` | Number of tokens currently available |

## Context

### `resilience_context`

A `contextvars.ContextVar[Optional[dict]]` that carries request-scoped metadata into every `ResilienceEvent.context` field.

```python
from pyresilience import resilience_context

resilience_context.set({"trace_id": "abc-123"})
```

## Lifecycle

### `shutdown()`

Drains in-flight calls and releases thread pool resources. Call during application shutdown.

```python
from pyresilience import shutdown

shutdown()
```

### `get_in_flight_count()`

Returns the number of currently executing resilient calls. Requires `enable_in_flight_tracking()` to be called first.

```python
from pyresilience import enable_in_flight_tracking, get_in_flight_count

enable_in_flight_tracking()
# ... after some calls are in progress ...
count = get_in_flight_count()
```

### `enable_in_flight_tracking()`

Activates in-flight call counting. Disabled by default to avoid overhead. Once enabled, `get_in_flight_count()` returns accurate counts.

### `health_check(registry)`

Returns a dict summarizing resilience state for all registered functions in a `ResilienceRegistry`.

```python
from pyresilience import ResilienceRegistry, health_check

status = health_check(registry)
# {"payment-api": {"circuit_breaker": "closed", "in_flight": 3, ...}, ...}
```

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
| `context` | `Optional[dict]` | Request-scoped metadata from `resilience_context` |
| `duration` | `Optional[float]` | Call duration in seconds (set on SUCCESS events) |

### `EventType`

`RETRY`, `RETRY_EXHAUSTED`, `TIMEOUT`, `CIRCUIT_OPEN`, `CIRCUIT_HALF_OPEN`, `CIRCUIT_CLOSED`, `FALLBACK_USED`, `BULKHEAD_REJECTED`, `RATE_LIMITED`, `CACHE_HIT`, `CACHE_MISS`, `SUCCESS`, `FAILURE`, `SLOW_CALL`

## Exceptions

### `BulkheadFullError`

Raised when the bulkhead has no available slots and `max_wait` is exceeded.

### `RateLimitExceededError`

Raised when the rate limiter rejects a call (no tokens available and `max_wait` exceeded).
