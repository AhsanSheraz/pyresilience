"""Tests for result cache."""

from __future__ import annotations

import time

from pyresilience._cache import _SENTINEL, AsyncResultCache, ResultCache
from pyresilience._types import CacheConfig


class TestResultCache:
    def test_cache_hit(self) -> None:
        config = CacheConfig(max_size=10, ttl=60.0)
        cache = ResultCache(config)
        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_cache_miss(self) -> None:
        config = CacheConfig(max_size=10, ttl=60.0)
        cache = ResultCache(config)
        assert cache.get("missing") is _SENTINEL

    def test_ttl_expiration(self) -> None:
        config = CacheConfig(max_size=10, ttl=0.05)
        cache = ResultCache(config)
        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"
        time.sleep(0.1)
        assert cache.get("key1") is _SENTINEL

    def test_no_ttl_expiration(self) -> None:
        config = CacheConfig(max_size=10, ttl=0)
        cache = ResultCache(config)
        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_lru_eviction(self) -> None:
        config = CacheConfig(max_size=2, ttl=60.0)
        cache = ResultCache(config)
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        cache.put("k3", "v3")  # Should evict k1
        assert cache.get("k1") is _SENTINEL
        assert cache.get("k2") == "v2"
        assert cache.get("k3") == "v3"

    def test_lru_access_updates_order(self) -> None:
        config = CacheConfig(max_size=2, ttl=60.0)
        cache = ResultCache(config)
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        cache.get("k1")  # Access k1, making k2 the LRU
        cache.put("k3", "v3")  # Should evict k2
        assert cache.get("k1") == "v1"
        assert cache.get("k2") is _SENTINEL
        assert cache.get("k3") == "v3"

    def test_invalidate(self) -> None:
        config = CacheConfig(max_size=10, ttl=60.0)
        cache = ResultCache(config)
        cache.put("key1", "value1")
        assert cache.invalidate("key1") is True
        assert cache.get("key1") is _SENTINEL
        assert cache.invalidate("key1") is False

    def test_clear(self) -> None:
        config = CacheConfig(max_size=10, ttl=60.0)
        cache = ResultCache(config)
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        cache.clear()
        assert cache.size == 0
        assert cache.get("k1") is _SENTINEL

    def test_size(self) -> None:
        config = CacheConfig(max_size=10, ttl=60.0)
        cache = ResultCache(config)
        assert cache.size == 0
        cache.put("k1", "v1")
        assert cache.size == 1

    def test_stats(self) -> None:
        config = CacheConfig(max_size=10, ttl=60.0)
        cache = ResultCache(config)
        cache.put("k1", "v1")
        cache.get("k1")  # hit
        cache.get("missing")  # miss
        stats = cache.stats
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5
        assert stats["size"] == 1
        assert stats["max_size"] == 10

    def test_stats_empty(self) -> None:
        config = CacheConfig(max_size=10, ttl=60.0)
        cache = ResultCache(config)
        stats = cache.stats
        assert stats["hit_rate"] == 0.0

    def test_make_key(self) -> None:
        key1 = ResultCache.make_key(1, "hello", x=10)
        key2 = ResultCache.make_key(1, "hello", x=10)
        key3 = ResultCache.make_key(1, "hello", x=20)
        assert key1 == key2
        assert key1 != key3

    def test_overwrite_existing_key(self) -> None:
        config = CacheConfig(max_size=10, ttl=60.0)
        cache = ResultCache(config)
        cache.put("k1", "v1")
        cache.put("k1", "v2")
        assert cache.get("k1") == "v2"
        assert cache.size == 1


class TestAsyncResultCache:
    def test_delegates_to_result_cache(self) -> None:
        config = CacheConfig(max_size=10, ttl=60.0)
        cache = AsyncResultCache(config)
        cache.put("k1", "v1")
        assert cache.get("k1") == "v1"
        assert cache.size == 1
        assert cache.invalidate("k1") is True
        assert cache.stats["misses"] == 0

    def test_clear(self) -> None:
        config = CacheConfig(max_size=10, ttl=60.0)
        cache = AsyncResultCache(config)
        cache.put("k1", "v1")
        cache.clear()
        assert cache.size == 0

    def test_make_key(self) -> None:
        key = AsyncResultCache.make_key(1, 2, a=3)
        assert isinstance(key, str)


class TestCacheIntegration:
    def test_sync_decorator_caches_result(self) -> None:
        from pyresilience import CacheConfig, resilient

        call_count = 0

        @resilient(cache=CacheConfig(max_size=10, ttl=60.0))
        def my_func(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2

        assert my_func(5) == 10
        assert my_func(5) == 10  # cached
        assert call_count == 1

        assert my_func(6) == 12  # different args, not cached
        assert call_count == 2

    async def test_async_decorator_caches_result(self) -> None:
        from pyresilience import CacheConfig, resilient

        call_count = 0

        @resilient(cache=CacheConfig(max_size=10, ttl=60.0))
        async def my_func(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2

        assert await my_func(5) == 10
        assert await my_func(5) == 10  # cached
        assert call_count == 1

    def test_cache_events_emitted(self) -> None:
        from pyresilience import CacheConfig, EventType, resilient
        from pyresilience._types import ResilienceEvent

        events: list[ResilienceEvent] = []

        @resilient(cache=CacheConfig(max_size=10, ttl=60.0), listeners=[events.append])
        def my_func(x: int) -> int:
            return x * 2

        my_func(5)
        my_func(5)

        event_types = [e.event_type for e in events]
        assert EventType.CACHE_MISS in event_types
        assert EventType.CACHE_HIT in event_types

    def test_cache_with_ttl_expiry(self) -> None:
        from pyresilience import CacheConfig, resilient

        call_count = 0

        @resilient(cache=CacheConfig(max_size=10, ttl=0.05))
        def my_func() -> str:
            nonlocal call_count
            call_count += 1
            return "result"

        my_func()
        assert call_count == 1
        my_func()  # cached
        assert call_count == 1
        time.sleep(0.1)
        my_func()  # expired, re-executes
        assert call_count == 2
