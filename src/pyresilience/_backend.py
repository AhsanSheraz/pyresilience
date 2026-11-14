"""State backends — where shared resilience state is stored.

A backend is a small key/value store with an atomic increment. The default is no
backend at all (every component keeps its state in process memory). Pass a backend
through ``SharedStateConfig`` to share circuit breaker, rate limit and retry budget
state between processes.

``InMemoryBackend`` lives here; a Redis backend that needs no extra dependency is
in ``pyresilience.contrib.redis``.
"""

from __future__ import annotations

import threading
import time
from typing import Optional, Protocol, runtime_checkable

_monotonic = time.monotonic
# InMemoryBackend looks for expired entries when it holds this many, and from then
# on each time it has doubled since the last look
_SWEEP_AT = 64


@runtime_checkable
class StateBackend(Protocol):
    """Storage interface for shared state.

    Implementations must be safe to call from several threads. ``incr`` must be
    atomic: two concurrent increments of the same key must both be counted.
    A ``ttl`` in seconds, when given, (re)starts the key's expiry.
    """

    def get(self, key: str) -> Optional[str]:
        """Return the value stored under *key*, or None when missing or expired."""
        ...

    def set(self, key: str, value: str, ttl: Optional[float] = None) -> None:
        """Store *value* under *key*."""
        ...

    def incr(self, key: str, amount: float, ttl: Optional[float] = None) -> float:
        """Atomically add *amount* to the number under *key* (0 when missing) and return it."""
        ...

    def delete(self, key: str) -> None:
        """Remove *key*. Missing keys are ignored."""
        ...


class InMemoryBackend:
    """Thread-safe ``StateBackend`` kept in process memory.

    Shares state between executors, registries and threads of one process, and
    stands in for a real backend in tests. It does not cross process boundaries.
    """

    __slots__ = ("_data", "_lock", "_sweep_at")

    def __init__(self) -> None:
        # key -> (value, expiry on the monotonic clock or None)
        self._data: dict[str, tuple[str, Optional[float]]] = {}
        self._lock = threading.Lock()
        self._sweep_at = _SWEEP_AT

    def _sweep(self) -> None:
        """Drop expired entries. The caller holds the lock.

        A key that is never read again (the counter of a past rate-limit window)
        would otherwise stay for ever.
        """
        now = _monotonic()
        data = self._data
        expired = [
            key
            for key, (_, expires_at) in data.items()
            if expires_at is not None and now >= expires_at
        ]
        for key in expired:
            del data[key]
        # Look again when the store has doubled: the cost per write stays constant
        self._sweep_at = max(_SWEEP_AT, 2 * len(data))

    def _live(self, key: str) -> Optional[str]:
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and _monotonic() >= expires_at:
            del self._data[key]
            return None
        return value

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            return self._live(key)

    def set(self, key: str, value: str, ttl: Optional[float] = None) -> None:
        with self._lock:
            self._data[key] = (value, _monotonic() + ttl if ttl is not None else None)
            if len(self._data) >= self._sweep_at:
                self._sweep()

    def incr(self, key: str, amount: float, ttl: Optional[float] = None) -> float:
        with self._lock:
            current = self._live(key)
            total = (float(current) if current is not None else 0.0) + amount
            if ttl is not None:
                expires_at: Optional[float] = _monotonic() + ttl
            else:
                entry = self._data.get(key)
                expires_at = entry[1] if entry is not None else None
            self._data[key] = (repr(total), expires_at)
            if len(self._data) >= self._sweep_at:
                self._sweep()
            return total

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def keys(self) -> list[str]:
        """Names of all live keys (handy when debugging)."""
        with self._lock:
            return [key for key in list(self._data) if self._live(key) is not None]
