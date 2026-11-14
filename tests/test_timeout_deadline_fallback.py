"""Tests for fallbacks when the overall deadline stops the retries."""

from __future__ import annotations

from typing import Any

import pytest

from pyresilience import (
    EventType,
    FallbackConfig,
    ResilienceEvent,
    ResilienceTimeoutError,
    RetryConfig,
    TimeoutConfig,
    resilient,
)
from pyresilience._fallback import _fallback_match

# The first retry wait (1s) never fits into the deadline, so the retries stop at once
RETRY = RetryConfig(max_attempts=3, delay=1.0, jitter=False)
DEADLINE = TimeoutConfig(seconds=5.0, total_seconds=0.5)


def _name(exc: BaseException) -> str:
    return f"fallback: {type(exc).__name__}"


def _backup(*args: Any, **kwargs: Any) -> str:
    return "backup"


class TestFallbackMatch:
    def test_error_itself_matches(self) -> None:
        error = ConnectionError("down")
        assert _fallback_match(error, (ConnectionError,)) is error

    def test_retried_error_behind_a_deadline_matches(self) -> None:
        cause = ConnectionError("down")
        error = ResilienceTimeoutError("deadline")
        error.__cause__ = cause
        assert _fallback_match(error, (ConnectionError,)) is cause

    def test_timeout_wins_when_it_matches_itself(self) -> None:
        error = ResilienceTimeoutError("deadline")
        error.__cause__ = ConnectionError("down")
        assert _fallback_match(error, (Exception,)) is error

    def test_cause_of_another_error_does_not_match(self) -> None:
        error = ValueError("bad")
        error.__cause__ = ConnectionError("down")
        assert _fallback_match(error, (ConnectionError,)) is None

    def test_timeout_without_a_cause_does_not_match(self) -> None:
        assert _fallback_match(ResilienceTimeoutError("slow"), (ConnectionError,)) is None

    def test_unrelated_cause_does_not_match(self) -> None:
        error = ResilienceTimeoutError("deadline")
        error.__cause__ = KeyError("x")
        assert _fallback_match(error, (ConnectionError,)) is None


class TestDeadlineFallbackSync:
    def test_fallback_for_the_retried_error_still_applies(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            retry=RETRY,
            timeout=DEADLINE,
            fallback=FallbackConfig(handler=_name, fallback_on=(ConnectionError,)),
            listeners=[events.append],
        )
        def call() -> str:
            raise ConnectionError("down")

        # The handler gets the error it was configured for
        assert call() == "fallback: ConnectionError"
        used = [e for e in events if e.event_type == EventType.FALLBACK_USED]
        assert len(used) == 1
        assert isinstance(used[0].error, ResilienceTimeoutError)

    def test_fallback_for_the_timeout_gets_the_timeout(self) -> None:
        @resilient(
            retry=RETRY,
            timeout=DEADLINE,
            fallback=FallbackConfig(handler=_name, fallback_on=(ResilienceTimeoutError,)),
        )
        def call() -> str:
            raise ConnectionError("down")

        assert call() == "fallback: ResilienceTimeoutError"

    def test_unrelated_fallback_is_not_used(self) -> None:
        @resilient(
            retry=RETRY,
            timeout=DEADLINE,
            fallback=FallbackConfig(handler=_name, fallback_on=(KeyError,)),
        )
        def call() -> str:
            raise ConnectionError("down")

        with pytest.raises(ResilienceTimeoutError, match="total timeout budget") as info:
            call()
        assert isinstance(info.value.__cause__, ConnectionError)

    def test_alternative_takes_the_call(self) -> None:
        @resilient(
            retry=RETRY,
            timeout=DEADLINE,
            fallback=FallbackConfig(alternatives=[_backup], fallback_on=(ConnectionError,)),
        )
        def call() -> str:
            raise ConnectionError("down")

        assert call() == "backup"

    def test_router_handler_gets_the_retried_error(self) -> None:
        @resilient(
            retry=RETRY,
            timeout=DEADLINE,
            fallback=FallbackConfig(handler=_name, fallback_on=(ConnectionError,), cooldown=30.0),
        )
        def call() -> str:
            raise ConnectionError("down")

        assert call() == "fallback: ConnectionError"

    def test_router_leaves_an_unrelated_error_alone(self) -> None:
        @resilient(
            retry=RETRY,
            timeout=DEADLINE,
            fallback=FallbackConfig(alternatives=[_backup], fallback_on=(KeyError,)),
        )
        def call() -> str:
            raise ConnectionError("down")

        with pytest.raises(ResilienceTimeoutError, match="total timeout budget"):
            call()


class TestDeadlineFallbackAsync:
    async def test_fallback_for_the_retried_error_still_applies(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            retry=RETRY,
            timeout=DEADLINE,
            fallback=FallbackConfig(handler=_name, fallback_on=(ConnectionError,)),
            listeners=[events.append],
        )
        async def call() -> str:
            raise ConnectionError("down")

        assert await call() == "fallback: ConnectionError"
        used = [e for e in events if e.event_type == EventType.FALLBACK_USED]
        assert len(used) == 1
        assert isinstance(used[0].error, ResilienceTimeoutError)

    async def test_fallback_for_the_timeout_gets_the_timeout(self) -> None:
        @resilient(
            retry=RETRY,
            timeout=DEADLINE,
            fallback=FallbackConfig(handler=_name, fallback_on=(ResilienceTimeoutError,)),
        )
        async def call() -> str:
            raise ConnectionError("down")

        assert await call() == "fallback: ResilienceTimeoutError"

    async def test_unrelated_fallback_is_not_used(self) -> None:
        @resilient(
            retry=RETRY,
            timeout=DEADLINE,
            fallback=FallbackConfig(handler=_name, fallback_on=(KeyError,)),
        )
        async def call() -> str:
            raise ConnectionError("down")

        with pytest.raises(ResilienceTimeoutError, match="total timeout budget") as info:
            await call()
        assert isinstance(info.value.__cause__, ConnectionError)

    async def test_alternative_takes_the_call(self) -> None:
        @resilient(
            retry=RETRY,
            timeout=DEADLINE,
            fallback=FallbackConfig(alternatives=[_backup], fallback_on=(ConnectionError,)),
        )
        async def call() -> str:
            raise ConnectionError("down")

        assert await call() == "backup"

    async def test_router_handler_gets_the_retried_error(self) -> None:
        @resilient(
            retry=RETRY,
            timeout=DEADLINE,
            fallback=FallbackConfig(handler=_name, fallback_on=(ConnectionError,), cooldown=30.0),
        )
        async def call() -> str:
            raise ConnectionError("down")

        assert await call() == "fallback: ConnectionError"

    async def test_router_leaves_an_unrelated_error_alone(self) -> None:
        @resilient(
            retry=RETRY,
            timeout=DEADLINE,
            fallback=FallbackConfig(alternatives=[_backup], fallback_on=(KeyError,)),
        )
        async def call() -> str:
            raise ConnectionError("down")

        with pytest.raises(ResilienceTimeoutError, match="total timeout budget"):
            await call()
