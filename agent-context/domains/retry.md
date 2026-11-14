# Domain: Retry and Retry Budget

## Bounded Context

Retry is configured by `RetryConfig` and optionally limited by `RetryBudgetConfig`. The loop lives in `_execute_with_retry` of both executors in `src/pyresilience/_executor.py`; backoff is computed by `_compute_delay` and `_resolve_delay`; the budget is `src/pyresilience/_retry_budget.py`. HTTP helpers live in `src/pyresilience/contrib/http.py` (`../integrations/http.md`).

In scope:
- Exception-driven and result-driven (`retry_on_result`) retries, backoff, jitter, `delay_func`, `ignore_on`, retry budget.

Out of scope (lives elsewhere):
- Timeouts and circuit breaking (`executor-pipeline.md`, `circuit-breaker.md`).

For product framing see `../business-context.md`.

## State Model

Per attempt (1-based, `max_attempts` includes the first call):

| Outcome | Behaviour |
|---|---|
| Success, predicate false | record circuit success, emit `SUCCESS`, return |
| Success, `retry_on_result(result)` true, attempts remain | acquire budget; if empty emit `RETRY_EXHAUSTED` ("retry budget exhausted") and return the latest result; else emit `RETRY` and sleep |
| Success, predicate true on final attempt | emit `RETRY_EXHAUSTED` and return the result (no exception) |
| Exception in `ignore_on` | circuit tracking (unless the breaker ignores it too), emit `FAILURE`, re-raise; no retry, no fallback |
| Exception in `retry_on`, attempts remain | acquire budget; if empty emit `RETRY_EXHAUSTED`, then fallback (if `fallback_on` matches) or re-raise; else emit `RETRY`, sleep, retry |
| Exception, attempts used up or not retryable | emit `RETRY_EXHAUSTED` (only when retry is configured and attempts are used up), then fallback or `FAILURE` and re-raise |

Delay: `delay * backoff_factor ** (attempt - 1)`, capped at `max_delay`; with `jitter` the value is `max(0.1 * base, random() * base)`. When `delay_func(attempt, trigger)` returns a number it replaces this value, clamped to `[0, max_delay]`; returning `None` falls back to backoff. During the sleep the bulkhead slot is released and re-acquired.

## Actors and Permissions

Not applicable.

<!-- human-owned -->

## Invariants

- `max_attempts` counts the initial call.
- `ignore_on` always wins over `retry_on`.
- Jitter never reduces a delay below 10% of the base delay (prevents zero-delay retry storms).
- The retry budget is consulted for both exception-driven and result-driven retries and they share one token pool (result-driven support added in 0.4.1; see `TestRetryBudgetOnResult` in `tests/test_retry_budget.py`).
- When the budget is exhausted on a result-driven retry, the latest result is returned rather than an exception.

<!-- /human-owned -->

## External Workflow Wiring

- `RetryBudget` is a lock-protected token bucket (`max_retries` capacity, `refill_rate` tokens per second, starts full). `acquire()` consumes one token; `available` and `reset()` are public.
- A `RetryBudget` is created per executor from `ResilienceConfig.retry_budget`, or once per `ResilienceRegistry` name, where the sync and async executors share it (see `test_shared_budget_across_functions`). With `SharedStateConfig` it is a `_SyncedRetryBudget` exchanged with the backend in the background. Only retries are charged, never the first call.

<!-- agent-updatable -->

## Key Services / Entry Points

| File | Responsibility |
|---|---|
| `src/pyresilience/_types.py` | `RetryConfig`, `RetryBudgetConfig` and validation |
| `src/pyresilience/_executor.py` | `_compute_delay`, `_resolve_delay`, `_execute_with_retry` (sync and async), `_on_total_timeout` (stops retrying when the overall deadline is spent: `TimeoutConfig.total_seconds` or `per_attempt=False`; see `executor-pipeline.md`) |
| `src/pyresilience/_retry_budget.py` | `RetryBudget` |
| `src/pyresilience/_shared.py` | `_SyncedRetryBudget` (cross-process budget; `shared-state.md`) |
| `src/pyresilience/contrib/http.py` | `retry_on_status`, `retry_after_delay` (`rate_limit_feedback` is covered in `rate-limiting.md`) |
| `src/pyresilience/_presets.py` | presets that configure retry (`http_policy`, `db_policy`, `queue_policy`, `llm_policy`, `strict_policy`) |
| `tests/test_retry.py`, `tests/test_retry_on_result.py`, `tests/test_retry_budget.py` | behaviour tests |

<!-- /agent-updatable -->

<!-- human-owned -->

## What NOT to Do

- Do NOT retry on `BaseException`.
- Do NOT edit only one of the sync and async retry loops; they are separate code.
- Do NOT bypass the budget check on a new retry path.
- Do NOT assert tight timing in retry tests; use `jitter=False` and small delays.

<!-- /human-owned -->
