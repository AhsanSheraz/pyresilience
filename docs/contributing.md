# Contributing

Contributions are welcome! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/AhsanSheraz/pyresilience.git
cd pyresilience
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest -v
```

With coverage:

```bash
pytest --cov=pyresilience --cov-branch --cov-report=term-missing --cov-fail-under=95
```

## Linting

```bash
ruff check src/ tests/
ruff format src/ tests/
```

## Type Checking

```bash
mypy src/pyresilience
```

## Project Structure

```
src/pyresilience/
    __init__.py          # Public API exports
    _types.py            # All config dataclasses and event types
    _decorator.py        # The @resilient() decorator
    _executor.py         # Core execution pipeline (sync + async)
    _circuit_breaker.py  # Circuit breaker state machine
    _bulkhead.py         # Semaphore-based concurrency limiter
    _rate_limiter.py     # Token bucket rate limiter
    _cache.py            # LRU result cache with TTL
    _registry.py         # Named resilience instance management
    _presets.py          # Opinionated default configs
    _logging.py          # JsonEventLogger + MetricsCollector
    _compat.py           # Runtime backend detection (uvloop, orjson)

tests/
    test_retry.py
    test_timeout.py
    test_circuit_breaker.py
    test_fallback.py
    test_bulkhead.py
    test_rate_limiter.py
    test_cache.py
    test_registry.py
    test_combined.py
    test_events.py
    test_presets.py
    test_logging.py
    test_compat.py
```

## Guidelines

- Keep zero runtime dependencies
- Support Python 3.9+
- Maintain >95% test coverage
- All code must pass `ruff check`, `ruff format --check`, and `mypy --strict`
- Follow existing patterns for new resilience modules
- Add tests for every new feature
