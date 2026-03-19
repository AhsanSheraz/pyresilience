"""Result cache — avoids redundant calls to slow backends."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pyresilience._types import CacheConfig

_SENTINEL = object()
_monotonic = time.monotonic


class ResultCache:
    """Thread-safe LRU result cache with TTL support.

    Uses OrderedDict for O(1) LRU eviction and monotonic clock for TTL.
    """

    __slots__ = ("_hits", "_lock", "_max_size", "_misses", "_store", "_ttl")

    def __init__(self, config: CacheConfig) -> None:
        self._max_size = config.max_size
        self._ttl = config.ttl
        self._lock = threading.Lock()
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def make_key(*args: Any, **kwargs: Any) -> str:
        """Create a cache key from function arguments."""
        parts = [repr(a) for a in args]
        parts.extend(f"{k}={v!r}" for k, v in sorted(kwargs.items()))
        return "|".join(parts)

    def get(self, key: str) -> Any:
        """Get a cached value. Returns _SENTINEL if not found or expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return _SENTINEL

            value, timestamp = entry
            if self._ttl > 0 and (_monotonic() - timestamp) > self._ttl:
                del self._store[key]
                self._misses += 1
                return _SENTINEL

            self._store.move_to_end(key)
            self._hits += 1
            return value

    def put(self, key: str, value: Any) -> None:
        """Store a value in the cache."""
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (value, _monotonic())

            # Evict oldest entries if over capacity
            while len(self._store) > self._max_size:
                self._store.popitem(last=False)

    def invalidate(self, key: str) -> bool:
        """Remove a specific key. Returns True if it existed."""
        with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    def clear(self) -> None:
        """Clear all cached entries and reset stats."""
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._store)

    @property
    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            return {
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": self._hits / total if total > 0 else 0.0,
                "size": len(self._store),
                "max_size": self._max_size,
            }


class AsyncResultCache:
    """Async-compatible result cache (delegates to thread-safe ResultCache)."""

    def __init__(self, config: CacheConfig) -> None:
        self._cache = ResultCache(config)

    @staticmethod
    def make_key(*args: Any, **kwargs: Any) -> str:
        return ResultCache.make_key(*args, **kwargs)

    def get(self, key: str) -> Any:
        return self._cache.get(key)

    def put(self, key: str, value: Any) -> None:
        self._cache.put(key, value)

    def invalidate(self, key: str) -> bool:
        return self._cache.invalidate(key)

    def clear(self) -> None:
        self._cache.clear()

    @property
    def size(self) -> int:
        return self._cache.size

    @property
    def stats(self) -> dict[str, Any]:
        return self._cache.stats
