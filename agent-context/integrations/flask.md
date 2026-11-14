# Flask Integration

<!-- human-owned -->

`src/pyresilience/contrib/flask.py` provides a Flask extension object and a route decorator, both built on `_SyncExecutor`. It does not import Flask; it only calls `app.before_request(...)` and sets `app.extensions["pyresilience"]` on the object passed to `init_app`.

---

## Entry points

- `Resilience(app=None, config=None)` with `init_app(app, config=None)`: builds one `_SyncExecutor` (empty `ResilienceConfig` when none given), registers a `before_request` hook and stores itself in `app.extensions`. `executor` property raises `RuntimeError` before `init_app`. `call(func, *args, **kwargs)` runs a callable through the executor.
- `resilient_route(*, retry=None, timeout=None, circuit_breaker=None)`: decorator applying those three patterns to a view.

---

## Credentials Summary

<!-- /human-owned -->

<!-- agent-updatable -->

| Component | Executor | Credentials |
|---|---|---|
| `Resilience` | one `_SyncExecutor` per `init_app` call | none |
| `resilient_route` | one `_SyncExecutor` per decorator call | none |

<!-- /agent-updatable -->

<!-- human-owned -->

---

## Known Divergences (Do Not Replicate)

- The `before_request` hook (`_before_request`) is a no-op placeholder: installing the extension does NOT wrap requests automatically. Resilience applies only through `Resilience.call` or `resilient_route`.
- `resilient_route` exposes only retry, timeout and circuit breaker, not the full `@resilient` option set.

<!-- /human-owned -->
