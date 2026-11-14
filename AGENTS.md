# AGENTS.md - pyresilience

Python 3.9+ stdlib-only library (hatchling, pytest, ruff, mypy --strict) published to PyPI.

One `@resilient` decorator that composes retry, timeout, circuit breaker, fallback, bulkhead, rate limiter and result cache for sync and async functions. The public API is `__all__` in `src/pyresilience/__init__.py`; the core has zero runtime dependencies.

## HARD RULE - Before You Plan a Change

1. Read `agent-context/AGENT_INDEX.md` — it maps tasks to docs.
2. For common changes, the required reading is:

| About to... | Read first |
|---|---|
| Change pattern order, retry loop, timeout, fallback, registry or shutdown | `agent-context/domains/executor-pipeline.md`, `agent-context/conventions.md` |
| Change retry, retry budget, `delay_func`, `retry_on_result` | `agent-context/domains/retry.md` |
| Change the circuit breaker | `agent-context/domains/circuit-breaker.md` |
| Change rate limits, costs or server feedback | `agent-context/domains/rate-limiting.md` |
| Change fallback alternatives or cooldown | `agent-context/domains/fallback.md` |
| Change shared state or a state backend | `agent-context/domains/shared-state.md`, `agent-context/integrations/redis.md` |
| Add or change a public symbol, config field or preset | `agent-context/api-conventions.md`, `agent-context/error-handling.md` |
| Add or change a `contrib/` adapter or optional dependency | `agent-context/integrations/` file for it, `agent-context/architecture.md` |
| Add or change tests, CI or release steps | `agent-context/testing.md`, `agent-context/infrastructure.md` |

   How much to read is a mechanical test, not a judgment call. The task is a
   **"new thing"** if it involves ANY of: a new file, a new public class or
   exported symbol, a new config field or event type, a new integration, or a
   new dependency.
   New thing: read `AGENT_INDEX.md` plus every matching row above.
   None of the above: small edit; the matching rows above are enough. If any
   single item trips the list, the whole task is a "new thing" - do not split a
   task to dodge it.

   **Declare your reading.** The first line of any plan or implementation you
   propose must be `Context read: {files}` naming the agent-context docs you
   actually read (or `Context read: none - small edit, code only` with the
   justification). A plan without this line is incomplete.

3. **Follow the conventions you find. Do not invent or "improve" them.**
   If a convention is unclear, seems to conflict with existing code, or appears
   outdated based on what you observe - stop, surface the issue, and propose
   the change. Do NOT edit human-owned sections yourself.

4. Update `agent-context/` ONLY when you added something new to the world:
   a new exported symbol, exception, event type, integration, pattern or domain
   term - OR when you discovered a non-obvious invariant the next agent would
   miss. Edits go in sections marked `<!-- agent-updatable -->`. Do NOT modify
   sections marked `<!-- human-owned -->`. The git log is the changelog, not
   these docs - do not record routine fixes, refactors or version bumps.
   In your final summary, name the agent-context section you updated - or state
   `Context updates: none needed` and why. Omitting this line means the task is
   not done.

5. Write or update tests for every change; all tests must pass before a change
   is considered done.

## Quick Start

```bash
make dev          # uv pip install -e ".[dev]"
make test         # pytest -v
make test-cov     # branch coverage gate >= 95%
make lint         # ruff check + ruff format --check
make typecheck    # mypy --strict on src/pyresilience
```

## Inviolable Rules

These cause silent damage - the build will not catch them.

1. `_SyncExecutor` and `_AsyncExecutor` in `src/pyresilience/_executor.py` are separate, mirrored implementations. Any behavior change (order, events, fallback, retry, budget) must be made in both; the type checker will not notice if only one changes. The same applies to `_WeightedRateLimiter` / `_AsyncWeightedRateLimiter` (`_weighted_limiter.py`) and `_FallbackRouter.run_sync` / `run_async` (`_fallback.py`).
2. The pipeline order is a public semantic contract: cache, circuit breaker, rate limiter, bulkhead, retry(timeout(fn)), fallback. Do not reorder it or add a stage elsewhere without treating it as breaking.
3. `__version__` in `src/pyresilience/__init__.py` and `[project] version` in `pyproject.toml` are not compared by any test; change both together.
4. Core modules must never import optional packages (uvloop, orjson, FastAPI, Django, Flask, OpenTelemetry, Prometheus) at module top level or add runtime dependencies; the dev environment hides the breakage but user installs hit it.
5. Python 3.9 is declared but is not in the GitHub Actions matrix (3.10 to 3.15 only). Do not use `X | Y`, runtime `collections.abc` imports or `type[T]` at runtime; CI will not catch every case.
6. Registry state is shared per name: the sync and async executors of one name share the circuit breaker, rate limits, retry budget and fallback cooldown (`_Parts` in `_parts.py`), but NOT the bulkhead or the result cache. `register()` drops the cached executors and shared state of that name; already-decorated functions keep what they captured.
7. Listener failures must never reach the caller: keep `_emit`'s catch, and give any new `ResilienceEvent` field a default so existing listeners keep working.
