# Error Handling

This library has no HTTP layer. Errors are Python exceptions raised to the caller of the wrapped function, or swallowed by a fallback.

<!-- human-owned -->

## Error Response Format

Rejections raise a typed exception from `src/pyresilience/_exceptions.py`. The exceptions are created with a fixed message and carry no extra attributes (for example `CircuitOpenError("Circuit breaker is open")`, `BulkheadFullError("Bulkhead full")`, `RateLimitExceededError("Rate limit exceeded")`).

## Global Exception Handler

There is none. The executors (`_SyncExecutor._execute_core`, `_AsyncExecutor._execute_core` in `src/pyresilience/_executor.py`) decide, per exception, whether to record a circuit failure, retry, call the fallback or re-raise. Listener exceptions are caught in `_emit` and logged through the `pyresilience` logger at WARNING; they never propagate.

<!-- /human-owned -->

<!-- agent-updatable -->

## Exception Mapping Table

Where each exception is raised by the library.

| Exception | Raised by | Condition | Fallback applies? |
|---|---|---|---|
| `CircuitOpenError` | executor | circuit open before the call, or open when re-checked before retry attempt > 1 | Yes, when a `FallbackConfig` is set (the pre-call checks call the fallback whenever `fallback_cfg is not None`, regardless of `fallback_on`; the retry-loop re-check honours `fallback_on`) |
| `RateLimitExceededError` | executor | `rate_limiter.acquire()` returned False | Same as above (pre-call check) |
| `BulkheadFullError` | executor | `bulkhead.acquire()` returned False, or slot could not be re-acquired after retry sleep | Pre-call: yes. Re-acquire after sleep: raised directly, no fallback |
| `ResilienceTimeoutError` | executor timeout path (`_execute_with_timeout`, total-deadline check); also injected into a timed-out worker thread via `_interrupt_thread` on CPython | per-attempt timeout, or total deadline exhausted | Goes through normal retry/circuit/fallback handling as an `Exception` |

## Custom Exception Classes

- `ResilienceError(Exception)` - base class for all pyresilience rejections (`_exceptions.py`).
- `CircuitOpenError(ResilienceError)`.
- `BulkheadFullError(ResilienceError)`.
- `RateLimitExceededError(ResilienceError)` - defined in `_exceptions.py`, re-exported from `_rate_limiter.py`.
- `ResilienceTimeoutError(ResilienceError, TimeoutError)` - also a builtin `TimeoutError` for backward compatibility.

## Config Validation (`ValueError` in `__post_init__`, `src/pyresilience/_types.py`)

| Config | Message raised |
|---|---|
| `RetryConfig` | `max_attempts must be >= 1`; `delay must be >= 0`; `max_delay must be >= 0` |
| `TimeoutConfig` | `seconds must be > 0`; `pool_size must be >= 1` |
| `CircuitBreakerConfig` | `failure_threshold must be >= 1`; `recovery_timeout must be >= 0`; `failure_rate_threshold must be between 0.0 and 1.0` |
| `FallbackConfig` | no raise: when `handler is None`, `fallback_on` is forced to `()` |
| `BulkheadConfig` | `max_concurrent must be >= 1` |
| `RateLimiterConfig` | `max_calls must be >= 1`; `period must be > 0` |
| `CacheConfig` | `max_size must be >= 1`; `ttl must be >= 0` |
| `RetryBudgetConfig` | `max_retries must be >= 1`; `refill_rate must be > 0` |

Other validation: `contrib/http.py` `retry_on_status()` raises `ValueError` with no codes and `TypeError` for non-int codes; `retry_after_delay()` raises `ValueError("max_wait must be > 0")`. Optional-dependency listeners raise `ImportError` at construction (`OpenTelemetryListener`, `PrometheusListener`); Flask `Resilience.executor` raises `RuntimeError` before `init_app()`; `ResilienceRegistry.get_or_default` / decorator creation raises `KeyError` for unknown names with no default.

<!-- /agent-updatable -->

<!-- human-owned -->

## Conventions for New Exceptions

1. Add the class to `src/pyresilience/_exceptions.py`, inheriting from `ResilienceError` (add `TimeoutError`-style builtin bases only for backward-compat reasons, as `ResilienceTimeoutError` does).
2. Give it a docstring stating the trigger condition.
3. Export it from `src/pyresilience/__init__.py` `__all__` if users should catch it.
4. Raise it from both `_SyncExecutor` and `_AsyncExecutor` and decide explicitly how fallback and events (`EventType`) interact.
5. Config validation uses `ValueError("<field> must be ...")` in `__post_init__`, with one test per `raise`.

## What NOT to Do

- Do NOT widen `retry_on` or `error_types` defaults to `BaseException`; `KeyboardInterrupt` and `SystemExit` must not be retried or swallowed.
- Do NOT let a listener exception break the wrapped call; keep `_emit`'s try/except.
- Do NOT make `FallbackConfig` silently return `None`: the `handler=None` guard that clears `fallback_on` must stay.
- Do NOT use bare `except:` in library code or tests.

<!-- /human-owned -->
