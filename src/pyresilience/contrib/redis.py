"""Redis state backend for pyresilience.

Shares circuit breaker, rate limit and retry budget state between processes and
hosts. pyresilience does not import or depend on a Redis library: you pass in the
client you already use. Any client with redis-py's synchronous API works
(``redis.Redis``, ``valkey.Valkey``, ...).

Usage::

    import redis
    from redis.backoff import NoBackoff
    from redis.retry import Retry
    from pyresilience import RateLimiterConfig, SharedStateConfig, resilient
    from pyresilience.contrib.redis import RedisBackend

    # Rate-limited calls wait for this client: short timeouts, no retries of its own
    client = redis.Redis(
        host="localhost",
        port=6379,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
        retry=Retry(NoBackoff(), 0),
    )
    backend = RedisBackend(client)

    @resilient(
        rate_limiter=RateLimiterConfig(max_calls=100, period=60.0),
        shared_state=SharedStateConfig(backend=backend, key="payment-api"),
    )
    def charge(amount: float) -> dict:
        ...
"""

from __future__ import annotations

from typing import Any, Optional

__all__ = ["RedisBackend"]


class RedisBackend:
    """``StateBackend`` on top of a synchronous Redis client.

    Args:
        client: A redis-py compatible client. Only ``get``, ``set``,
            ``incrbyfloat``, ``pexpire``, ``delete`` and, when the client has
            it, ``pipeline`` are used.
        prefix: Prepended to every key so several applications can share one
            Redis database. Defaults to ``"pyresilience:"``.
    """

    __slots__ = ("_client", "_pipeline", "_prefix")

    def __init__(self, client: Any, prefix: str = "pyresilience:") -> None:
        self._client = client
        self._prefix = prefix
        # With a pipeline, increment and expiry travel in one round trip
        self._pipeline: Any = getattr(client, "pipeline", None)

    def get(self, key: str) -> Optional[str]:
        value: Any = self._client.get(self._prefix + key)
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    def set(self, key: str, value: str, ttl: Optional[float] = None) -> None:
        if ttl is not None:
            self._client.set(self._prefix + key, value, px=max(1, int(ttl * 1000)))
        else:
            self._client.set(self._prefix + key, value)

    def incr(self, key: str, amount: float, ttl: Optional[float] = None) -> float:
        # INCRBYFLOAT is atomic on the server, so concurrent callers are all counted
        full_key = self._prefix + key
        if ttl is None:
            return float(self._client.incrbyfloat(full_key, amount))
        expiry = max(1, int(ttl * 1000))
        if self._pipeline is None:
            total = float(self._client.incrbyfloat(full_key, amount))
            self._client.pexpire(full_key, expiry)
            return total
        pipe = self._pipeline(transaction=False)
        pipe.incrbyfloat(full_key, amount)
        pipe.pexpire(full_key, expiry)
        return float(pipe.execute()[0])

    def delete(self, key: str) -> None:
        self._client.delete(self._prefix + key)
