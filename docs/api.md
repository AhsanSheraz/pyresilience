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
    retry_budget=RetryBudgetConfig(...),
    listeners=[...],
    shared_state=SharedStateConfig(...),
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
| `ignore_on` | `Sequence[Type]` | `()` | Exception types never retried; takes precedence over `retry_on` |
| `delay_func` | `Callable[[int, Any], Optional[float]]` | `None` | Dynamic per-attempt delay from the triggering exception/result; `None` return falls back to exponential backoff |

### `TimeoutConfig`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `seconds` | `float` | `30.0` | Timeout duration |
| `per_attempt` | `bool` | `True` | Per-attempt timeout (`True`) or total deadline (`False`) |
| `pool_size` | `int` | `4` | Thread pool size for sync timeouts |
| `total_seconds` | `Optional[float]` | `None` | Overall deadline for all attempts and retry waits, on top of the per-attempt `seconds`. Requires `per_attempt=True` |
| `stream_idle_seconds` | `Optional[float]` | `None` | Max wait for the first item and between items when the result is an iterator or async iterator |

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
| `ignore_on` | `Sequence[Type]` | `()` | Exception types never counted as failures; takes precedence over `error_types` |

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
| `fallback_on` | `Sequence[Type]` | `(Exception,)` | Exceptions triggering fallback. Auto-cleared when there is no handler and no alternative |
| `alternatives` | `Sequence[Callable]` | `()` | Callables tried in order with the original arguments before the handler |
| `cooldown` | `float` | `0.0` | Seconds a failing target (the function or an alternative) is skipped. `0` disables |
| `cooldown_threshold` | `int` | `1` | Consecutive failures that start a cooldown |

`FallbackConfig()` is safe to call with no arguments. The handler can be an async function when decorating async functions. See [Fallback](core/fallback.md).

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
| `cost` | `Optional[Callable[..., float]]` | `None` | Units of the primary limit a call consumes, from its arguments (default 1) |
| `actual_cost` | `Optional[Callable[[Any], Optional[float]]]` | `None` | Units really consumed, from the result; the difference to `cost` is settled |
| `limits` | `Sequence[RateLimit]` | `()` | Additional limits enforced together with the primary limit (named `"calls"`) |
| `feedback` | `Optional[Callable[[Any], Optional[RateLimitFeedback]]]` | `None` | Reads the server's own limits from each attempt's result or exception |
| `charge_retries` | `bool` | `False` | Debit every retry attempt against the limits |

### `RateLimit`

One additional limit of a `RateLimiterConfig`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_units` | `float` | required | Units allowed per period |
| `period` | `float` | required | Time period in seconds |
| `name` | `str` | `"limit<N>"` | Name used in events, errors and feedback |
| `cost` | `Optional[Callable[..., float]]` | `None` | Units a call consumes, from its arguments (default 1) |
| `actual_cost` | `Optional[Callable[[Any], Optional[float]]]` | `None` | Units really consumed, from the result |

### `RateLimitFeedback`

Returned by a `feedback` function. Frozen dataclass.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `retry_after` | `Optional[float]` | `None` | Seconds during which no call should be sent; pauses the limiter |
| `remaining` | `Optional[Mapping[str, float]]` | `None` | Limit name to units left on the server; lowers the local level, never raises it |

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

Sync and async functions under one name share the circuit breaker, rate limits, retry budget and fallback cooldown state. `register()` on an existing name drops its executors and state.

### `SharedStateConfig`

Shares circuit breaker, rate limit and retry budget state between processes. See [Shared State](advanced/shared-state.md).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `backend` | `StateBackend` | required | Where the shared state is stored |
| `key` | `str` | `""` | Name of the state in the backend. Defaults to the registry name or `module.qualname` of the function |
| `sync_interval` | `float` | `1.0` | Seconds between background passes (circuit breaker, retry budget). `0` disables the thread |
| `fail_open` | `bool` | `True` | Rate limiting while the backend is unreachable: local limit (`True`) or reject (`False`) |

| Method | Description |
|--------|-------------|
| `sync_now()` | Run one synchronisation pass immediately |

### `StateBackend`

Protocol for shared-state storage. `incr` must be atomic.

| Method | Description |
|--------|-------------|
| `get(key)` | Value under `key`, or `None` |
| `set(key, value, ttl=None)` | Store a string value, optionally expiring after `ttl` seconds |
| `incr(key, amount, ttl=None)` | Atomically add `amount` and return the new total |
| `delete(key)` | Remove `key` |

### `InMemoryBackend`

Thread-safe `StateBackend` in process memory. Also offers `keys()`.

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
| `refund()` | Give back one token that was acquired but not used |

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

### `llm_policy(**kwargs)`

Optimized for LLM / HTTP API calls: 60s timeout, 4 attempts with 429-aware `Retry-After`-honoring
backoff, client-side rate limiter (60 calls/60s), circuit breaker at 5 failures. Optional
`tokens_per_minute` (with `token_cost` / `token_usage`), `adaptive_rate_limit` and
`rate_limit_max_wait`. See [HTTP & LLM Helpers](advanced/http.md).

## contrib.http

Stdlib-only helpers in `pyresilience.contrib.http` (not re-exported from the package root):

### `retry_on_status(*codes)`

Returns a predicate for `RetryConfig.retry_on_result`. Duck-typed: matches integer `status_code`
(requests/httpx) or `status` (aiohttp) attributes against `codes`.

### `retry_after_delay(max_wait=60.0)`

Returns a `delay_func` for `RetryConfig.delay_func`. Parses the `Retry-After` header
(delta-seconds and HTTP-date forms) from the triggering response or from an exception carrying
a `.response` attribute; returns `None` (exponential backoff fallback) when absent or
unparseable; result is clamped to `[0, max_wait]`.

### `rate_limit_feedback(*, calls_limit="calls", tokens_limit="tokens", max_pause=60.0)`

Returns a `feedback` function for `RateLimiterConfig.feedback`. Parses `Retry-After`,
`x-ratelimit-*`, `anthropic-ratelimit-*` and `RateLimit-*` headers from a response or from an
exception carrying a `.response`, and returns a `RateLimitFeedback` (or `None`). Pauses are
capped at `max_pause` seconds.

## contrib.redis

### `RedisBackend(client, prefix="pyresilience:")`

`StateBackend` on top of a synchronous redis-py compatible client that you supply. pyresilience
does not import a Redis library.

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

`RETRY`, `RETRY_EXHAUSTED`, `TIMEOUT`, `CIRCUIT_OPEN`, `CIRCUIT_HALF_OPEN`, `CIRCUIT_CLOSED`, `FALLBACK_USED`, `COOLDOWN`, `BULKHEAD_REJECTED`, `RATE_LIMITED`, `CACHE_HIT`, `CACHE_MISS`, `SUCCESS`, `FAILURE`, `SLOW_CALL`

## Exceptions

### `BulkheadFullError`

Raised when the bulkhead has no available slots and `max_wait` is exceeded.

### `RateLimitExceededError`

Raised when the rate limiter rejects a call (no tokens available and `max_wait` exceeded).
