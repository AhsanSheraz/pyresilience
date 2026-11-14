"""Tests for the result cache while the primary function is cooling down."""

from __future__ import annotations

from typing import Any

from pyresilience import (
    CacheConfig,
    EventType,
    FallbackConfig,
    ResilienceEvent,
    resilient,
)

COOLDOWN = {"cooldown": 30.0, "cooldown_threshold": 1}


class Backup:
    """An alternative that counts its calls."""

    __name__ = "backup"

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        return f"backup: {prompt}"


def _types(events: list[ResilienceEvent]) -> list[EventType]:
    return [event.event_type for event in events]


class TestCacheDuringCooldownSync:
    def test_cached_result_is_served_while_the_primary_cools_down(self) -> None:
        backup = Backup()
        events: list[ResilienceEvent] = []

        @resilient(
            cache=CacheConfig(),
            fallback=FallbackConfig(alternatives=[backup], **COOLDOWN),
            listeners=[events.append],
        )
        def primary(prompt: str) -> str:
            if prompt == "bad":
                raise ConnectionError("primary is down")
            return f"primary: {prompt}"

        assert primary("good") == "primary: good"
        assert primary("bad") == "backup: bad"  # the cooldown starts here
        events.clear()

        assert primary("good") == "primary: good"
        assert backup.calls == 1
        assert _types(events) == [EventType.CACHE_HIT]

    def test_uncached_call_goes_to_the_alternative(self) -> None:
        backup = Backup()
        events: list[ResilienceEvent] = []

        @resilient(
            cache=CacheConfig(),
            fallback=FallbackConfig(alternatives=[backup], **COOLDOWN),
            listeners=[events.append],
        )
        def primary(prompt: str) -> str:
            if prompt == "bad":
                raise ConnectionError("primary is down")
            return f"primary: {prompt}"

        assert primary("bad") == "backup: bad"
        events.clear()

        assert primary("new") == "backup: new"
        assert _types(events) == [EventType.CACHE_MISS, EventType.FALLBACK_USED]

    def test_works_without_listeners(self) -> None:
        backup = Backup()

        @resilient(cache=CacheConfig(), fallback=FallbackConfig(alternatives=[backup], **COOLDOWN))
        def primary(prompt: str) -> str:
            if prompt == "bad":
                raise ConnectionError("primary is down")
            return f"primary: {prompt}"

        assert primary("good") == "primary: good"
        assert primary("bad") == "backup: bad"
        assert primary("good") == "primary: good"
        assert primary("new") == "backup: new"
        assert backup.calls == 2

    def test_cache_is_checked_once_while_the_primary_is_healthy(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            cache=CacheConfig(),
            fallback=FallbackConfig(alternatives=[Backup()], **COOLDOWN),
            listeners=[events.append],
        )
        def primary(prompt: str) -> str:
            return f"primary: {prompt}"

        assert primary("good") == "primary: good"
        assert _types(events).count(EventType.CACHE_MISS) == 1


class TestCacheDuringCooldownAsync:
    async def test_cached_result_is_served_while_the_primary_cools_down(self) -> None:
        backup = Backup()
        events: list[ResilienceEvent] = []

        @resilient(
            cache=CacheConfig(),
            fallback=FallbackConfig(alternatives=[backup], **COOLDOWN),
            listeners=[events.append],
        )
        async def primary(prompt: str) -> str:
            if prompt == "bad":
                raise ConnectionError("primary is down")
            return f"primary: {prompt}"

        assert await primary("good") == "primary: good"
        assert await primary("bad") == "backup: bad"
        events.clear()

        assert await primary("good") == "primary: good"
        assert backup.calls == 1
        assert _types(events) == [EventType.CACHE_HIT]

    async def test_uncached_call_goes_to_the_alternative(self) -> None:
        backup = Backup()
        events: list[ResilienceEvent] = []

        @resilient(
            cache=CacheConfig(),
            fallback=FallbackConfig(alternatives=[backup], **COOLDOWN),
            listeners=[events.append],
        )
        async def primary(prompt: str) -> str:
            if prompt == "bad":
                raise ConnectionError("primary is down")
            return f"primary: {prompt}"

        assert await primary("bad") == "backup: bad"
        events.clear()

        assert await primary("new") == "backup: new"
        assert _types(events) == [EventType.CACHE_MISS, EventType.FALLBACK_USED]

    async def test_works_without_listeners(self) -> None:
        backup = Backup()

        @resilient(cache=CacheConfig(), fallback=FallbackConfig(alternatives=[backup], **COOLDOWN))
        async def primary(prompt: str) -> str:
            if prompt == "bad":
                raise ConnectionError("primary is down")
            return f"primary: {prompt}"

        assert await primary("good") == "primary: good"
        assert await primary("bad") == "backup: bad"
        assert await primary("good") == "primary: good"
        assert await primary("new") == "backup: new"
        assert backup.calls == 2

    async def test_cache_is_checked_once_while_the_primary_is_healthy(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            cache=CacheConfig(),
            fallback=FallbackConfig(alternatives=[Backup()], **COOLDOWN),
            listeners=[events.append],
        )
        async def primary(prompt: str) -> Any:
            return f"primary: {prompt}"

        assert await primary("good") == "primary: good"
        assert _types(events).count(EventType.CACHE_MISS) == 1
