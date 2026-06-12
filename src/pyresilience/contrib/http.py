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

import email.utils
import time
from typing import Any, Callable, Optional, Union

__all__ = ["retry_after_delay", "retry_on_status"]


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
