# Domain: Fallback, Alternatives and Cooldown

## Bounded Context

`FallbackConfig` has two modes. With only a `handler`, the executors call `_apply_fallback` / `_apply_fallback_async` (`src/pyresilience/_fallback.py`) from inside the pipeline. With `alternatives`, or with `cooldown > 0` plus a handler, `_needs_router` is true and `_build_parts` builds a `_FallbackRouter` that wraps the whole core call.

In scope:
- Handler application, alternatives, cooldown state, `COOLDOWN` and `FALLBACK_USED` events from the router.

Out of scope (lives elsewhere):
- Pre-call rejections and the retry loop (`executor-pipeline.md`, `retry.md`).

For product framing see `../business-context.md`.

## State Model

Router mode (`_FallbackRouter.run_sync` / `run_async`):

```
1. primary      skipped when cooling down AND a handler or a ready alternative exists;
                else _execute_core runs (full pipeline); success resets its failures
2. alternatives in order, each skipped while cooling down; called with the original args;
                async alternatives are awaited; first success wins
                (FALLBACK_USED, detail "alternative <name>")
3. handler      FALLBACK_USED, then _apply_fallback*; used last
4. else         the last error is raised
```

- Matched error: `_fallback_match(exc, types)` (`_fallback.py`) returns `exc`, or the `__cause__` of a `ResilienceTimeoutError` (the error a spent deadline stopped retrying) when that matches. `_FallbackRouter._eligible` uses it and `_handler_error()` hands the matched error to the handler. `_FallbackRouter.primary_cooling()` tells the executor the primary is being skipped, so it can serve a cached result first.
- Eligible errors: `fallback_on` types plus the executor rejections (`CircuitOpenError`, `RateLimitExceededError`, `BulkheadFullError`); never types in `RetryConfig.ignore_on`. Other exceptions propagate without touching cooldown.
- Cooldown: a target (primary or alternative) enters cooldown after `cooldown_threshold` consecutive failures and is skipped for `cooldown` seconds; `COOLDOWN` is emitted when it enters. A cooldown never fails a call alone: when nothing else is ready the primary is called anyway. When a cooldown has expired, the next failure starts the streak again from zero. In `run_sync` an alternative that returns an awaitable raises `TypeError`.
- The router is built into `_Parts`, so a registry name shares cooldown state between its sync and async executors. When a router exists the executor clears its own `_fallback_cfg` and `_fallback_on`, so failures reach the router instead of the inline handler.
- `FallbackConfig.__post_init__`: `fallback_on` is forced to `()` only when there is neither a handler nor alternatives.
- `_FallbackRouter.state()` returns per target `{"failures", "cooling_for"}`.

## Actors and Permissions

Not applicable.

<!-- human-owned -->

## Invariants

- Without a handler and without alternatives, a failure must never turn into a silent `None`.
- Router sync and async paths mirror each other; change both.
- Cooldown state changes happen under the router lock.

<!-- /human-owned -->

## External Workflow Wiring

None beyond the executors (`_execute_routed` in each executor, selected in `_entry`).

<!-- agent-updatable -->

## Key Services / Entry Points

| File | Responsibility |
|---|---|
| `src/pyresilience/_fallback.py` | `_apply_fallback`, `_apply_fallback_async`, `_needs_router`, `_Target`, `_FallbackRouter` |
| `src/pyresilience/_types.py` | `FallbackConfig` (`alternatives`, `cooldown`, `cooldown_threshold`), `EventType.COOLDOWN` |
| `src/pyresilience/_executor.py` | `_execute_routed` (sync and async) |
| `src/pyresilience/_parts.py` | builds the router |
| `tests/test_fallback.py`, `tests/test_fallback_cooldown.py`, `tests/test_fallback_cooldown_async.py`, `tests/test_fallback_cooldown_cache.py`, `tests/test_timeout_deadline_fallback.py` | behaviour tests |

<!-- /agent-updatable -->

<!-- human-owned -->

## What NOT to Do

- Do NOT apply the plain handler inside the core when a router exists.
- Do NOT make cooldown reject a call by itself.

<!-- /human-owned -->
