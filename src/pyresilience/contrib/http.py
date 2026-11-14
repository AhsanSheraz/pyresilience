"""HTTP resilience helpers for pyresilience.

Provides stdlib-only predicates and delay functions that integrate with
``RetryConfig.retry_on_result`` and ``RetryConfig.delay_func``. Works with
any HTTP client (requests, httpx, aiohttp) via duck-typing — no third-party
imports are required.

Usage::

    import email.utils
    import time
    from pyresilience import resilient, RetryConfig
    from pyresilience.contrib.http import retry_on_status, retry_after_delay

    @resilient(
        retry=RetryConfig(
            max_attempts=4,
            retry_on_result=retry_on_status(429, 503),
            delay_func=retry_after_delay(max_wait=120.0),
        )
    )
    def call_api() -> object:
        ...
"""

from __future__ import annotations

import datetime
import email.utils
import re
import time
from typing import Any, Callable, Optional, Sequence, Union

from pyresilience._types import PRIMARY_LIMIT_NAME, RateLimitFeedback

__all__ = ["rate_limit_feedback", "retry_after_delay", "retry_on_status"]


def retry_on_status(*codes: int) -> Callable[[Any], bool]:
    """Return a predicate that returns True when the response status is in *codes*.

    Suitable for ``RetryConfig.retry_on_result``. Works duck-typed with requests,
    httpx, and aiohttp responses by checking ``status_code`` then ``status``
    attributes.

    Args:
        *codes: HTTP status codes that should trigger a retry (e.g., 429, 503).

    Returns:
        A callable ``(obj) -> bool`` that returns ``True`` when the response
        status matches one of the supplied codes.

    Raises:
        ValueError: When called with no arguments.
        TypeError: When any argument is not an ``int`` or is a ``bool``.
    """
    if not codes:
        raise ValueError("retry_on_status requires at least one status code")
    for code in codes:
        # bool is a subclass of int — reject it explicitly
        if isinstance(code, bool) or not isinstance(code, int):
            raise TypeError(f"status codes must be int, got {type(code).__name__!r}: {code!r}")

    _code_set: frozenset[int] = frozenset(codes)

    def _predicate(obj: Any) -> bool:
        # Try requests/httpx attribute first, then aiohttp
        value: Any = getattr(obj, "status_code", None)
        if value is None:
            value = getattr(obj, "status", None)
        # Accept only real int values (not bool, not None, not str, …)
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        return value in _code_set

    return _predicate


# ---------------------------------------------------------------------------
# Private helpers for retry_after_delay
# ---------------------------------------------------------------------------


def _get_retry_after_header(trigger: Any) -> Optional[str]:
    """Extract the raw ``Retry-After`` header value from *trigger*.

    Tries ``trigger.headers`` first (httpx / direct response), then
    ``trigger.response.headers`` (requests ``HTTPError``-shaped exceptions).
    Returns ``None`` when no usable header is found.
    """
    headers: Any = None
    try:
        headers = getattr(trigger, "headers", None)
        if headers is None:
            response: Any = getattr(trigger, "response", None)
            if response is not None:
                headers = getattr(response, "headers", None)
    except Exception:
        return None

    if headers is None:
        return None

    # Case-insensitive lookup via the three most common spellings
    for key in ("Retry-After", "retry-after", "RETRY-AFTER"):
        try:
            value: Any = headers.get(key)
            if value is not None:
                return str(value)
        except Exception:
            continue

    return None


def _parse_retry_after(raw: str) -> Optional[float]:
    """Parse a raw ``Retry-After`` header into a delay in seconds.

    First attempts to parse *raw* as a delta-seconds integer/float. On failure,
    tries RFC 2822 HTTP-date arithmetic against the current wall-clock time.
    Returns ``None`` when neither form can be parsed.
    """
    # Delta-seconds form
    try:
        return float(raw)
    except (ValueError, TypeError):
        pass

    # HTTP-date form
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        delay = dt.timestamp() - time.time()
        return delay
    except Exception:
        return None


def retry_after_delay(
    max_wait: float = 60.0,
) -> Callable[[int, Union[BaseException, Any]], Optional[float]]:
    """Return a ``delay_func`` that honours the ``Retry-After`` response header.

    Suitable for ``RetryConfig.delay_func``. When the server returns a
    ``Retry-After`` header (delta-seconds or HTTP-date), the resolved delay is
    used; otherwise ``None`` is returned so pyresilience falls back to its own
    exponential back-off.

    The resolved value is clamped to ``[0.0, max_wait]``.

    Args:
        max_wait: Upper bound (seconds) for the delay. Defaults to 60.0.

    Returns:
        A callable ``(attempt, trigger) -> Optional[float]``.

    Raises:
        ValueError: When *max_wait* is <= 0.
    """
    if max_wait <= 0:
        raise ValueError("max_wait must be > 0")

    def _delay_func(attempt: int, trigger: Union[BaseException, Any]) -> Optional[float]:
        try:
            raw = _get_retry_after_header(trigger)
            if raw is None:
                return None
            delay = _parse_retry_after(raw)
            if delay is None:
                return None
            # Clamp to [0.0, max_wait]
            return max(0.0, min(delay, max_wait))
        except Exception:
            return None

    return _delay_func


# ---------------------------------------------------------------------------
# Rate-limit header feedback
# ---------------------------------------------------------------------------

# Header names, lower-case. First match wins.
_REMAINING_CALLS = (
    "x-ratelimit-remaining-requests",
    "anthropic-ratelimit-requests-remaining",
    "x-ratelimit-remaining",
    "ratelimit-remaining",
)
_RESET_CALLS = (
    "x-ratelimit-reset-requests",
    "anthropic-ratelimit-requests-reset",
    "x-ratelimit-reset",
    "ratelimit-reset",
)
_REMAINING_TOKENS = (
    "x-ratelimit-remaining-tokens",
    "anthropic-ratelimit-tokens-remaining",
)
_RESET_TOKENS = (
    "x-ratelimit-reset-tokens",
    "anthropic-ratelimit-tokens-reset",
)

# "6m0s", "1s", "20ms", "1h2m3.5s"
_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
_DURATION_UNITS = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}
# Numbers above this are absolute epoch timestamps, not seconds-from-now
_EPOCH_THRESHOLD = 1_000_000_000.0


def _get_headers(trigger: Any) -> Any:
    """Return the headers mapping of a response, or of an exception's response."""
    headers: Any = getattr(trigger, "headers", None)
    if headers is None:
        response: Any = getattr(trigger, "response", None)
        if response is not None:
            headers = getattr(response, "headers", None)
    return headers


def _first_header(headers: Any, names: Sequence[str]) -> Optional[str]:
    """Return the first header among *names* (lower-case), matched case-insensitively."""
    for name in names:
        value: Any = headers.get(name)
        if value is not None:
            return str(value)
    # Plain dicts are case-sensitive: fall back to a lower-cased scan
    items: Any = getattr(headers, "items", None)
    if items is None:
        return None
    lowered = {str(key).lower(): value for key, value in items()}
    for name in names:
        value = lowered.get(name)
        if value is not None:
            return str(value)
    return None


def _parse_number(raw: Optional[str]) -> Optional[float]:
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_reset(raw: Optional[str]) -> Optional[float]:
    """Parse a rate-limit reset header into seconds from now.

    Accepts seconds from now (``"30"``), an epoch timestamp in seconds or
    milliseconds, a duration (``"6m0s"``, ``"20ms"``), an RFC 3339 timestamp, or
    an HTTP-date. Returns None when the value cannot be parsed.
    """
    if raw is None:
        return None
    raw = raw.strip()
    number = _parse_number(raw)
    if number is not None:
        if number > _EPOCH_THRESHOLD * 1000:
            return max(0.0, number / 1000.0 - time.time())
        if number > _EPOCH_THRESHOLD:
            return max(0.0, number - time.time())
        return max(0.0, number)

    parts = _DURATION_PART.findall(raw)
    if parts and "".join(value + unit for value, unit in parts) == raw:
        return sum(float(value) * _DURATION_UNITS[unit] for value, unit in parts)

    try:
        moment = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            moment = email.utils.parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return max(0.0, moment.timestamp() - time.time())


def rate_limit_feedback(
    *,
    calls_limit: str = PRIMARY_LIMIT_NAME,
    tokens_limit: str = "tokens",
    max_pause: float = 60.0,
) -> Callable[[Any], Optional[RateLimitFeedback]]:
    """Return a ``feedback`` function that reads rate-limit headers.

    Suitable for ``RateLimiterConfig.feedback``. It inspects each attempt's
    response (or the response attached to a raised exception) and reports:

    - ``Retry-After`` (delta-seconds or HTTP-date): pause the limiter.
    - Remaining requests (``x-ratelimit-remaining-requests``,
      ``anthropic-ratelimit-requests-remaining``, ``x-ratelimit-remaining``,
      ``RateLimit-Remaining``): lower the ``calls_limit`` level.
    - Remaining tokens (``x-ratelimit-remaining-tokens``,
      ``anthropic-ratelimit-tokens-remaining``): lower the ``tokens_limit`` level.
    - When a remaining value is 0 and the matching reset header is present, pause
      until the reset.

    Works duck-typed with requests, httpx and aiohttp responses and with plain
    dict headers. Unparseable or missing headers are ignored.

    Args:
        calls_limit: Name of the limit that counts requests. Defaults to ``"calls"``,
            the primary limit.
        tokens_limit: Name of the limit that counts tokens. Defaults to ``"tokens"``.
        max_pause: Upper bound (seconds) for any pause. Defaults to 60.0.

    Returns:
        A callable ``(outcome) -> Optional[RateLimitFeedback]``.

    Raises:
        ValueError: When *max_pause* is <= 0.
    """
    if max_pause <= 0:
        raise ValueError("max_pause must be > 0")

    sources = (
        (calls_limit, _REMAINING_CALLS, _RESET_CALLS),
        (tokens_limit, _REMAINING_TOKENS, _RESET_TOKENS),
    )

    def _feedback(outcome: Any) -> Optional[RateLimitFeedback]:
        try:
            headers = _get_headers(outcome)
            if headers is None:
                return None

            pause: Optional[float] = None
            raw_retry_after = _first_header(headers, ("retry-after",))
            if raw_retry_after is not None:
                delay = _parse_retry_after(raw_retry_after)
                if delay is not None and delay > 0:
                    pause = delay

            remaining: dict[str, float] = {}
            for limit_name, remaining_names, reset_names in sources:
                left = _parse_number(_first_header(headers, remaining_names))
                if left is None:
                    continue
                remaining[limit_name] = left
                if left <= 0:
                    reset = _parse_reset(_first_header(headers, reset_names))
                    if reset is not None and reset > 0 and (pause is None or reset > pause):
                        pause = reset

            if pause is None and not remaining:
                return None
            if pause is not None and pause > max_pause:
                pause = max_pause
            return RateLimitFeedback(retry_after=pause, remaining=remaining or None)
        except Exception:
            return None

    return _feedback
