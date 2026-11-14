# Domain: Shared State

## Bounded Context

Two kinds of sharing exist. (1) Within a process: `_Parts` (`src/pyresilience/_parts.py`) holds the circuit breaker, rate limiter, retry budget and fallback router and is handed to both executors of a registry name. (2) Across processes: `SharedStateConfig` plus a `StateBackend` make those parts exchange state through a key/value store.

In scope:
- `_Parts` / `_build_parts`, `StateBackend`, `InMemoryBackend`, `_Syncer`, `_SharedWindows`, `_SyncedRetryBudget`, `_SyncedCircuitBreaker`.

Out of scope (lives elsewhere):
- The Redis client wrapper (`../integrations/redis.md`).
- Local breaker, limiter and budget logic (`circuit-breaker.md`, `rate-limiting.md`, `retry.md`).

For product framing see `../business-context.md`.

## State Model

- `_build_parts(config, state_key)`: with `config.shared_state`, the key is `SharedStateConfig.key` or `state_key`; no key raises `ValueError("shared_state needs a key: set SharedStateConfig.key")`. `@resilient` passes `f"{fn.__module__}.{fn.__qualname__}"`; the registry passes the name.
- Bulkheads and caches are not in `_Parts`; they stay per executor.
- `StateBackend` (runtime-checkable Protocol): `get`, `set(ttl)`, `incr(amount, ttl)` (must be atomic), `delete`. `InMemoryBackend` is thread-safe and in-process only (extra `keys()`).
- Rate limits: every acquisition is counted. `_SharedWindows.acquire` increments a fixed-window counter `"<key>:rl:<limit>:<window>"` per limit (TTL two periods) on top of the local limiter, takes the units back when a limit would be exceeded, and returns the window keys it used. `adjust(deltas, windows)` gives unused units back only to the window they were taken from and only while it is current; extra usage and `charge()` (retries) go to the current window. `fail_open=True` serves on the local limit while the backend is down (the backend is not called again until the outage pause ends); `False` rejects with `RateLimitExceededError` (blocker `state backend unavailable`).
- Retry budget (`_SyncedRetryBudget`) and circuit breaker (`_SyncedCircuitBreaker`): decided locally, exchanged by `_Syncer.sync_now()` every `sync_interval` seconds from a daemon thread named `pyresilience-state-sync`; the call path does no backend I/O for them. `sync_interval=0` starts no thread (call `SharedStateConfig.sync_now()`). Components are held weakly; the thread ends when none is left. The thread is restarted in a forked child.
- Breaker sharing: the open state is shared; in consecutive mode the failure streak adds up across instances; sliding-window mode shares only the open state. Shared timestamps use the wall clock.
- Backend failures during sync are logged (first at WARNING, repeats at DEBUG) and local state is kept.
- Outage pause (`_SharedWindows`): after a failed backend call the backend is not called for `pause` seconds (`max(1.0, SharedStateConfig.sync_interval)`, passed from `_parts.py`; floor `_MIN_OUTAGE_PAUSE`). In that time `acquire` answers at once per `fail_open`, `charge` returns None and `adjust` does nothing. When the pause ends, one call probes the backend.
- Fork safety: `_shared.py` keeps a `_syncers` WeakSet and registers `_after_fork_in_child()` with `os.register_at_fork` when it exists (not on Windows). In the child each live `_Syncer` gets a new lock, drops the dead thread, calls `_after_fork()` on every live part and restarts the sync thread when there are parts and `sync_interval > 0`. `_SyncedRetryBudget` and `_SyncedCircuitBreaker` take new locks and set their seen counters to the current totals, so the child does not republish what the parent counted.
## Actors and Permissions

Not applicable.

<!-- human-owned -->

## Invariants

- No backend I/O on the call path except the shared rate-limit increment.
- A backend outage must never break a call by itself (rate limiting follows `fail_open`).
- Core never imports a Redis library; clients are passed in.

<!-- /human-owned -->

## External Workflow Wiring

- Registry: `register()` and `unregister()` drop cached executors and `_Parts` for the name (`_drop`); `clear()` empties all. Already-decorated functions keep the executor they captured.

<!-- agent-updatable -->

## Key Services / Entry Points

| File | Responsibility |
|---|---|
| `src/pyresilience/_backend.py` | `StateBackend`, `InMemoryBackend` |
| `src/pyresilience/_shared.py` | `_Syncer`, `_syncer_for`, `_SharedWindows`, `_SyncedRetryBudget` |
| `src/pyresilience/_shared_breaker.py` | `_SyncedCircuitBreaker` |
| `src/pyresilience/_parts.py` | `_Parts`, `_build_parts` |
| `src/pyresilience/_types.py` | `SharedStateConfig` (`backend`, `key`, `sync_interval`, `fail_open`, `sync_now()`), `ResilienceConfig.shared_state` |
| `src/pyresilience/_registry.py` | per-name `_parts` map |
| `src/pyresilience/contrib/redis.py` | `RedisBackend` |
| `tests/test_backend.py`, `test_registry_shared.py`, `test_shared_breaker.py`, `test_shared_limits.py`, `test_shared_sync.py`, `test_shared_outage.py`, `test_shared_fork.py` (real `os.fork`, skipped on Windows) | behaviour tests |

<!-- /agent-updatable -->

<!-- human-owned -->

## What NOT to Do

- Do NOT add backend calls to the circuit breaker or retry budget call path.
- Do NOT assume a registry name shares bulkhead or cache between sync and async functions.

<!-- /human-owned -->
