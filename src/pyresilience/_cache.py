"""Result cache — avoids redundant calls to slow backends."""

from __future__ import annotations

import asyncio
import threading
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pyresilience._types import CacheConfig

_SENTINEL = object()
_monotonic = time.monotonic


def _make_cache_key(*args: Any, **kwargs: Any) -> Any:
    """Create a cache key from function arguments.

    Fast path: when all args are hashable and no kwargs, use the args tuple
    directly (tuple hashing is much faster than string building + repr).
    Falls back to type-qualified string key for unhashable args or kwargs.
    """
    if not kwargs:
        try:
            hash(args)
            return args
        except TypeError:
            pass
    parts = [f"{type(a).__qualname__}:{a!r}" for a in args]
    parts.extend(f"{k}={type(v).__qualname__}:{v!r}" for k, v in sorted(kwargs.items()))
    return "|".join(parts)


class ResultCache:
    """Thread-safe LRU result cache with TTL support.

    Uses OrderedDict for O(1) LRU eviction and monotonic clock for TTL.
    """

    __slots__ = (
        "_hits",
        "_key_locks",
        "_key_locks_lock",
        "_lock",
        "_max_size",
        "_misses",
        "_store",
        "_ttl",
    )

    def __init__(self, config: CacheConfig) -> None:
        self._max_size = config.max_size
        self._ttl = config.ttl
        self._lock = threading.Lock()
        self._store: OrderedDict[Any, tuple[Any, float]] = OrderedDict()
        self._hits = 0
        self._misses = 0
        # Per-key locks for cache stampede prevention (single-flight)
        self._key_locks: dict[Any, threading.Lock] = {}
        self._key_locks_lock = threading.Lock()

    @staticmethod
    def make_key(*args: Any, **kwargs: Any) -> Any:
        """Create a cache key from function arguments."""
        return _make_cache_key(*args, **kwargs)

    def get(self, key: Any) -> Any:
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
                # Clean up the lock for the expired key
                with self._key_locks_lock:
                    self._key_locks.pop(key, None)
                return _SENTINEL

            self._store.move_to_end(key)
            self._hits += 1
            return value

    def put(self, key: Any, value: Any) -> list[Any]:
        """Store a value in the cache. Returns list of evicted keys (if any)."""
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (value, _monotonic())

            # Evict oldest entries if over capacity
            evicted_keys: list[Any] = []
            while len(self._store) > self._max_size:
                evicted_key, _ = self._store.popitem(last=False)
                evicted_keys.append(evicted_key)

            # Clean up locks for evicted keys
            if evicted_keys:
                with self._key_locks_lock:
                    for evicted_key in evicted_keys:
                        self._key_locks.pop(evicted_key, None)

            return evicted_keys

    def invalidate(self, key: Any) -> bool:
        """Remove a specific key. Returns True if it existed."""
        with self._lock:
            if key in self._store:
                del self._store[key]
                # Clean up the lock for the invalidated key
                with self._key_locks_lock:
                    self._key_locks.pop(key, None)
                return True
            return False

    def get_key_lock(self, key: Any) -> threading.Lock:
        """Get a per-key lock for cache stampede prevention."""
        with self._key_locks_lock:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._key_locks[key] = lock
            return lock

    def clear(self) -> None:
        """Clear all cached entries and reset stats."""
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0
        with self._key_locks_lock:
            self._key_locks.clear()

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
        # Per-key async locks for cache stampede prevention
        self._async_key_locks: dict[Any, asyncio.Lock] = {}
        self._async_key_locks_lock = threading.Lock()

    @staticmethod
    def make_key(*args: Any, **kwargs: Any) -> Any:
        return ResultCache.make_key(*args, **kwargs)

    def get(self, key: Any) -> Any:
        result = self._cache.get(key)
        # If TTL expired and key was removed, also clean up async lock
        if result is _SENTINEL and key not in self._cache._store:
            with self._async_key_locks_lock:
                self._async_key_locks.pop(key, None)
        return result

    def put(self, key: Any, value: Any) -> None:
        evicted_keys = self._cache.put(key, value)
        if evicted_keys:
            with self._async_key_locks_lock:
                for evicted_key in evicted_keys:
                    self._async_key_locks.pop(evicted_key, None)

    def invalidate(self, key: Any) -> bool:
        result = self._cache.invalidate(key)
        # Clean up async lock if key was removed
        if result:
            with self._async_key_locks_lock:
                self._async_key_locks.pop(key, None)
        return result

    def get_async_key_lock(self, key: Any) -> asyncio.Lock:
        """Get a per-key async lock for cache stampede prevention."""
        with self._async_key_locks_lock:
            lock = self._async_key_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._async_key_locks[key] = lock
            return lock

    def clear(self) -> None:
        self._cache.clear()
        with self._async_key_locks_lock:
            self._async_key_locks.clear()

    @property
    def size(self) -> int:
        return self._cache.size

    @property
    def stats(self) -> dict[str, Any]:
        return self._cache.stats
