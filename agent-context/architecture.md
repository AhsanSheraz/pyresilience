# Architecture

<!-- human-owned -->

## System Overview

`pyresilience` is a single-process Python library (3.9 to 3.14, stdlib only in core). The public decorator `@resilient` wraps a function in an executor object that applies a fixed pipeline of resilience patterns and emits `ResilienceEvent`s to listeners. There is no service, network surface, database or deployment target in this repo.

## Architecture Style

- **Decorator plus executor**: `_decorator.resilient` picks `_AsyncExecutor` when `inspect.iscoroutinefunction(fn)` is true, otherwise `_SyncExecutor`. Both live in `src/pyresilience/_executor.py` and mirror each other.
- **Config dataclasses as the contract**: every pattern is configured by a `*Config` dataclass in `src/pyresilience/_types.py`; `ResilienceConfig` composes them.
- **Sync/async sibling classes**: bulkhead, rate limiter and cache have `Foo` and `AsyncFoo` in the same module. The circuit breaker and retry budget are single thread-locked classes used by both executors. The circuit breaker, rate limiter state, retry budget and fallback router are built once into `_Parts` (`_parts.py`) and shared by the sync and async executors of a registry name; with `SharedStateConfig` they exchange state through a `StateBackend`.
- **Private modules, public facade**: implementation lives in `_underscore` modules; `__init__.py` `__all__` is the contract. `presets.py` and `logging.py` are thin public re-exports.
- **Hot-path performance discipline**: `_executor.py` pre-caches config as instance attributes (`__slots__`), inlines `isinstance`, guards `_emit` behind a `has_listeners` bool and has a no-retry/no-timeout fast path.

## Key Architectural Boundaries

```
caller -> @resilient wrapper (_decorator.py)
            -> _SyncExecutor / _AsyncExecutor.execute (_executor.py)
                 cache -> circuit breaker -> rate limiter -> bulkhead
                   -> retry loop { circuit re-check (attempt>1), per-attempt or total timeout, fn }
                   -> fallback
            -> listeners (JsonEventLogger, MetricsCollector, contrib listeners)
```

Layers (conceptual):

| Layer | Modules |
|---|---|
| Public API | `__init__.py`, `_decorator.py`, `presets.py`, `logging.py`, `_registry.py` |
| Orchestration | `_executor.py`, `_parts.py`, `_events.py`, `_fallback.py`, `_stream.py` |
| Patterns | `_retry_budget.py`, `_circuit_breaker.py`, `_bulkhead.py`, `_rate_limiter.py`, `_limiter_core.py`, `_weighted_limiter.py`, `_cache.py` |
| State sharing | `_backend.py`, `_shared.py`, `_shared_breaker.py` |
| Contracts | `_types.py`, `_exceptions.py` |
| Observability | `_logging.py`, `_health.py` |
| Compatibility | `_compat.py` |
| Adapters | `contrib/*.py` (see `integrations/`) |

Details of the pipeline, registry sharing and shutdown are in `domains/executor-pipeline.md`.

<!-- /human-owned -->

<!-- agent-updatable -->

## External Service Dependencies

None at runtime. Optional packages are detected or imported lazily; see `integrations/` and `infrastructure.md`.

## Technology Stack

| Layer | Technology |
|---|---|
| Language | Python `>=3.9` (`pyproject.toml`); CI matrix runs 3.10 to 3.15, tox lists py39 to py315 |
| Runtime deps | none (`pyproject.toml` has no `dependencies`) |
| Optional extras | `fast` (uvloop on non-Windows, orjson), `dev` (pytest, pytest-cov, pytest-asyncio, mypy, ruff) |
| Build backend | hatchling (wheel packages `src/pyresilience`) |
| Dev tooling | uv, ruff (`ruff.toml` authoritative), mypy `--strict`, pre-commit |
| Tests | pytest with `asyncio_mode = "auto"`, coverage gate 95% branch |
| Docs | mkdocs-material, `docs/` |

## Key Directories

- `src/pyresilience/` - library package (see layer table above); `py.typed` marker is present.
- `src/pyresilience/contrib/` - `fastapi.py`, `django.py`, `flask.py`, `http.py`, `otel.py`, `prometheus.py`, `redis.py`.
- `tests/` - pytest suite, one `test_*.py` per feature; no `conftest.py`.

### Internal modules added in 0.5.0 (`src/pyresilience/`)

| Module | Owns |
|---|---|
| `_events.py` | `_emit` (moved out of `_executor.py`); catches listener exceptions |
| `_stream.py` | `_wrap_stream`, `_IdleTimeoutIterator`, `_IdleTimeoutAsyncIterator` for `TimeoutConfig.stream_idle_seconds` |
| `_limiter_core.py` | `_Bucket`, `_LimiterCore`: token buckets, all-or-nothing reserve, reconcile, feedback, pause |
| `_weighted_limiter.py` | `_WeightedRateLimiter`, `_AsyncWeightedRateLimiter`, `_needs_weighted_limiter` |
| `_fallback.py` | `_apply_fallback`, `_apply_fallback_async`, `_FallbackRouter` (alternatives, cooldown) |
| `_backend.py` | `StateBackend` protocol, `InMemoryBackend` (both public) |
| `_shared.py` | `_Syncer`, `_SharedWindows`, `_SyncedRetryBudget` |
| `_shared_breaker.py` | `_SyncedCircuitBreaker` |
| `_parts.py` | `_Parts`, `_build_parts`: stateful parts built once and shared by sync and async executors |
| `contrib/redis.py` | `RedisBackend` |

Details: `domains/rate-limiting.md`, `domains/fallback.md`, `domains/shared-state.md`, `domains/executor-pipeline.md`.
- `benchmarks/` - `bench_overhead.py`, `bench_new_features.py`, `bench_compare.py`, `full_benchmark.py`, `stress_test.py`, `README.md`.
- `examples/` - runnable examples.
- `docs/` - mkdocs sources (`core/`, `advanced/`, `getting-started/`, `api.md`).
- `.github/workflows/` - `ci.yml`, `docs.yml`, `auto-merge-dependabot.yml`.

<!-- /agent-updatable -->

<!-- human-owned -->

## What NOT to Do

- Do NOT add a runtime dependency to the core package; only optional extras.
- Do NOT reorder the pipeline in `_executor.py` or change which patterns run before others without treating it as a breaking change.
- Do NOT duplicate orchestration logic in `contrib/`; reuse `_SyncExecutor` / `_AsyncExecutor`.
- Do NOT touch `src/pyresilience/py.typed`.
- Do NOT use 3.10+ runtime syntax (`X | Y`, runtime `collections.abc` imports, `type[T]` at runtime).

<!-- /human-owned -->
