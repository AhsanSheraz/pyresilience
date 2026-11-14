"""Tests for fallback alternatives and cooldown of failing targets (async)."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

import pytest

from pyresilience import (
    CircuitBreakerConfig,
    EventType,
    FallbackConfig,
    ResilienceEvent,
    ResilienceTimeoutError,
    RetryConfig,
    TimeoutConfig,
    resilient,
)


class AsyncProvider:
    """An async callable that counts calls and fails while ``failing`` is True."""

    def __init__(self, name: str, failing: bool = False) -> None:
        self.__name__ = name
        self.failing = failing
        self.calls = 0
        self.last_kwargs: dict[str, Any] = {}

    async def __call__(self, *args: Any, **kwargs: Any) -> str:
        self.calls += 1
        self.last_kwargs = kwargs
        if self.failing:
            raise ConnectionError(f"{self.__name__} is down")
        return f"{self.__name__}: {args[0]}"


class TestAlternativesAsync:
    async def test_first_alternative_gets_the_original_arguments(self) -> None:
        backup = AsyncProvider("backup")
        events: list[ResilienceEvent] = []

        @resilient(fallback=FallbackConfig(alternatives=[backup]), listeners=[events.append])
        async def primary(prompt: str, *, model: str = "a") -> str:
            raise ConnectionError("primary is down")

        assert await primary("hello", model="b") == "backup: hello"
        assert backup.last_kwargs == {"model": "b"}
        assert [e.event_type for e in events] == [EventType.FAILURE, EventType.FALLBACK_USED]
        assert events[-1].detail == "alternative backup"

    async def test_sync_alternative_is_allowed(self) -> None:
        def backup(prompt: str) -> str:
            return f"sync backup: {prompt}"

        @resilient(fallback=FallbackConfig(alternatives=[backup]))
        async def primary(prompt: str) -> str:
            raise ConnectionError("primary is down")

        assert await primary("hello") == "sync backup: hello"

    async def test_next_alternative_when_the_first_fails(self) -> None:
        first = AsyncProvider("first", failing=True)
        second = AsyncProvider("second")

        @resilient(fallback=FallbackConfig(alternatives=[first, second]))
        async def primary(prompt: str) -> str:
            raise ConnectionError("primary is down")

        assert await primary("hello") == "second: hello"
        assert first.calls == 1

    async def test_async_handler_runs_after_all_alternatives_fail(self) -> None:
        backup = AsyncProvider("backup", failing=True)
        events: list[ResilienceEvent] = []

        async def handler(exc: BaseException) -> str:
            return f"handled: {exc}"

        @resilient(
            fallback=FallbackConfig(alternatives=[backup], handler=handler),
            listeners=[events.append],
        )
        async def primary(prompt: str) -> str:
            raise ConnectionError("primary is down")

        assert await primary("hello") == "handled: backup is down"
        assert events[-1].event_type == EventType.FALLBACK_USED

    async def test_last_error_is_raised_without_a_handler(self) -> None:
        backup = AsyncProvider("backup", failing=True)

        @resilient(fallback=FallbackConfig(alternatives=[backup]))
        async def primary(prompt: str) -> str:
            raise ConnectionError("primary is down")

        with pytest.raises(ConnectionError, match="backup is down"):
            await primary("hello")

    async def test_alternatives_are_not_called_on_success(self) -> None:
        backup = AsyncProvider("backup")

        @resilient(fallback=FallbackConfig(alternatives=[backup]))
        async def primary(prompt: str) -> str:
            return f"primary: {prompt}"

        assert await primary("hello") == "primary: hello"
        assert backup.calls == 0

    async def test_errors_outside_fallback_on_are_raised(self) -> None:
        backup = AsyncProvider("backup")

        @resilient(fallback=FallbackConfig(alternatives=[backup], fallback_on=(ConnectionError,)))
        async def primary(prompt: str) -> str:
            raise ValueError("bad request")

        with pytest.raises(ValueError, match="bad request"):
            await primary("hello")
        assert backup.calls == 0

    async def test_ineligible_error_from_an_alternative_propagates(self) -> None:
        async def strict_backup(prompt: str) -> str:
            raise ValueError("backup rejects the request")

        @resilient(
            fallback=FallbackConfig(alternatives=[strict_backup], fallback_on=(ConnectionError,))
        )
        async def primary(prompt: str) -> str:
            raise ConnectionError("primary is down")

        with pytest.raises(ValueError, match="backup rejects the request"):
            await primary("hello")

    async def test_retries_run_before_alternatives(self) -> None:
        backup = AsyncProvider("backup")
        attempts = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
            fallback=FallbackConfig(alternatives=[backup]),
        )
        async def primary(prompt: str) -> str:
            nonlocal attempts
            attempts += 1
            raise ConnectionError("primary is down")

        assert await primary("hello") == "backup: hello"
        assert attempts == 3

    async def test_open_circuit_routes_to_alternatives(self) -> None:
        backup = AsyncProvider("backup")
        attempts = 0

        @resilient(
            circuit_breaker=CircuitBreakerConfig(failure_threshold=1, recovery_timeout=60.0),
            fallback=FallbackConfig(alternatives=[backup], fallback_on=(ConnectionError,)),
        )
        async def primary(prompt: str) -> str:
            nonlocal attempts
            attempts += 1
            raise ConnectionError("primary is down")

        assert await primary("one") == "backup: one"
        assert await primary("two") == "backup: two"
        assert attempts == 1

    async def test_streamed_alternative_result_gets_the_idle_timeout(self) -> None:
        async def chunks() -> AsyncIterator[int]:
            yield 1
            await asyncio.sleep(1.0)
            yield 2

        async def backup() -> AsyncIterator[int]:
            return chunks()

        @resilient(
            timeout=TimeoutConfig(seconds=1.0, stream_idle_seconds=0.1),
            fallback=FallbackConfig(alternatives=[backup]),
        )
        async def primary() -> AsyncIterator[int]:
            raise ConnectionError("primary is down")

        stream = await primary()
        assert await stream.__anext__() == 1
        with pytest.raises(ResilienceTimeoutError):
            await stream.__anext__()


class TestCooldownAsync:
    async def test_failing_primary_is_skipped_during_cooldown(self) -> None:
        backup = AsyncProvider("backup")
        events: list[ResilienceEvent] = []
        attempts = 0

        @resilient(
            fallback=FallbackConfig(alternatives=[backup], cooldown=30.0),
            listeners=[events.append],
        )
        async def primary(prompt: str) -> str:
            nonlocal attempts
            attempts += 1
            raise ConnectionError("primary is down")

        assert await primary("one") == "backup: one"
        assert await primary("two") == "backup: two"
        assert attempts == 1
        cooldowns = [e for e in events if e.event_type == EventType.COOLDOWN]
        assert len(cooldowns) == 1
        assert cooldowns[0].detail == "primary cooling down for 30.0s"

    async def test_primary_is_tried_again_after_cooldown(self) -> None:
        backup = AsyncProvider("backup")
        failing = True
        attempts = 0

        @resilient(fallback=FallbackConfig(alternatives=[backup], cooldown=0.2))
        async def primary(prompt: str) -> str:
            nonlocal attempts
            attempts += 1
            if failing:
                raise ConnectionError("primary is down")
            return "primary"

        assert await primary("one") == "backup: one"
        assert await primary("two") == "backup: two"
        assert attempts == 1

        failing = False
        await asyncio.sleep(0.3)
        assert await primary("three") == "primary"
        state = primary._executor._router.state()  # type: ignore[attr-defined]
        assert state["primary"] == {"failures": 0, "cooling_for": 0.0}

    async def test_cooling_alternative_is_skipped(self) -> None:
        first = AsyncProvider("first", failing=True)
        second = AsyncProvider("second")

        @resilient(fallback=FallbackConfig(alternatives=[first, second], cooldown=30.0))
        async def primary(prompt: str) -> str:
            raise ConnectionError("primary is down")

        assert await primary("one") == "second: one"
        assert await primary("two") == "second: two"
        assert first.calls == 1
        assert second.calls == 2

    async def test_alternative_recovers_after_success(self) -> None:
        backup = AsyncProvider("backup", failing=True)

        @resilient(
            fallback=FallbackConfig(
                alternatives=[backup], handler="static", cooldown=30.0, cooldown_threshold=3
            )
        )
        async def primary(prompt: str) -> str:
            raise ConnectionError("primary is down")

        assert await primary("one") == "static"
        backup.failing = False
        assert await primary("two") == "backup: two"
        state = primary._executor._router.state()  # type: ignore[attr-defined]
        assert state["backup"]["failures"] == 0

    async def test_primary_is_called_when_nothing_else_is_available(self) -> None:
        backup = AsyncProvider("backup", failing=True)
        attempts = 0

        @resilient(fallback=FallbackConfig(alternatives=[backup], cooldown=30.0))
        async def primary(prompt: str) -> str:
            nonlocal attempts
            attempts += 1
            raise ConnectionError("primary is down")

        with pytest.raises(ConnectionError, match="backup is down"):
            await primary("one")
        with pytest.raises(ConnectionError, match="primary is down"):
            await primary("two")
        assert attempts == 2

    async def test_handler_only_cooldown(self) -> None:
        attempts = 0

        @resilient(fallback=FallbackConfig(handler="cached answer", cooldown=30.0))
        async def primary(prompt: str) -> str:
            nonlocal attempts
            attempts += 1
            raise ConnectionError("primary is down")

        assert await primary("one") == "cached answer"
        assert await primary("two") == "cached answer"
        assert attempts == 1

    async def test_concurrent_callers_share_cooldown_state(self) -> None:
        backup = AsyncProvider("backup")
        attempts = 0

        @resilient(fallback=FallbackConfig(alternatives=[backup], cooldown=30.0))
        async def primary(prompt: str) -> str:
            nonlocal attempts
            attempts += 1
            raise ConnectionError("primary is down")

        await primary("warm-up")
        results = await asyncio.gather(*(primary("x") for _ in range(50)))
        assert results == ["backup: x"] * 50
        assert attempts == 1
