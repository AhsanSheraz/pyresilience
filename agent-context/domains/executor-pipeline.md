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
- **Registry**: `_get_executor` caches executors under the keys `"<name>:sync"` and `"<name>:async"`. A sync and an async function registered under the same name therefore get two separate executors and do NOT share a circuit breaker, bulkhead, rate limiter, cache or retry budget. Functions of the same kind share one. `register()` replaces the config and drops cached executors only for the old keys of that name; already-decorated functions keep the executor they captured.
- **Retry budget scope**: one `RetryBudget` is created per executor (not process-wide). It is shared across functions only through a registry name.
- **In-flight tracking and shutdown**: tracking is off until `enable_in_flight_tracking()` or `shutdown()`. `shutdown(wait, timeout)` sets `_shutting_down`, enables tracking, waits for drain, then shuts down custom pools. `_shutting_down` is written but never read, so calls started after `shutdown()` are not rejected.
- **Introspection**: decorated wrappers expose `_executor`; `health_check` reads `_circuit_breaker` from it.

<!-- agent-updatable -->

## Key Services / Entry Points

| File | Responsibility |
|---|---|
| `src/pyresilience/_decorator.py` | `resilient`: builds `ResilienceConfig`, chooses executor, wraps with `functools.wraps` |
| `src/pyresilience/_executor.py` | `_SyncExecutor`, `_AsyncExecutor`, `_emit`, `_compute_delay`, `_apply_fallback(_async)`, `shutdown`, `enable_in_flight_tracking`, `get_in_flight_count`, `_interrupt_thread` |
| `src/pyresilience/_registry.py` | `ResilienceRegistry`: `register`, `set_default`, `get`, `get_or_default`, `decorator`, `get_executor`, `names`, `unregister`, `clear` |
| `src/pyresilience/_health.py` | `health_check` |
| `src/pyresilience/_bulkhead.py` | `Bulkhead` (lock+counter, or semaphore when `max_wait > 0`), `AsyncBulkhead` (semaphore re-created per event loop) |
| `src/pyresilience/_rate_limiter.py` | `RateLimiter`, `AsyncRateLimiter` (integer-nanosecond token bucket; polls with 10 ms sleeps when `max_wait > 0`) |
| `src/pyresilience/_cache.py` | `ResultCache`, `AsyncResultCache` (LRU via `OrderedDict`, TTL, hits/misses stats, per-key locks) |
| `src/pyresilience/_logging.py` | `_emit` support: `resilience_context`, `call_id_var`, listeners |

<!-- /agent-updatable -->

<!-- human-owned -->

## What NOT to Do

- Do NOT change cache semantics without noting that a fallback value produced inside the call stage (`_execute_direct` / `_execute_with_retry`) is returned to `_execute_core` and stored by `cache.put` like a normal result; fallbacks from the pre-call rejection checks (steps 2 to 4) are returned before the cache write.
- Do NOT assume a sync and an async function share state just because they use the same registry name.
- Do NOT call `_emit` without the `has_listeners` guard in hot paths.
- Do NOT edit `_executor.py` without running the sync and async test classes for the touched behaviour and, for non-trivial changes, `benchmarks/bench_overhead.py`.

<!-- /human-owned -->
