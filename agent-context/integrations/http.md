# HTTP Helpers (client-agnostic)

<!-- human-owned -->

`src/pyresilience/contrib/http.py` is stdlib-only (`email.utils`, `time`). It adapts HTTP responses from any client (requests, httpx, aiohttp) via duck typing to `RetryConfig.retry_on_result` and `RetryConfig.delay_func`. It is the only contrib module imported by core code: `_presets.llm_policy` imports it lazily inside the function.

---

## Entry points

- `retry_on_status(*codes)`: returns a predicate `(obj) -> bool` reading `status_code` then `status`. Raises `ValueError` with no codes and `TypeError` for non-int codes.
- `retry_after_delay(max_wait=60.0)`: returns a `delay_func(attempt, trigger)` that parses the `Retry-After` header (delta-seconds or HTTP-date) from the response or exception, clamped to `[0, max_wait]`; returns `None` when absent or unparsable so normal backoff applies. Raises `ValueError` when `max_wait <= 0`.

- `rate_limit_feedback(calls_limit="calls", tokens_limit="tokens", max_pause=60.0)`: returns a `RateLimiterConfig.feedback` callable that reads `Retry-After` and rate-limit headers (`x-ratelimit-*`, `anthropic-ratelimit-*`, `RateLimit-*`) from a response or an exception carrying `.response` and returns a `RateLimitFeedback` or `None`. Raises `ValueError` when `max_pause <= 0`. `llm_policy(adaptive_rate_limit=True)` uses it.

All three names are in the module `__all__`. `llm_policy` (in `_presets.py`) combines them with a rate limiter, timeout and circuit breaker (default status codes 429, 500, 502, 503, 504).

---

## Credentials Summary

<!-- /human-owned -->

<!-- agent-updatable -->

| Component | Dependency | Credentials |
|---|---|---|
| `retry_on_status`, `retry_after_delay`, `rate_limit_feedback` | none (stdlib) | none |

`rate_limit_feedback(*, calls_limit="calls", tokens_limit="tokens", max_pause=60.0)` returns a `RateLimiterConfig.feedback` callable. It reads `Retry-After`, `x-ratelimit-remaining-requests`, `anthropic-ratelimit-requests-remaining`, `x-ratelimit-remaining`, `RateLimit-Remaining`, the token equivalents and the matching reset headers, from a response or the response attached to an exception. It returns `None` on anything missing or unparseable. `max_pause <= 0` raises `ValueError`. Limiter side: `../domains/rate-limiting.md`.

<!-- /agent-updatable -->

<!-- human-owned -->

---

## Known Divergences (Do Not Replicate)

- Do not import `requests`, `httpx` or `aiohttp` in this module; keep it duck-typed so core stays dependency-free.
- Keep the import of this module inside `llm_policy` lazy; a top-level import from `_presets.py` would couple core import time to a contrib module.
- Status-based retries depend on the result path: the retry budget applies to them since 0.4.1, and when the budget runs out the last response is returned, not raised.

<!-- /human-owned -->
