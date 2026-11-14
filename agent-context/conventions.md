# Conventions

<!-- human-owned -->

## Naming Conventions

### Packages / Modules

- Implementation modules are `_lower_snake_case.py` (`_executor.py`, `_types.py`, `_circuit_breaker.py`).
- Public modules have no underscore: `presets.py`, `logging.py` (thin re-exports), `contrib/*.py`.
- Every module opens with a one-line docstring, then `from __future__ import annotations`, then stdlib imports, then `pyresilience._*` imports; forward-only types go under `if TYPE_CHECKING:` (see `_registry.py`, `_retry_budget.py`).

### Classes / Files

- Config dataclasses: `<Concept>Config`. Exceptions: `<Concept>Error`. Async sibling: `Async<Name>` in the same module as the sync class. Internal classes: `_LeadingUnderscore` (`_SyncExecutor`).
- Enum members are `UPPER_SNAKE_CASE` with lowercase string values (`EventType.RETRY = "retry"`).
- Tests: `tests/test_<feature>.py`, classes `Test<Concept><Mode>`.

### Methods / Functions

- `lower_snake_case`; presets are `<dependency>_policy` with keyword-only arguments and a `dict[str, Any]` return.
- Hot-path module constants and cached callables are bound at module level (`_monotonic = time.monotonic`, `_random = random.random`).

## Dependency Injection

None. Components are constructed from config in the executor `__init__`; shared instances are obtained by using the same `ResilienceRegistry` name.

## Annotation / Decorator Patterns

- `@resilient` supports `@resilient` and `@resilient(...)` through `@overload`s in `_decorator.py`; it uses `functools.wraps` and sets `wrapper._executor` with `# type: ignore[attr-defined]`.
- `# type: ignore[...]` must always carry an explicit error code.
- Classes on the hot path use `__slots__` (`_SyncExecutor`, `CircuitBreaker`, `RetryBudget`, `RateLimiter`, `ResultCache`).

## Type Declarations

- Python 3.9 compatible: use `Optional[T]`, `Union[A, B]`, `Sequence[T]`, `Type[T]` from `typing`. Lowercase `list[T]` / `dict[K, V]` / `tuple[...]` annotations are used in the code base (safe because of `from __future__ import annotations` and 3.9 runtime support).
- `mypy --strict` must pass on `src/pyresilience`; annotate every function and attribute.
- Untyped third-party modules (`uvloop`, `orjson`, `opentelemetry`, `prometheus_client`) are covered by `[[tool.mypy.overrides]] ignore_missing_imports`.

## Logging

- The library logs only through `logging.getLogger("pyresilience")` (`_executor.py`, `_logging.py`). `print()` appears only in `__main__.py`.
- Events are the primary observability channel; add an `EventType` rather than ad-hoc logging for new behaviours.
- Per-call context uses `contextvars` (`call_id_var`, `resilience_context`) so it survives `await`; never use `threading.local` for async-touching state.

## Transaction Management

Not applicable (no persistence). The analogous rule is state safety: every stateful object guards mutation with `threading.Lock` (sync) and the async siblings rely on single-threaded event-loop semantics or `asyncio` primitives (see `AsyncBulkhead`, `AsyncRateLimiter`, `AsyncResultCache`).

## Error Handling

Typed exceptions inherit from `ResilienceError`; config validation raises `ValueError` in `__post_init__`. See `error-handling.md`.

## Query / ORM Conventions

Not applicable.

## What NOT to Do

- Do NOT use `X | Y`, `X | None`, runtime `from collections.abc import ...` or `type[T]` at runtime (ruff ignores UP006/UP007/UP035/UP045 to keep 3.9 syntax).
- Do NOT add per-call work to `_executor.py` hot paths without keeping the module's documented optimizations (pre-cached attributes, inlined `isinstance`, listener-bool guard, local hoisting); run `benchmarks/bench_overhead.py` for non-trivial changes.
- Do NOT use mutable default values in dataclasses; use `field(default_factory=...)`.
- Do NOT add fields to `ResilienceEvent` without defaults.
- Do NOT change a pattern without updating its async sibling.

<!-- /human-owned -->
