"""Tests for fallback functionality."""

from __future__ import annotations

import pytest

from pyresilience import EventType, FallbackConfig, ResilienceEvent, resilient


class TestFallbackSync:
    def test_static_fallback(self) -> None:
        @resilient(fallback=FallbackConfig(handler="default"))
        def fails() -> str:
            raise ValueError("boom")

        assert fails() == "default"

    def test_callable_fallback(self) -> None:
        @resilient(fallback=FallbackConfig(handler=lambda e: f"caught: {e}"))
        def fails() -> str:
            raise ValueError("boom")

        assert fails() == "caught: boom"

    def test_fallback_not_triggered_on_success(self) -> None:
        @resilient(fallback=FallbackConfig(handler="default"))
        def works() -> str:
            return "ok"

        assert works() == "ok"

    def test_fallback_on_specific_exception(self) -> None:
        @resilient(
            fallback=FallbackConfig(
                handler="fallback",
                fallback_on=(ValueError,),
            )
        )
        def fails_type_error() -> str:
            raise TypeError("wrong type")

        with pytest.raises(TypeError):
            fails_type_error()

    def test_fallback_event_emitted(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            fallback=FallbackConfig(handler="default"),
            listeners=[events.append],
        )
        def fails() -> str:
            raise ValueError("boom")

        fails()
        event_types = [e.event_type for e in events]
        assert EventType.FALLBACK_USED in event_types

    def test_none_handler_auto_clears_fallback_on(self) -> None:
        # handler=None auto-clears fallback_on to prevent silently returning None
        cfg = FallbackConfig(handler=None)
        assert cfg.handler is None
        assert cfg.fallback_on == ()

    def test_default_constructor_works(self) -> None:
        # FallbackConfig() should work without arguments
        cfg = FallbackConfig()
        assert cfg.handler is None
        assert cfg.fallback_on == ()

    def test_none_handler_with_explicit_fallback_on_clears(self) -> None:
        # handler=None always clears fallback_on to prevent silent None returns
        cfg = FallbackConfig(handler=None, fallback_on=(ValueError,))
        assert cfg.fallback_on == ()


class TestAsyncFallbackHandler:
    @pytest.mark.asyncio
    async def test_async_fallback_handler(self) -> None:
        """Async fallback handler is awaited in async context."""

        async def async_handler(exc: Exception) -> str:
            return f"async_caught: {exc}"

        @resilient(fallback=FallbackConfig(handler=async_handler))
        async def fails() -> str:
            raise ValueError("boom")

        result = await fails()
        assert result == "async_caught: boom"

    @pytest.mark.asyncio
    async def test_sync_handler_in_async_context(self) -> None:
        """Sync fallback handler still works in async context."""

        @resilient(fallback=FallbackConfig(handler=lambda e: "sync_fallback"))
        async def fails() -> str:
            raise ValueError("boom")

        assert await fails() == "sync_fallback"


class TestFallbackAsync:
    @pytest.mark.asyncio
    async def test_async_fallback(self) -> None:
        @resilient(fallback=FallbackConfig(handler="async_default"))
        async def fails() -> str:
            raise ValueError("boom")

        assert await fails() == "async_default"

    @pytest.mark.asyncio
    async def test_async_fallback_used_event(self) -> None:
        """Fallback_used event emitted in async."""
        events: list[ResilienceEvent] = []

        @resilient(
            fallback=FallbackConfig(handler="fallback_val"),
            listeners=[events.append],
        )
        async def fails() -> str:
            raise ValueError("fail")

        result = await fails()
        assert result == "fallback_val"
        event_types = [e.event_type for e in events]
        assert EventType.FALLBACK_USED in event_types
