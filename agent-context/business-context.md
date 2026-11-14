# Business Context

<!-- human-owned -->

## Parent Product

`pyresilience` is an open-source (MIT) Python library published to PyPI. It is positioned as "Python's Resilience4j": one coordinated decorator, `@resilient(...)`, that combines retry, timeout, circuit breaker, fallback, bulkhead, rate limiter and result cache for sync and async functions. There is no parent platform; the consumers are application authors who install the package into their own services.

## This Service's Role

`pyresilience` is a single-process library with a zero-runtime-dependency core (stdlib only). It owns:

- The `@resilient` decorator and the fixed order in which patterns are applied around a wrapped call.
- The configuration dataclasses and event model (`ResilienceEvent`, `EventType`) that define its public contract.
- Pattern state machines (circuit breaker, token buckets, bulkhead, LRU+TTL cache).
- Named shared state via `ResilienceRegistry`.
- Optional adapters under `src/pyresilience/contrib/`.

It does NOT own:

- HTTP clients, ORMs, queue clients: it wraps them, it does not replace them.
- Distributed coordination (service discovery, leader election, cross-process rate limits).
- Metrics storage or dashboards: it emits events; listeners forward them.
- Deployment: there is no server, container or database in this repo.

## Actors

| Actor | Who | Interaction |
|---|---|---|
| Library user | App author | Imports from `pyresilience` (the `__all__` surface), applies `@resilient` |
| Framework integrator | FastAPI / Django / Flask user | `pyresilience.contrib.*` |
| Observability integrator | OTel / Prometheus user | `contrib/otel.py`, `contrib/prometheus.py`, `JsonEventLogger`, `MetricsCollector` |
| Maintainer | Repo owner | PRs, releases (tag-driven publish) |
| CI | GitHub Actions | Lint, mypy, tests, coverage gate |

## Bounded Contexts in This Service

| Context | Doc |
|---|---|
| Executor / pattern pipeline, registry, shared state | `domains/executor-pipeline.md` |
| Retry, retry budget, `Retry-After` handling | `domains/retry.md` |
| Circuit breaker | `domains/circuit-breaker.md` |

Bulkhead, rate limiter and cache are small self-contained modules; they are covered in `architecture.md` and the pipeline doc rather than separate files.

## High-Level Vocabulary

See `glossary.md`. Minimum to read the rest:

- **Pattern**: one of retry, timeout, circuit breaker, fallback, bulkhead, rate limiter, cache.
- **Executor**: `_SyncExecutor` / `_AsyncExecutor`, which run the patterns around one function.
- **Listener**: a `Callable[[ResilienceEvent], None]` that receives every emitted event.
- **Registry**: `ResilienceRegistry`, named configs whose stateful components are shared.
- **Preset / policy**: a function returning a dict to splat into `@resilient(**policy)`.

## Why This Matters for Agents

1. **Zero runtime dependencies in core.** The "no dependencies" promise is load-bearing. Only `[project.optional-dependencies]` extras may add packages; framework and telemetry imports in `contrib/` must stay lazy or guarded.
2. **The public API is `__all__` in `src/pyresilience/__init__.py`.** Removing or renaming a symbol, changing a config field, or reordering the pipeline is a breaking change for users.
3. **Python 3.9 source compatibility.** The package declares `requires-python >=3.9` and mypy/ruff target 3.9, so runtime syntax must stay 3.9-safe.

When in doubt about whether a change is permissible, check whether it preserves these invariants.

<!-- /human-owned -->
