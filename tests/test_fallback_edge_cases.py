"""Edge cases of the fallback router: streak after cooldown, last resort, call styles."""

from __future__ import annotations

import time
from typing import Any

import pytest

from pyresilience import EventType, FallbackConfig, ResilienceEvent, resilient
from pyresilience._fallback import _FallbackRouter


class TestStreakAfterCooldown:
    def test_threshold_counts_again_after_a_cooldown_expired(self) -> None:
        events: list[ResilienceEvent] = []
        attempts = 0

        def backup() -> str:
            return "backup"

        @resilient(
            fallback=FallbackConfig(alternatives=[backup], cooldown=0.2, cooldown_threshold=3),
            listeners=[events.append],
        )
        def primary() -> str:
            nonlocal attempts
            attempts += 1
            raise ConnectionError("down")

        for _ in range(3):
            primary()
        assert attempts == 3
        primary()  # cooling down: skipped
        assert attempts == 3

        time.sleep(0.3)
        primary()  # cooldown over: one failure does not start a new cooldown
        primary()
        assert attempts == 5
        cooldowns = [e for e in events if e.event_type == EventType.COOLDOWN]
        assert len(cooldowns) == 1
        state = primary._executor._router.state()  # type: ignore[attr-defined]
        assert state["primary"]["failures"] == 2

    async def test_threshold_counts_again_after_a_cooldown_expired_async(self) -> None:
        attempts = 0

        async def backup() -> str:
            return "backup"

        @resilient(
            fallback=FallbackConfig(alternatives=[backup], cooldown=0.2, cooldown_threshold=2)
        )
        async def primary() -> str:
            nonlocal attempts
            attempts += 1
            raise ConnectionError("down")

        await primary()
        await primary()
        await primary()  # skipped
        assert attempts == 2
        time.sleep(0.3)
        await primary()
        await primary()  # second failure after expiry starts the next cooldown
        await primary()  # skipped again
        assert attempts == 4


class TestCooldownNeverFailsACall:
    def test_primary_is_called_when_alternatives_vanish_sync(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        attempts = 0

        def backup() -> str:
            raise ConnectionError("backup down")

        @resilient(fallback=FallbackConfig(alternatives=[backup], cooldown=30.0))
        def primary() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("primary down")
            return "primary recovered"

        with pytest.raises(ConnectionError, match="backup down"):
            primary()
        # Simulate the race: the router decided to skip the primary, then found
        # every alternative cooling down
        monkeypatch.setattr(_FallbackRouter, "_skip_primary", lambda self: True)
        assert primary() == "primary recovered"
        assert attempts == 2
        state = primary._executor._router.state()  # type: ignore[attr-defined]
        assert state["primary"] == {"failures": 0, "cooling_for": 0.0}

    def test_last_resort_failure_is_recorded_and_raised_sync(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def backup() -> str:
            raise ConnectionError("backup down")

        @resilient(fallback=FallbackConfig(alternatives=[backup], cooldown=30.0))
        def primary() -> str:
            raise ConnectionError("primary down")

        with pytest.raises(ConnectionError, match="backup down"):
            primary()
        monkeypatch.setattr(_FallbackRouter, "_skip_primary", lambda self: True)
        with pytest.raises(ConnectionError, match="primary down"):
            primary()
        state = primary._executor._router.state()  # type: ignore[attr-defined]
        assert state["primary"]["failures"] == 2

    def test_last_resort_ineligible_error_is_raised_untouched_sync(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        attempts = 0

        def backup() -> str:
            raise ConnectionError("backup down")

        @resilient(
            fallback=FallbackConfig(
                alternatives=[backup], cooldown=30.0, fallback_on=(ConnectionError,)
            )
        )
        def primary() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("primary down")
            raise ValueError("bad request")

        with pytest.raises(ConnectionError):
            primary()
        monkeypatch.setattr(_FallbackRouter, "_skip_primary", lambda self: True)
        with pytest.raises(ValueError, match="bad request"):
            primary()
        state = primary._executor._router.state()  # type: ignore[attr-defined]
        assert state["primary"]["failures"] == 1

    async def test_primary_is_called_when_alternatives_vanish_async(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        attempts = 0

        async def backup() -> str:
            raise ConnectionError("backup down")

        @resilient(fallback=FallbackConfig(alternatives=[backup], cooldown=30.0))
        async def primary() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("primary down")
            return "primary recovered"

        with pytest.raises(ConnectionError, match="backup down"):
            await primary()
        monkeypatch.setattr(_FallbackRouter, "_skip_primary", lambda self: True)
        assert await primary() == "primary recovered"

    async def test_last_resort_failure_is_recorded_and_raised_async(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def backup() -> str:
            raise ConnectionError("backup down")

        @resilient(fallback=FallbackConfig(alternatives=[backup], cooldown=30.0))
        async def primary() -> str:
            raise ConnectionError("primary down")

        with pytest.raises(ConnectionError, match="backup down"):
            await primary()
        monkeypatch.setattr(_FallbackRouter, "_skip_primary", lambda self: True)
        with pytest.raises(ConnectionError, match="primary down"):
            await primary()

    async def test_last_resort_ineligible_error_is_raised_untouched_async(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        attempts = 0

        async def backup() -> str:
            raise ConnectionError("backup down")

        @resilient(
            fallback=FallbackConfig(
                alternatives=[backup], cooldown=30.0, fallback_on=(ConnectionError,)
            )
        )
        async def primary() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("primary down")
            raise ValueError("bad request")

        with pytest.raises(ConnectionError):
            await primary()
        monkeypatch.setattr(_FallbackRouter, "_skip_primary", lambda self: True)
        with pytest.raises(ValueError, match="bad request"):
            await primary()


class TestAlternativeCallStyle:
    def test_async_alternative_of_a_sync_function_is_an_error(self) -> None:
        async def async_backup(prompt: str) -> str:
            return "never awaited"

        @resilient(fallback=FallbackConfig(alternatives=[async_backup], handler="static"))
        def primary(prompt: str) -> str:
            raise ConnectionError("down")

        with pytest.raises(TypeError, match="async_backup returned an awaitable"):
            primary("hello")

    def test_awaitable_without_close_is_an_error_too(self) -> None:
        class Awaitable:
            def __await__(self) -> Any:
                yield

        def odd_backup(prompt: str) -> Any:
            return Awaitable()

        @resilient(fallback=FallbackConfig(alternatives=[odd_backup]))
        def primary(prompt: str) -> str:
            raise ConnectionError("down")

        with pytest.raises(TypeError, match="odd_backup returned an awaitable"):
            primary("hello")
