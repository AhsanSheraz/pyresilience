# Domain: Circuit Breaker

## Bounded Context

`CircuitBreaker` in `src/pyresilience/_circuit_breaker.py` is a thread-safe state machine configured by `CircuitBreakerConfig`. Both executors use the same class (there is no async variant); state is guarded by one `threading.Lock` and recovery timing uses `time.monotonic`. It is a public symbol and can be used standalone.

In scope:
- State transitions, consecutive-count and sliding-window modes, slow-call detection, manual control.

Out of scope (lives elsewhere):
- Where it is checked in the pipeline and how rejection interacts with fallback (`executor-pipeline.md`).

For product framing see `../business-context.md`.

## State Model

```
CLOSED --(failures reach threshold / failure rate / slow-call rate)--> OPEN
OPEN   --(recovery_timeout elapsed, evaluated lazily on access)-----> HALF_OPEN
HALF_OPEN --(success_threshold successes)--------------------------> CLOSED
HALF_OPEN --(any failure)-----------------------------------------> OPEN
```

- **Consecutive mode** (`sliding_window_size == 0`): opens after `failure_threshold` consecutive failures; a success resets the counter.
- **Sliding window** (`sliding_window_size > 0`): deque of `(is_failure, is_slow)` for the last N calls. Evaluated once at least `minimum_calls` entries exist (defaults to the window size when 0); opens when failure rate `>= failure_rate_threshold`, or slow rate `>= slow_call_rate_threshold` when `slow_call_duration > 0`. The window is cleared when the circuit closes.
- OPEN to HALF_OPEN is computed inside `state`, `allow_request` and `record_success_atomic` (no timer thread). `allow_request` rejects only when OPEN, so HALF_OPEN admits every request.

Public members: `state`, `failure_count`, `allow_request()`, `record_success()`, `record_success_atomic(duration)` (returns previous and new state; used by the executors), `record_failure(duration)`, `reset()`, `force_open()`, `force_close()`, `metrics`.

## Actors and Permissions

Not applicable.

<!-- human-owned -->

## Invariants

- All state changes happen under `self._lock`; use `record_success_atomic` rather than `.state` followed by `record_success` when you need the transition.
- Only exceptions matching `error_types` and not matching `ignore_on` may be recorded as failures; the executors enforce this before calling `record_failure`.
- `EventType.CIRCUIT_HALF_OPEN` exists but nothing under `src/` emits it. `CIRCUIT_OPEN` is emitted on rejection and when a failure opens the circuit; `CIRCUIT_CLOSED` when a success closes it.

<!-- /human-owned -->

## External Workflow Wiring

Registry-shared breakers: `health_check(registry)` reads `executor._circuit_breaker.state.value` and `.failure_count`.

<!-- agent-updatable -->

## Key Services / Entry Points

| File | Responsibility |
|---|---|
| `src/pyresilience/_circuit_breaker.py` | `CircuitBreaker` |
| `src/pyresilience/_types.py` | `CircuitBreakerConfig`, `CircuitState` |
| `src/pyresilience/_executor.py` | calls `allow_request`, `record_success_atomic`, `record_failure`; emits circuit events |
| `src/pyresilience/_health.py` | `health_check` |
| `tests/test_circuit_breaker.py`, `tests/test_sliding_window.py` | behaviour tests |

<!-- /agent-updatable -->

<!-- human-owned -->

## What NOT to Do

- Do NOT read or mutate breaker state outside the lock.
- Do NOT change the consecutive-count default; sliding window is opt-in via `sliding_window_size`.
- Do NOT count `ignore_on` exceptions as failures.

<!-- /human-owned -->
