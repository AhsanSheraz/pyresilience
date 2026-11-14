# API Conventions

This repo is a library: the "API" is the public Python surface, not HTTP.

<!-- human-owned -->

## API Style

- The contract is `__all__` in `src/pyresilience/__init__.py`. Anything not listed (for example `Bulkhead`, `AsyncBulkhead`, `_SyncExecutor`) is private, even when importable from a private module.
- Two public re-export modules exist and must keep working: `pyresilience.presets` and `pyresilience.logging` (they re-export from `_presets.py` / `_logging.py`).
- Optional adapters live under `pyresilience.contrib.*` and are imported by path; they are not in the top-level `__all__`.
- `__version__` is defined in `__init__.py` but is not in `__all__`; it must equal `[project] version` in `pyproject.toml`.
- Code-first: there are no spec files or generated sources.

### Adding a New Public Symbol

1. Implement it in the appropriate private module (`_types.py` for config/event contracts, `_exceptions.py` for errors, a pattern module otherwise).
2. Import it in `src/pyresilience/__init__.py` and add it to `__all__` (keep the list sorted as it is today).
3. For presets or logging helpers, also export it from `presets.py` / `logging.py`.
4. Add a smoke import test (see `tests/test_public_modules.py`) and a CHANGELOG entry.
5. Treat the addition as additive; treat any removal, rename or signature change as breaking.

### Generated Code Notes

None. There is no generated code in this repo.

## Base Path

Not applicable (no HTTP surface). Import root is `pyresilience`.

## API Doc Surfaces

`docs/api.md` plus the pages under `docs/core/` and `docs/advanced/`, built by mkdocs (`mkdocs.yml`) and hosted on Read the Docs. <!-- verify: whether docs/api.md is hand-written or generated unconfirmed -->

<!-- /human-owned -->

## Public API Catalog

<!-- agent-updatable -->

Enumerated from `__all__` in `src/pyresilience/__init__.py` (46 entries).

### Decorator and registry

| Symbol | Kind | Defined in |
|---|---|---|
| `resilient` | function (overloaded decorator; keyword args `retry, timeout, circuit_breaker, fallback, bulkhead, rate_limiter, cache, retry_budget, listeners, shared_state`) | `_decorator.py` |
| `ResilienceRegistry` | class | `_registry.py` |
| `health_check` | function (`registry -> dict`) | `_health.py` |

### Configuration dataclasses

| Symbol | Kind | Defined in |
|---|---|---|
| `ResilienceConfig` | dataclass (composite + `listeners`) | `_types.py` |
| `RetryConfig` | dataclass | `_types.py` |
| `TimeoutConfig` | dataclass | `_types.py` |
| `CircuitBreakerConfig` | dataclass | `_types.py` |
| `FallbackConfig` | dataclass | `_types.py` |
| `BulkheadConfig` | dataclass | `_types.py` |
| `RateLimiterConfig` | dataclass | `_types.py` |
| `CacheConfig` | dataclass | `_types.py` |
| `RetryBudgetConfig` | dataclass | `_types.py` |
| `RateLimit` | dataclass: an additional limit (`max_units`, `period`, `name`, `cost`, `actual_cost`) | `_types.py` |
| `RateLimitFeedback` | frozen dataclass: server report (`retry_after`, `remaining`) returned by `RateLimiterConfig.feedback` | `_types.py` |
| `SharedStateConfig` | dataclass (`backend`, `key`, `sync_interval`, `fail_open`; method `sync_now()`) | `_types.py` |

New config fields (all optional, defaults keep old behaviour):

| Config | Field | Meaning |
|---|---|---|
| `TimeoutConfig` | `total_seconds` | overall deadline for all attempts and retry waits; requires `per_attempt=True` |
| `TimeoutConfig` | `stream_idle_seconds` | idle limit between items of an iterator / async iterator result |
| `RateLimiterConfig` | `cost`, `actual_cost` | units per call for the primary limit, and the real cost read from the result |
| `RateLimiterConfig` | `limits` | extra `RateLimit`s enforced together with the primary limit |
| `RateLimiterConfig` | `feedback` | callable returning `RateLimitFeedback` from each attempt's outcome |
| `RateLimiterConfig` | `charge_retries` | debit every retry attempt against the limits |
| `FallbackConfig` | `alternatives` | callables tried in order with the original arguments |
| `FallbackConfig` | `cooldown`, `cooldown_threshold` | skip a failing target for `cooldown` seconds after N consecutive failures |
| `ResilienceConfig` | `shared_state` | `SharedStateConfig`; also `@resilient(shared_state=...)` |

### Events and observability

| Symbol | Kind | Defined in |
|---|---|---|
| `ResilienceEvent` | frozen dataclass | `_types.py` |
| `EventType` | enum (0.5.0 adds `COOLDOWN`) | `_types.py` |
| `CircuitState` | enum | `_types.py` |
| `ResilienceListener` | type alias `Callable[[ResilienceEvent], None]` | `_types.py` |
| `JsonEventLogger` | class (listener) | `_logging.py` |
| `MetricsCollector` | class (listener) | `_logging.py` |
| `resilience_context` | `ContextVar[Optional[dict]]` | `_logging.py` |

### Pattern classes (usable standalone)

| Symbol | Kind | Defined in |
|---|---|---|
| `CircuitBreaker` | class | `_circuit_breaker.py` |
| `RetryBudget` | class | `_retry_budget.py` |
| `RateLimiter`, `AsyncRateLimiter` | classes | `_rate_limiter.py` |
| `ResultCache`, `AsyncResultCache` | classes | `_cache.py` |
| `StateBackend` | runtime-checkable Protocol (`get`, `set`, `incr`, `delete`) | `_backend.py` |
| `InMemoryBackend` | class (thread-safe, in-process `StateBackend`) | `_backend.py` |

### Exceptions

| Symbol | Kind | Defined in |
|---|---|---|
| `ResilienceError`, `CircuitOpenError`, `BulkheadFullError`, `RateLimitExceededError`, `ResilienceTimeoutError` | exceptions | `_exceptions.py` (`RateLimitExceededError` is re-exported by `_rate_limiter.py`) |

See `error-handling.md`.

### Presets

| Symbol | Kind | Defined in |
|---|---|---|
| `http_policy`, `db_policy`, `queue_policy`, `llm_policy`, `strict_policy` | functions returning `dict[str, Any]` | `_presets.py` (also exported from `presets.py`) |

`llm_policy` parameters added in 0.5.0: `tokens_per_minute`, `token_cost`, `token_usage`, `adaptive_rate_limit`, `rate_limit_max_wait`. `tokens_per_minute` without `token_cost` or `token_usage` raises `ValueError`.

### Lifecycle and runtime helpers

| Symbol | Kind | Defined in |
|---|---|---|
| `shutdown` | function `(wait=True, timeout=30.0) -> bool` | `_executor.py` |
| `enable_in_flight_tracking`, `get_in_flight_count` | functions | `_executor.py` |
| `has_uvloop`, `has_orjson`, `install_uvloop` | functions | `_compat.py` |

### Public re-export modules

| Module | Exports |
|---|---|
| `pyresilience.presets` | `db_policy, http_policy, llm_policy, queue_policy, strict_policy` |
| `pyresilience.logging` | `JsonEventLogger, MetricsCollector` (note: `resilience_context` is exported from the top level only) |

### Contrib entry points

| Module | Public names | Doc |
|---|---|---|
| `pyresilience.contrib.fastapi` | `ResilientMiddleware`, `ResilientDependency`, `resilient_dependency` | `integrations/fastapi.md` |
| `pyresilience.contrib.django` | `ResilientMiddleware`, `resilient_view` | `integrations/django.md` |
| `pyresilience.contrib.flask` | `Resilience`, `resilient_route` | `integrations/flask.md` |
| `pyresilience.contrib.http` | `retry_on_status`, `retry_after_delay`, `rate_limit_feedback` (`__all__`) | `integrations/http.md` |
| `pyresilience.contrib.otel` | `OpenTelemetryListener` | `integrations/otel.md` |
| `pyresilience.contrib.prometheus` | `PrometheusListener` | `integrations/prometheus.md` |
| `pyresilience.contrib.redis` | `RedisBackend` (`__all__`) | `integrations/redis.md` |

<!-- /agent-updatable -->

<!-- human-owned -->

## Request/Response Patterns

- Config classes are plain mutable `@dataclass`es with keyword defaults; `ResilienceEvent` is `@dataclass(frozen=True)` and new fields need defaults.
- `@resilient` supports bare `@resilient` and `@resilient(...)`. Bare use applies no patterns (it only wraps).
- Wrapped functions expose `wrapper._executor` for introspection (`health_check` reads `executor._circuit_breaker` by `getattr`).
- Presets use keyword-only arguments and return a splattable dict; optional entries are added only when set.
- Sync vs async is auto-detected; there is no separate async decorator.

## Error Responses

Errors are Python exceptions; see `error-handling.md`.

## What NOT to Do

- Do NOT remove, rename or change the signature of anything in `__all__` without explicit approval.
- Do NOT add a symbol to `__all__` without a test and a CHANGELOG entry.
- Do NOT import `contrib` modules from the core package at module load time (the lazy import in `_presets.llm_policy` is the only core to contrib link).
- Do NOT let `__version__` and `pyproject.toml` version drift.

<!-- /human-owned -->
