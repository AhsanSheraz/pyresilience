# FastAPI Integration

<!-- human-owned -->

`src/pyresilience/contrib/fastapi.py` provides an ASGI middleware and a dependency object that run requests or arbitrary callables through an `_AsyncExecutor` built from a `ResilienceConfig`. It imports no FastAPI/Starlette module itself (the middleware follows the plain ASGI interface), so it adds no dependency.

---

## Entry points

- `ResilientMiddleware(app, config=None)`: for `scope["type"] == "http"` runs the downstream app inside `executor.execute(...)`; a `CircuitOpenError` is turned into a 503 response (`_send_503`), every other exception propagates. Non-HTTP scopes pass straight through.
- `ResilientDependency(config)`: holds an executor; `call(func, *args, **kwargs)` executes `func` with resilience; `__call__` returns `self` so it works with `Depends(...)`.
- `resilient_dependency(config)`: factory returning a `ResilientDependency`.

---

## Credentials Summary

<!-- /human-owned -->

<!-- agent-updatable -->

| Component | Executor | Credentials |
|---|---|---|
| `ResilientMiddleware` | one `_AsyncExecutor` per middleware instance | none |
| `ResilientDependency` | one `_AsyncExecutor` per dependency object | none |

<!-- /agent-updatable -->

<!-- human-owned -->

---

## Known Divergences (Do Not Replicate)

- `ResilientMiddleware` wraps the whole ASGI app call. Streaming responses and bodies already sent cannot be retried safely, so do not combine it with `retry=` unless the handler is idempotent and nothing has been sent.
- Only `CircuitOpenError` is mapped to a response; `RateLimitExceededError` and `BulkheadFullError` from the same executor propagate as exceptions. Do not assume uniform HTTP mapping when adding rejections; decide explicitly.
- The module has no framework imports, so there is no import-time guard to copy; keep it that way (see `integrations/otel.md` for the guarded-import pattern used by listeners).

<!-- /human-owned -->
