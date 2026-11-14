# HTTP & LLM Helpers

`pyresilience.contrib.http` provides stdlib-only building blocks for the most common resilience
need on the internet today: **handling HTTP 429 rate limits and `Retry-After` headers** when
calling REST and LLM APIs.

The helpers are duck-typed — they work with `requests`, `httpx`, and `aiohttp` response objects
without importing any of them. The module has zero dependencies beyond the Python standard
library, so the core package's zero-deps promise holds.

```python
from pyresilience.contrib.http import retry_on_status, retry_after_delay
```

!!! note
    These helpers live under `pyresilience.contrib.http` and are **not** re-exported from the
    package root, matching the other `contrib` integrations. The [`llm_policy()`](presets.md#llm_policy)
    preset wires them up for you.

## `retry_on_status(*codes)`

Builds a predicate for [`RetryConfig.retry_on_result`](../core/retry.md#retry-on-result) that
returns `True` when a response's status code matches one of `codes`.

```python
from pyresilience import resilient, RetryConfig
from pyresilience.contrib.http import retry_on_status

@resilient(retry=RetryConfig(
    max_attempts=4,
    retry_on_result=retry_on_status(429, 500, 502, 503, 504),
))
def call_api():
    return requests.get("https://api.example.com/data")   # don't raise_for_status()
```

Behavior:

- Reads `response.status_code` (requests/httpx) first, then `response.status` (aiohttp).
- Only genuine integers match — strings like `"429"` and `bool` values are rejected.
- Returns `False` for anything that isn't response-shaped, so it's safe with mixed return types.
- Raises `ValueError` when called with no codes and `TypeError` for non-integer codes.

## `retry_after_delay(max_wait=60.0)`

Builds a [`delay_func`](../core/retry.md#dynamic-delays-delay_func) that reads the `Retry-After`
header from the object that triggered the retry and waits exactly as long as the server asked —
instead of guessing with exponential backoff.

```python
from pyresilience import resilient, RetryConfig
from pyresilience.contrib.http import retry_on_status, retry_after_delay

@resilient(retry=RetryConfig(
    max_attempts=4,
    delay=1.0,                                   # backoff base when no Retry-After is present
    retry_on_result=retry_on_status(429, 503),
    delay_func=retry_after_delay(max_wait=60.0),
))
def call_api():
    return requests.get("https://api.example.com/data")
```

Behavior:

- Header sources, in order: `trigger.headers`, then `trigger.response.headers` (covers
  `requests.HTTPError`-shaped exceptions raised by `raise_for_status()`).
- Parses both `Retry-After` forms: delta-seconds (`"30"`) and HTTP-date
  (`"Wed, 21 Oct 2026 07:28:00 GMT"`).
- Returns `None` when the header is missing or unparseable — pyresilience then falls back to the
  configured exponential backoff. Your retries never break because of a weird header.
- The returned delay is clamped to `[0, max_wait]`, so a misbehaving server can't make your
  client sleep for an hour.
- Raises `ValueError` at build time when `max_wait <= 0`.

## `rate_limit_feedback()` { #rate_limit_feedback }

A `feedback` function for `RateLimiterConfig.feedback`. It reads the headers of each attempt's
response, or of the response attached to a raised exception, and tells the client-side limiter
what the server reported:

```python
from pyresilience import resilient, RateLimit, RateLimiterConfig
from pyresilience.contrib.http import rate_limit_feedback

@resilient(
    rate_limiter=RateLimiterConfig(
        max_calls=60,
        period=60.0,
        limits=[RateLimit(90_000, 60.0, name="tokens", cost=lambda prompt: len(prompt) // 4)],
        feedback=rate_limit_feedback(),
    ),
)
def ask_model(prompt: str):
    return http_client.post(url, json={"input": prompt})
```

| Header | Effect |
|---|---|
| `Retry-After` (seconds or HTTP-date) | Pause the limiter |
| `x-ratelimit-remaining-requests`, `anthropic-ratelimit-requests-remaining`, `x-ratelimit-remaining`, `RateLimit-Remaining` | Lower the request limit to the reported value |
| `x-ratelimit-remaining-tokens`, `anthropic-ratelimit-tokens-remaining` | Lower the token limit to the reported value |
| matching `*-reset` header, when the remaining value is 0 | Pause until the reset |

Reset values may be seconds from now, an epoch timestamp, a duration such as `6m0s` or `20ms`,
an RFC 3339 timestamp or an HTTP-date.

| Parameter | Default | Description |
|---|---|---|
| `calls_limit` | `"calls"` | Name of the limit that counts requests (the primary limit) |
| `tokens_limit` | `"tokens"` | Name of the limit that counts tokens |
| `max_pause` | `60.0` | Upper bound in seconds for any pause |

Headers are matched case-insensitively, also in plain dicts. Missing or unparseable headers
are ignored, and the function never raises.

## Putting It Together for LLM APIs

For OpenAI/Anthropic-style clients that raise exceptions on 429 instead of returning responses,
attach the helpers to the exception side — `retry_after_delay` already understands exceptions
carrying a `.response` attribute:

```python
from pyresilience import resilient, RetryConfig, CircuitBreakerConfig
from pyresilience.contrib.http import retry_after_delay

@resilient(
    retry=RetryConfig(
        max_attempts=4,
        delay=1.0,
        retry_on=(RateLimitError, APIConnectionError),   # retryable
        ignore_on=(AuthenticationError, PermissionDeniedError),  # terminal: fail fast
        delay_func=retry_after_delay(max_wait=60.0),
    ),
    circuit_breaker=CircuitBreakerConfig(
        failure_threshold=5,
        ignore_on=(AuthenticationError, PermissionDeniedError),  # don't trip the circuit
    ),
)
def ask_model(prompt: str):
    return client.chat.completions.create(model="...", messages=[{"role": "user", "content": prompt}])
```

Or skip the wiring entirely with the [`llm_policy()`](presets.md#llm_policy) preset, which
combines all of the above with a client-side rate limiter:

```python
from pyresilience import resilient, llm_policy

@resilient(**llm_policy(ignore_on=(AuthenticationError,)))
def ask_model(prompt: str): ...
```

With token limits and server feedback:

```python
@resilient(**llm_policy(
    max_calls=60,                                   # requests per minute
    tokens_per_minute=90_000,
    token_cost=lambda prompt: len(prompt) // 4 + 256,          # estimate, reserved up front
    token_usage=lambda response: response.usage.total_tokens,  # settled after the call
    adaptive_rate_limit=True,                       # follow Retry-After and x-ratelimit-* headers
    rate_limit_max_wait=10.0,                       # wait up to 10s for capacity
))
def ask_model(prompt: str): ...
```
