"""Tests for resilience context propagation."""

from __future__ import annotations

import pytest

from pyresilience import EventType, ResilienceEvent, resilient
from pyresilience._logging import resilience_context
from pyresilience._types import RetryConfig


class TestContextPropagationSync:
    def test_context_included_in_events(self) -> None:
        """Setting resilience_context before a call includes context in emitted events."""
        events: list[ResilienceEvent] = []

        @resilient(retry=RetryConfig(max_attempts=1, delay=0.01), listeners=[events.append])
        def my_func() -> str:
            return "ok"

        token = resilience_context.set({"request_id": "abc-123", "trace_id": "xyz-789"})
        try:
            my_func()
        finally:
            resilience_context.reset(token)

        assert len(events) > 0
        for event in events:
            assert event.context == {"request_id": "abc-123", "trace_id": "xyz-789"}

    def test_events_have_none_context_when_not_set(self) -> None:
        """Events have context=None when resilience_context is not set."""
        events: list[ResilienceEvent] = []

        @resilient(retry=RetryConfig(max_attempts=1, delay=0.01), listeners=[events.append])
        def my_func() -> str:
            return "ok"

        # Ensure context is not set (reset to default)
        token = resilience_context.set(None)
        try:
            my_func()
        finally:
            resilience_context.reset(token)

        assert len(events) > 0
        for event in events:
            assert event.context is None

    def test_context_per_thread(self) -> None:
        """ContextVar semantics: each thread has its own context."""
        import threading

        events: list[ResilienceEvent] = []

        @resilient(retry=RetryConfig(max_attempts=1, delay=0.01), listeners=[events.append])
        def my_func() -> str:
            return "ok"

        def run_with_context(ctx: dict[str, str]) -> None:
            token = resilience_context.set(ctx)
            try:
                my_func()
            finally:
                resilience_context.reset(token)

        t1 = threading.Thread(target=run_with_context, args=({"thread": "1"},))
        t2 = threading.Thread(target=run_with_context, args=({"thread": "2"},))

        t1.start()
        t1.join()
        t2.start()
        t2.join()

        # Each thread should have produced events with its own context
        success_events = [e for e in events if e.event_type == EventType.SUCCESS]
        contexts = [e.context for e in success_events]
        assert {"thread": "1"} in contexts
        assert {"thread": "2"} in contexts

    def test_context_with_retry_events(self) -> None:
        """Context propagates to retry events as well."""
        events: list[ResilienceEvent] = []
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
            listeners=[events.append],
        )
        def my_func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "ok"

        token = resilience_context.set({"request_id": "retry-test"})
        try:
            my_func()
        finally:
            resilience_context.reset(token)

        retry_events = [e for e in events if e.event_type == EventType.RETRY]
        assert len(retry_events) > 0
        for event in retry_events:
            assert event.context == {"request_id": "retry-test"}


class TestContextPropagationAsync:
    @pytest.mark.asyncio
    async def test_async_context_included_in_events(self) -> None:
        """Setting resilience_context before an async call includes context in events."""
        events: list[ResilienceEvent] = []

        @resilient(retry=RetryConfig(max_attempts=1, delay=0.01), listeners=[events.append])
        async def my_func() -> str:
            return "ok"

        token = resilience_context.set({"request_id": "async-123"})
        try:
            await my_func()
        finally:
            resilience_context.reset(token)

        assert len(events) > 0
        for event in events:
            assert event.context == {"request_id": "async-123"}

    @pytest.mark.asyncio
    async def test_async_events_have_none_context_when_not_set(self) -> None:
        """Async events have context=None when resilience_context is not set."""
        events: list[ResilienceEvent] = []

        @resilient(retry=RetryConfig(max_attempts=1, delay=0.01), listeners=[events.append])
        async def my_func() -> str:
            return "ok"

        token = resilience_context.set(None)
        try:
            await my_func()
        finally:
            resilience_context.reset(token)

        assert len(events) > 0
        for event in events:
            assert event.context is None

    @pytest.mark.asyncio
    async def test_async_context_per_task(self) -> None:
        """ContextVar semantics: each asyncio task inherits parent context independently."""
        import asyncio

        events: list[ResilienceEvent] = []

        @resilient(retry=RetryConfig(max_attempts=1, delay=0.01), listeners=[events.append])
        async def my_func() -> str:
            return "ok"

        async def run_with_context(ctx: dict[str, str]) -> None:
            token = resilience_context.set(ctx)
            try:
                await my_func()
            finally:
                resilience_context.reset(token)

        await asyncio.gather(
            run_with_context({"task": "1"}),
            run_with_context({"task": "2"}),
        )

        success_events = [e for e in events if e.event_type == EventType.SUCCESS]
        contexts = [e.context for e in success_events]
        assert {"task": "1"} in contexts
        assert {"task": "2"} in contexts
