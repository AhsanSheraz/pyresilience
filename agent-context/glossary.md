# Glossary

<!-- agent-updatable -->

## Domain Terms

| Term | Definition |
|---|---|
| Resilience pattern | One of retry, timeout, circuit breaker, fallback, bulkhead, rate limiter, cache. |
| `@resilient` | Public decorator in `src/pyresilience/_decorator.py`. Builds a `ResilienceConfig`, picks `_AsyncExecutor` for coroutine functions and `_SyncExecutor` otherwise, and exposes it as `wrapper._executor`. |
| Executor | `_SyncExecutor` / `_AsyncExecutor` in `src/pyresilience/_executor.py`; hold pre-resolved config plus bulkhead and cache for one decorated function (or one registry name). Circuit breaker, limiter, retry budget and fallback router come from a `_Parts` object that a registry shares between the sync and async executor of a name. |
| Fast path | Executor mode used when there is no retry, no timeout and no slow-call tracking: calls `_execute_direct` instead of the retry loop. |
| Listener | `ResilienceListener = Callable[[ResilienceEvent], None]`. Exceptions raised by a listener are caught and logged; they never break the wrapped call. |
| `ResilienceEvent` | Frozen dataclass: `event_type`, `function_name`, `attempt`, `error`, `detail`, `context`, `duration`. |
| Registry | `ResilienceRegistry`: name to `ResilienceConfig`, with one cached executor per (name, sync/async). Both executors of a name share one `_Parts` (breaker, limits, retry budget, cooldown); bulkhead and cache stay per executor. |
| Preset / policy | `http_policy`, `db_policy`, `queue_policy`, `llm_policy`, `strict_policy`: return a dict for `@resilient(**policy)`. |
| Sliding window | Circuit breaker mode enabled when `CircuitBreakerConfig.sliding_window_size > 0`; opens on failure rate or slow-call rate over the last N calls. |
| Slow call | A call whose duration is at least `CircuitBreakerConfig.slow_call_duration` (only when > 0). |
| Per-attempt timeout | `TimeoutConfig.per_attempt=True` (default): each attempt gets the full timeout. `False`: one deadline across all attempts. |
| Overall deadline | One time budget for the whole call, retry waits included: `TimeoutConfig.seconds` with `per_attempt=False`, or `total_seconds` next to a per-attempt `seconds`. When spent, the executor raises `ResilienceTimeoutError` (`_on_total_timeout`). |
| Stream idle timeout | `TimeoutConfig.stream_idle_seconds`: an iterator or async iterator result must yield each item (the first included) within this time, else `ResilienceTimeoutError`. |
| Weighted limit | A rate limit whose calls cost more than one unit (`cost`), or one of several limits (`RateLimit`) a call must satisfy together; all-or-nothing. |
| Reconcile | After a call, replace the reserved cost estimate by the real cost (`actual_cost`) and give back or charge the difference. |
| Server feedback | `RateLimiterConfig.feedback` result (`RateLimitFeedback`): `Retry-After` pauses the limiter, reported remaining units lower its levels. |
| Alternative | A callable in `FallbackConfig.alternatives` tried with the original arguments when the call fails (for example another provider). |
| Cooldown | Time a failing target (primary or alternative) is skipped after `cooldown_threshold` consecutive failures; emits `EventType.COOLDOWN` on entry. |
| State backend | `StateBackend` protocol (`get`, `set`, `incr`, `delete`) behind `SharedStateConfig`; `InMemoryBackend` or `contrib.redis.RedisBackend`. |
| Sync pass | One background exchange of breaker and retry-budget state with the backend (`_Syncer.sync_now`), every `sync_interval` seconds. |
| Parts | `_Parts` (`_parts.py`): the shareable stateful components built from one config. |
| Retry budget | `RetryBudget`: token bucket that caps retries; one per executor, or one per registry name shared by sync and async executors. |
| `ignore_on` | On `RetryConfig`: never retried (re-raised immediately). On `CircuitBreakerConfig`: never counted as a failure. Takes precedence over `retry_on` / `error_types`. |
| `delay_func` | Optional `(attempt, trigger) -> Optional[float]` on `RetryConfig` to override backoff (e.g. `Retry-After`). |
| `retry_on_result` | Predicate on `RetryConfig`; when true for a returned value, the call is retried without an exception. |
| Stampede prevention | Per-key lock in the cache path so only one caller computes a missing key. |
| In-flight tracking | Lazy counter of running calls, enabled by `enable_in_flight_tracking()` or `shutdown()`. |
| `resilience_context` | `ContextVar[Optional[dict]]`; its value is copied into `ResilienceEvent.context`. |
| Contrib | Optional adapters under `src/pyresilience/contrib/`. |

## Abbreviations

| Abbreviation | Meaning |
|---|---|
| CB | Circuit breaker |
| LRU | Least recently used (cache eviction) |
| TTL | Time to live |
| OTel | OpenTelemetry |
| RTD | Read the Docs |
| PEP 561 | Typed-package marker standard (`py.typed`) |

## Status Enums Reference

### `CircuitState` (`src/pyresilience/_types.py`)
`CLOSED = "closed"`, `OPEN = "open"`, `HALF_OPEN = "half_open"`.

### `EventType` (`src/pyresilience/_types.py`)
`RETRY`, `RETRY_EXHAUSTED`, `TIMEOUT`, `CIRCUIT_OPEN`, `CIRCUIT_HALF_OPEN`, `CIRCUIT_CLOSED`, `FALLBACK_USED`, `COOLDOWN`, `BULKHEAD_REJECTED`, `RATE_LIMITED`, `CACHE_HIT`, `CACHE_MISS`, `SLOW_CALL`, `SUCCESS`, `FAILURE` (values are the lowercase snake_case names). `CIRCUIT_HALF_OPEN` is defined but no code under `src/` emits it (verified by grep).

<!-- /agent-updatable -->
