# Domain: Executor Pipeline

## Bounded Context

The executors in `src/pyresilience/_executor.py` turn a `ResilienceConfig` into behaviour around one function call. `_SyncExecutor` and `_AsyncExecutor` mirror each other; `ResilienceRegistry` (`src/pyresilience/_registry.py`) lets several functions share one executor and therefore the same stateful patterns. This is the most change-sensitive code in the repo.

In scope:
- Pattern ordering, retry loop, timeout handling, fallback, event emission.
- Shared state via the registry; in-flight tracking and `shutdown()`.

Out of scope (lives elsewhere):
- Pattern internals: `_circuit_breaker.py`, `_bulkhead.py`, `_rate_limiter.py`, `_cache.py`, `_retry_budget.py` (retry and circuit details: `retry.md`, `circuit-breaker.md`).
- Event listeners: `_logging.py`, `contrib/`.

For product framing see `../business-context.md`.

## State Model

Order of operations in `_execute_core` (verified in code, both executors):

```
1. cache lookup        hit -> return (CACHE_HIT); miss -> CACHE_MISS, take per-key lock, re-check
                       (routed mode, primary cooling down: looked up in _execute_routed before the router runs)
2. circuit breaker     allow_request() false -> CIRCUIT_OPEN, fallback if configured else CircuitOpenError
3. rate limiter        acquire() false -> RATE_LIMITED, fallback if configured else RateLimitExceededError
4. bulkhead            acquire() false -> BULKHEAD_REJECTED, fallback if configured else BulkheadFullError
5. call
     fast path (no retry, no timeout, slow_call_duration == 0): _execute_direct
     otherwise: _execute_with_retry
        for attempt in 1..max_attempts:
          attempt > 1: re-check circuit breaker
          timeout (per attempt, or remaining total deadline) around fn
          retry_on_result predicate, circuit success/failure recording
          ignore_on -> re-raise; retryable -> retry budget -> delay -> retry
          exhausted -> RETRY_EXHAUSTED -> fallback (if fallback_on matches) or re-raise
6. cache.put(result); release bulkhead slot and cache key lock in finally
```

The circuit breaker check comes BEFORE the rate limiter and bulkhead (the order is cache, circuit breaker, rate limiter, bulkhead, retry(timeout(fn)), fallback).

## Actors and Permissions

Not applicable.

<!-- human-owned -->

## Invariants

- Pipeline order above is a semantic contract; reordering is a breaking change.
- Sync and async executors must stay behaviourally identical (events, fallback rules, ordering).
- The bulkhead slot is released during retry sleep and re-acquired before the next attempt; `bulkhead_held` tracks ownership so the `finally` releases at most once.
- Exceptions in `ignore_on` bypass retry AND fallback (they emit `FAILURE` and re-raise); they are also never recorded on the circuit breaker if listed in the breaker's `ignore_on`.
- Listener exceptions never propagate (`_emit` catches `Exception`).
- Hot path rules: pre-cached attributes in `__init__`, `has_listeners` guard before every `_emit`, no per-call allocations that can be avoided.
- `retry_on` / `error_types` / `fallback_on` default to `(Exception,)` and must never include `BaseException`.

<!-- /human-owned -->

## External Workflow Wiring

- **Timeouts (sync)**: the call runs on a thread pool (`_default_timeout_pool`, shared, sized `min(32, cpu_count + 4)`; a dedicated pool is created when `TimeoutConfig.pool_size` differs from that default). On timeout the future is cancelled and, on CPython, `_interrupt_thread` schedules `ResilienceTimeoutError` in the worker. It cannot interrupt blocking C calls, so the worker may keep running.
- **Timeouts (async)**: `asyncio.wait_for`; `asyncio.TimeoutError` becomes `ResilienceTimeoutError`.
- **Registry**: `_get_executor` caches executors under the keys `"<name>:sync"` and `"<name>:async"`. It builds one `_Parts` per name and passes it to both, so a sync and an async function registered under the same name share the circuit breaker, rate limits, retry budget and fallback cooldown. Bulkhead and cache are per executor, so only functions of the same kind share those. `register()` and `unregister()` drop both cached executors and the `_Parts` of that name; already-decorated functions keep the executor they captured.
- **Retry budget scope**: one `RetryBudget` per executor, or per registry name (shared by the sync and async executors). It is not process-wide. With `SharedStateConfig` it is a `_SyncedRetryBudget` exchanged with the backend in the background.
- **In-flight tracking and shutdown**: tracking is off until `enable_in_flight_tracking()` or `shutdown()`. `shutdown(wait, timeout)` sets `_shutting_down`, enables tracking, waits for drain, then shuts down custom pools. `_shutting_down` is written but never read, so calls started after `shutdown()` are not rejected.
- **Introspection**: decorated wrappers expose `_executor`; `health_check` reads `_circuit_breaker` from it.

<!-- agent-updatable -->

## Key Services / Entry Points

| File | Responsibility |
|---|---|
| `src/pyresilience/_decorator.py` | `resilient`: builds `ResilienceConfig`, chooses executor, wraps with `functools.wraps` |
| `src/pyresilience/_executor.py` | `_SyncExecutor`, `_AsyncExecutor`, `_compute_delay`, `shutdown`, `enable_in_flight_tracking`, `get_in_flight_count`, `_interrupt_thread` |
| `src/pyresilience/_events.py` | `_emit` |
| `src/pyresilience/_fallback.py` | `_apply_fallback(_async)`, `_FallbackRouter` (`fallback.md`) |
| `src/pyresilience/_parts.py` | `_Parts`, `_build_parts`: breaker, limiter, retry budget, router built once per executor or per registry name (`shared-state.md`) |
| `src/pyresilience/_stream.py` | idle-timeout iterator wrappers; each sync stream is read by its own daemon thread (not the timeout pool) that runs in `contextvars.copy_context()` taken at the first `next()`, so the stream body sees the caller's context variables; `with` / `async with` are forwarded |
| `src/pyresilience/_registry.py` | `ResilienceRegistry`: `register`, `set_default`, `get`, `get_or_default`, `decorator`, `get_executor`, `names`, `unregister`, `clear` |
| `src/pyresilience/_health.py` | `health_check` |
| `src/pyresilience/_bulkhead.py` | `Bulkhead` (lock+counter, or semaphore when `max_wait > 0`), `AsyncBulkhead` (semaphore re-created per event loop) |
| `src/pyresilience/_rate_limiter.py` | `RateLimiter`, `AsyncRateLimiter` (integer-nanosecond token bucket; polls with 10 ms sleeps when `max_wait > 0`); weighted variant in `rate-limiting.md` |
| `src/pyresilience/_cache.py` | `ResultCache`, `AsyncResultCache` (LRU via `OrderedDict`, TTL, hits/misses stats, per-key locks) |
| `src/pyresilience/_logging.py` | `resilience_context`, `call_id_var`, listeners |

### Executor internals added in 0.5.0 (both executors, same names)

Verified in `src/pyresilience/_executor.py`.

| Member | Role |
|---|---|
| `__init__(config, shared=None, state_key="")` | `shared` is a `_Parts` from the registry; without it the executor calls `_build_parts(config, state_key)`. Circuit breaker, limiter, retry budget and router come from the parts; bulkhead and cache are built per executor |
| `_entry` | Chosen once in `__init__`: `_execute_routed` when a fallback router exists, else `_execute_stream` when `TimeoutConfig.stream_idle_seconds` is set, else `_execute_core`. `execute()` calls `self._entry` |
| `_execute_core` | The pipeline of the State Model section (cache, breaker, limiter, bulkhead, retry loop) |
| `_execute_stream` | Runs the core, then wraps an iterator or async iterator result with the idle limit |
| `_execute_routed` | Runs `_FallbackRouter.run_sync` / `run_async` around `_execute_core`; wraps streams afterwards; the executor's own `_fallback_cfg` and `_fallback_on` are cleared when a router exists. When a cache is configured and `router.primary_cooling()` is true, the cache is looked up first (CACHE_HIT returns the cached value; a miss goes on to the router and is reported as CACHE_MISS through `on_primary_skipped` right before a fallback answers, or by the core when the primary is called after all, so one call reports one miss), so the cache stays first while the primary is skipped |
| `_timeout_total` | Overall deadline in seconds: `TimeoutConfig.seconds` when `per_attempt=False`, else `total_seconds`, else 0 (none) |
| `_on_total_timeout(func_name, listeners, cause)` | Called by the retry loops when the deadline is spent: emits `TIMEOUT` ("exceeded total ... budget") unless the last attempt itself timed out and already reported it, then fallback if `fallback_on` matches the timeout error or its cause (`_fallback_match`; the handler receives the matched error, the `FALLBACK_USED` event still carries the timeout error), else `FAILURE` and raises `ResilienceTimeoutError` with `__cause__` set to the last error |
| `_on_rate_limited(func_name, listeners, blocker)` | Rejection path of the weighted limiter (`rate-limiting.md`) |
| deadline in `_execute_with_retry` | `deadline = monotonic() + _timeout_total`; each attempt gets `min(seconds, time left)`; a retry wait that cannot fit in the time left ends in `_on_total_timeout` |

<!-- /agent-updatable -->

<!-- human-owned -->

## What NOT to Do

- Do NOT change cache semantics without noting that a fallback value produced inside the call stage (`_execute_direct` / `_execute_with_retry`) is returned to `_execute_core` and stored by `cache.put` like a normal result; fallbacks from the pre-call rejection checks (steps 2 to 4) are returned before the cache write.
- Do NOT assume a sync and an async function share bulkhead slots or cached results under one registry name; breaker, limits, retry budget and cooldown are shared.
- Do NOT call `_emit` without the `has_listeners` guard in hot paths.
- Do NOT edit `_executor.py` without running the sync and async test classes for the touched behaviour and, for non-trivial changes, `benchmarks/bench_overhead.py`.

<!-- /human-owned -->
