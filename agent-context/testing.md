# Testing

<!-- human-owned -->

## Test Types

- **Unit tests per feature**: one `tests/test_<feature>.py` per module or pattern (`test_retry.py`, `test_circuit_breaker.py`, `test_bulkhead.py`, `test_rate_limiter.py`, `test_cache.py`, `test_timeout.py`, `test_fallback.py`, `test_retry_budget.py`, `test_sliding_window.py`, `test_registry.py`, `test_shutdown.py`, ...). Framework: pytest.
- **Cross-pattern tests**: `test_combined.py`, `test_events.py`, `test_context.py` for user-visible interactions only.
- **Contrib tests**: `test_contrib.py`, `test_contrib_http.py`, `test_otel.py`, `test_prometheus.py`.
- **Public surface tests**: `test_public_modules.py`, `test_main.py` (checks that `python -m pyresilience` prints `__version__`; no test compares it with `pyproject.toml`, so keep both in sync by hand).
- Async tests are plain `async def test_...` functions: `asyncio_mode = "auto"` in `pyproject.toml`.

## Test Profile Guards

Not applicable (no profiles, no external services). Tests must not need network, credentials or optional frameworks.

## Mocking Rules

No mocking framework is used. Use plain functions, closures and `nonlocal` counters, and a `listener` that appends to a list to assert on `EventType`. There is no `conftest.py`; define helpers locally in each test file.

## Naming and Layout

- Files start with a docstring, then `from __future__ import annotations`.
- Group in `class Test<Concept><Mode>` (for example `TestRetryBudget`, `TestRetryBudgetAsync`); methods are `test_<behavior_in_snake_case>`.
- Cover both sync and async variants for every pattern that has an `Async*` sibling.
- Add one test per `__post_init__` `raise`, using `pytest.raises(ValueError, match="...")`.
- Keep delays tiny (`delay=0.01`) and use `jitter=False` for deterministic timing; leave headroom for Windows timer resolution and avoid tight upper bounds on elapsed time.
- Example to copy: `tests/test_retry_budget.py` (parametrised sync/async, listener on/off).

## Running Tests

```bash
make test        # pytest -v
make test-cov    # pytest -v --cov=pyresilience --cov-branch --cov-report=term-missing --cov-fail-under=95
pytest -v tests/test_retry_budget.py
pytest -v tests/test_retry_budget.py::TestRetryBudget::test_acquire_until_depleted
```

## What NOT to Do

- Do NOT weaken or bypass the `--cov-fail-under=95` branch coverage gate.
- Do NOT introduce `unittest.mock`/fixture frameworks or a `conftest.py` without approval.
- Do NOT write tests that depend on wall-clock precision, network access or installed optional frameworks without a guard.
- Do NOT leave `pdb` or `breakpoint()` in tests (pre-commit `debug-statements`).

<!-- /human-owned -->

<!-- agent-updatable -->

## Test Inventory (0.5.0)

- 797 tests as of 0.5.0, passing on Python 3.9, 3.10, 3.14 and 3.15.
- Files added in 0.5.0: `test_timeout_deadline.py`, `test_stream_timeout.py`, `test_rate_limiter_weighted.py`, `test_rate_limiter_feedback.py`, `test_rate_limiter_weighted_decorator.py`, `test_contrib_http_feedback.py`, `test_fallback_cooldown.py`, `test_fallback_cooldown_async.py`, `test_backend.py`, `test_registry_shared.py`, `test_shared_breaker.py`, `test_shared_limits.py`, `test_shared_sync.py`.
- Shared-state tests use `InMemoryBackend`; none needs a running Redis.

<!-- /agent-updatable -->
