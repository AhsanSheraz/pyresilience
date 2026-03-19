"""Tests for event system."""

from __future__ import annotations

from pyresilience import EventType, ResilienceEvent, RetryConfig, resilient


class TestEventSystem:
    def test_listener_receives_all_events(self) -> None:
        events: list[ResilienceEvent] = []
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=2, delay=0.01),
            listeners=[events.append],
        )
        def fails_once() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("first fail")
            return "ok"

        fails_once()
        assert len(events) == 2  # RETRY + SUCCESS
        assert events[0].event_type == EventType.RETRY
        assert events[0].attempt == 1
        assert events[0].error is not None
        assert events[1].event_type == EventType.SUCCESS
        assert events[1].attempt == 2

    def test_event_has_function_name(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            retry=RetryConfig(max_attempts=1, delay=0.01),
            listeners=[events.append],
        )
        def my_function() -> str:
            return "ok"

        my_function()
        assert all(e.function_name == "my_function" for e in events)

    def test_listener_error_does_not_break_flow(self) -> None:
        def bad_listener(event: ResilienceEvent) -> None:
            raise RuntimeError("listener crash")

        @resilient(
            retry=RetryConfig(max_attempts=1, delay=0.01),
            listeners=[bad_listener],
        )
        def works() -> str:
            return "ok"

        assert works() == "ok"  # Should not raise

    def test_multiple_listeners(self) -> None:
        events_a: list[ResilienceEvent] = []
        events_b: list[ResilienceEvent] = []

        @resilient(
            retry=RetryConfig(max_attempts=1, delay=0.01),
            listeners=[events_a.append, events_b.append],
        )
        def works() -> str:
            return "ok"

        works()
        assert len(events_a) == 1
        assert len(events_b) == 1

    def test_event_frozen(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            retry=RetryConfig(max_attempts=1, delay=0.01),
            listeners=[events.append],
        )
        def works() -> str:
            return "ok"

        works()
        event = events[0]
        # ResilienceEvent is frozen dataclass
        with __import__("pytest").raises(AttributeError):
            event.event_type = EventType.FAILURE  # type: ignore[misc]

    def test_success_event_has_duration(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            retry=RetryConfig(max_attempts=1, delay=0.01),
            listeners=[events.append],
        )
        def works() -> str:
            return "ok"

        works()
        success = [e for e in events if e.event_type == EventType.SUCCESS]
        assert len(success) == 1
        assert success[0].duration is not None
        assert success[0].duration >= 0.0

    def test_success_event_duration_with_retry(self) -> None:
        events: list[ResilienceEvent] = []
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=2, delay=0.01),
            listeners=[events.append],
        )
        def fails_once() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("fail")
            return "ok"

        fails_once()
        success = [e for e in events if e.event_type == EventType.SUCCESS]
        assert len(success) == 1
        assert success[0].duration is not None
        assert success[0].duration >= 0.0
