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

    def test_none_fallback_handler_raises_validation_error(self) -> None:
        with pytest.raises(ValueError, match="requires a handler"):
            FallbackConfig(handler=None)

    def test_none_handler_allowed_with_empty_fallback_on(self) -> None:
        # handler=None is valid when fallback_on is empty (no triggers)
        cfg = FallbackConfig(handler=None, fallback_on=())
        assert cfg.handler is None


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
