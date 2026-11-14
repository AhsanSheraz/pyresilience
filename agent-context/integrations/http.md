# HTTP Helpers (client-agnostic)

<!-- human-owned -->

`src/pyresilience/contrib/http.py` is stdlib-only (`email.utils`, `time`). It adapts HTTP responses from any client (requests, httpx, aiohttp) via duck typing to `RetryConfig.retry_on_result` and `RetryConfig.delay_func`. It is the only contrib module imported by core code: `_presets.llm_policy` imports it lazily inside the function.

---

## Entry points

- `retry_on_status(*codes)`: returns a predicate `(obj) -> bool` reading `status_code` then `status`. Raises `ValueError` with no codes and `TypeError` for non-int codes.
- `retry_after_delay(max_wait=60.0)`: returns a `delay_func(attempt, trigger)` that parses the `Retry-After` header (delta-seconds or HTTP-date) from the response or exception, clamped to `[0, max_wait]`; returns `None` when absent or unparsable so normal backoff applies. Raises `ValueError` when `max_wait <= 0`.

Both names are in the module `__all__`. `llm_policy` (in `_presets.py`) combines them with a rate limiter, timeout and circuit breaker (default status codes 429, 500, 502, 503, 504).

---

## Credentials Summary

<!-- /human-owned -->

<!-- agent-updatable -->

| Component | Dependency | Credentials |
|---|---|---|
| `retry_on_status`, `retry_after_delay` | none (stdlib) | none |

<!-- /agent-updatable -->

<!-- human-owned -->

---

## Known Divergences (Do Not Replicate)

- Do not import `requests`, `httpx` or `aiohttp` in this module; keep it duck-typed so core stays dependency-free.
- Keep the import of this module inside `llm_policy` lazy; a top-level import from `_presets.py` would couple core import time to a contrib module.
- Status-based retries depend on the result path: the retry budget applies to them since 0.4.1, and when the budget runs out the last response is returned, not raised.

<!-- /human-owned -->
