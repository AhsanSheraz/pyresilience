# Domain: Rate Limiting

## Bounded Context

`RateLimiterConfig` selects one of two limiter families. The plain family (`RateLimiter`, `AsyncRateLimiter` in `src/pyresilience/_rate_limiter.py`) is a single integer-nanosecond token bucket costing one token per call. The weighted family (`src/pyresilience/_limiter_core.py`, `src/pyresilience/_weighted_limiter.py`) handles several limits, per-call costs, cost reconciliation, server feedback and retry charging. The choice is made once, in `_build_parts` (`src/pyresilience/_parts.py`), by `_needs_weighted_limiter(config)` or because `shared_state` is set.

In scope:
- Limit selection, all-or-nothing acquisition across limits, reconcile after the call, server feedback pauses and level lowering, retry charging.

Out of scope (lives elsewhere):
- Cross-process counting (`shared-state.md`).
- Where the limiter sits in the pipeline and what a rejection does (`executor-pipeline.md`).
- Header parsing (`../integrations/http.md`).

For product framing see `../business-context.md`.

## State Model

- Selection: `_needs_weighted_limiter` is true when any of `cost`, `actual_cost`, `limits`, `feedback`, `charge_retries` is set. With `shared_state` the weighted limiter is always used.
- Limits: the primary limit is `max_calls` per `period`, named `"calls"` (`PRIMARY_LIMIT_NAME` in `_types.py`). Each `RateLimit` in `limits` adds a bucket; an empty name becomes `limit<N>` (1-based position in `limits`). Names must be unique.
- Acquire (`_LimiterCore.try_reserve`): a call takes its cost from every bucket or from none. Rejection returns the name of the blocking limit and the wait; `max_wait > 0` makes `reserve` loop with sleeps (`time.sleep` sync, `asyncio.sleep` async) until the deadline.
- Cost: `cost(*args, **kwargs)` per limit, default 1 unit per call.
- Reconcile: after a successful attempt, `actual_cost(result)` replaces the estimate; the difference is given back or charged (`_LimiterCore.observe`). `None` keeps the estimate.
- Server feedback: `RateLimiterConfig.feedback(outcome)` returns `RateLimitFeedback(retry_after, remaining)`. `retry_after` pauses every acquisition; `remaining[name]` lowers a bucket level, never raises it. Both results and raised exceptions are observed.
- Retry charging: with `charge_retries=True`, each attempt after the first is debited without waiting (`bind` in `_WeightedRateLimiter`); otherwise capacity is taken once per call and retries cost nothing.
- Rejection: the executor calls `_on_rate_limited(func_name, listeners, blocker)`: `RATE_LIMITED` event with detail `limit '<name>' exceeded`, then fallback if configured, else `RateLimitExceededError("Rate limit exceeded (<name>)")`.
- Registry: sync and async executors of one registry name share one limiter (`_Parts.plain_limiter` or `_Parts.limiter_core`). The async plain limiter draws from the sync `RateLimiter` bucket via `AsyncRateLimiter(config, shared)`.

## Actors and Permissions

Not applicable.

<!-- human-owned -->

## Invariants

- Nothing is consumed when any limit rejects a call (all-or-nothing).
- Server feedback may lower a level or pause the limiter; it never raises a level above what local accounting says.
- Sync and async weighted limiters are twins around one `_LimiterCore`; behaviour changes go into the core, or into both loops.
- `RateLimitExceededError` is raised by the executor, not by the limiter classes.

<!-- /human-owned -->

## External Workflow Wiring

- `llm_policy` (`_presets.py`) builds a `RateLimiterConfig` with a `"tokens"` `RateLimit` (60 s period) when `tokens_per_minute` is set, `feedback=rate_limit_feedback(...)` when `adaptive_rate_limit=True`, and `charge_retries=True` when token limits are in play.
- `contrib.http.rate_limit_feedback` supplies the header reader (`../integrations/http.md`).

<!-- agent-updatable -->

## Key Services / Entry Points

| File | Responsibility |
|---|---|
| `src/pyresilience/_types.py` | `RateLimit`, `RateLimitFeedback`, `RateLimiterConfig` and validation |
| `src/pyresilience/_rate_limiter.py` | `RateLimiter` (adds `try_acquire`), `AsyncRateLimiter` (optional `shared` sync limiter) |
| `src/pyresilience/_limiter_core.py` | `_Bucket`, `_LimiterCore`: `costs`, `try_reserve`, `give_back`, `charge`, `observe`, `levels`, `paused_for`, `reset` |
| `src/pyresilience/_weighted_limiter.py` | `_WeightedRateLimiter`, `_AsyncWeightedRateLimiter`: `reserve`, `bind`, `levels`, `reset`; `_needs_weighted_limiter` |
| `src/pyresilience/_parts.py` | picks and builds the limiter per config |
| `tests/test_rate_limiter.py`, `test_rate_limiter_weighted.py`, `test_rate_limiter_feedback.py`, `test_rate_limiter_weighted_decorator.py`, `test_contrib_http_feedback.py` | behaviour tests |

<!-- /agent-updatable -->

<!-- human-owned -->

## What NOT to Do

- Do NOT add a weighted-only feature to only one of the sync and async limiters.
- Do NOT consume capacity before every limit has been checked.
- Do NOT let feedback raise a local level.

<!-- /human-owned -->
