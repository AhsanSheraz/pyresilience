# Django Integration

<!-- human-owned -->

`src/pyresilience/contrib/django.py` offers a middleware configured from Django settings and a per-view decorator. Both use `_SyncExecutor`. Django is imported lazily inside `ResilientMiddleware._load_config` (`from django.conf import settings`) so the module imports without Django installed.

---

## Entry points

- `ResilientMiddleware(get_response)`: builds its executor on first request from `settings.PYRESILIENCE_CONFIG` (dict). Recognised keys: `timeout_seconds`, `circuit_failure_threshold` (with optional `circuit_recovery_seconds`, default 30.0), `max_attempts` (with optional `retry_delay`, default 1.0), and the deprecated `max_retries` (emits `DeprecationWarning`, used only when `max_attempts` is absent). Missing Django means an empty config.
- `resilient_view(*, retry=None, timeout=None, circuit_breaker=None)`: decorator that builds one `_SyncExecutor` at decoration time and runs the view through it.

---

## Credentials Summary

<!-- /human-owned -->

<!-- agent-updatable -->

| Component | Executor | Credentials |
|---|---|---|
| `ResilientMiddleware` | one lazily created `_SyncExecutor` per middleware instance | none |
| `resilient_view` | one `_SyncExecutor` per decorated view factory call | none |

<!-- /agent-updatable -->

<!-- human-owned -->

---

## Known Divergences (Do Not Replicate)

- Settings keys are an ad-hoc flat dict, not `ResilienceConfig` fields; only retry, timeout and circuit breaker can be configured through settings. New options need explicit mapping code and tests.
- `_load_config` swallows `ImportError` for Django and silently returns an empty config; a missing or misspelled `PYRESILIENCE_CONFIG` key has no effect and no warning.
- `resilient_view` does not expose fallback, bulkhead, rate limiter, cache, retry budget or listeners, unlike `@resilient`.

<!-- /human-owned -->
