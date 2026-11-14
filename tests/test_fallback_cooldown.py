"""Tests for fallback alternatives and cooldown of failing targets (sync)."""

from __future__ import annotations

import threading
import time
from typing import Any, Iterator

import pytest

from pyresilience import (
    CircuitBreakerConfig,
    CircuitOpenError,
    EventType,
    FallbackConfig,
    ResilienceEvent,
    ResilienceTimeoutError,
    RetryConfig,
    TimeoutConfig,
    resilient,
)


class Provider:
    """A callable that counts calls and fails while ``failing`` is True."""

    def __init__(self, name: str, failing: bool = False) -> None:
        self.__name__ = name
        self.failing = failing
        self.calls = 0
        self.last_args: tuple[Any, ...] = ()
        self.last_kwargs: dict[str, Any] = {}

    def __call__(self, *args: Any, **kwargs: Any) -> str:
        self.calls += 1
        self.last_args = args
        self.last_kwargs = kwargs
        if self.failing:
            raise ConnectionError(f"{self.__name__} is down")
        return f"{self.__name__}: {args[0]}"


class TestAlternativesSync:
    def test_first_alternative_gets_the_original_arguments(self) -> None:
        backup = Provider("backup")
        events: list[ResilienceEvent] = []

        @resilient(fallback=FallbackConfig(alternatives=[backup]), listeners=[events.append])
        def primary(prompt: str, *, model: str = "a") -> str:
            raise ConnectionError("primary is down")

        assert primary("hello", model="b") == "backup: hello"
        assert backup.last_args == ("hello",)
        assert backup.last_kwargs == {"model": "b"}

        used = [e for e in events if e.event_type == EventType.FALLBACK_USED]
        assert len(used) == 1
        assert used[0].detail == "alternative backup"
        assert isinstance(used[0].error, ConnectionError)
        # The core reports the failure before the router falls back
        assert [e.event_type for e in events] == [EventType.FAILURE, EventType.FALLBACK_USED]

    def test_next_alternative_when_the_first_fails(self) -> None:
        first = Provider("first", failing=True)
        second = Provider("second")

        @resilient(fallback=FallbackConfig(alternatives=[first, second]))
        def primary(prompt: str) -> str:
            raise ConnectionError("primary is down")

        assert primary("hello") == "second: hello"
        assert first.calls == 1
        assert second.calls == 1

    def test_handler_runs_after_all_alternatives_fail(self) -> None:
        backup = Provider("backup", failing=True)
        events: list[ResilienceEvent] = []

        @resilient(
            fallback=FallbackConfig(alternatives=[backup], handler=lambda exc: f"handled: {exc}"),
            listeners=[events.append],
        )
        def primary(prompt: str) -> str:
            raise ConnectionError("primary is down")

        # The handler receives the last error of the chain
        assert primary("hello") == "handled: backup is down"
        assert events[-1].event_type == EventType.FALLBACK_USED
        assert events[-1].detail == ""

    def test_last_error_is_raised_without_a_handler(self) -> None:
        backup = Provider("backup", failing=True)

        @resilient(fallback=FallbackConfig(alternatives=[backup]))
        def primary(prompt: str) -> str:
            raise ConnectionError("primary is down")

        with pytest.raises(ConnectionError, match="backup is down"):
            primary("hello")

    def test_alternatives_are_not_called_on_success(self) -> None:
        backup = Provider("backup")

        @resilient(fallback=FallbackConfig(alternatives=[backup]))
        def primary(prompt: str) -> str:
            return f"primary: {prompt}"

        assert primary("hello") == "primary: hello"
        assert backup.calls == 0

    def test_errors_outside_fallback_on_are_raised(self) -> None:
        backup = Provider("backup")

        @resilient(fallback=FallbackConfig(alternatives=[backup], fallback_on=(ConnectionError,)))
        def primary(prompt: str) -> str:
            raise ValueError("bad request")

        with pytest.raises(ValueError, match="bad request"):
            primary("hello")
        assert backup.calls == 0

    def test_ineligible_error_from_an_alternative_propagates(self) -> None:
        def strict_backup(prompt: str) -> str:
            raise ValueError("backup rejects the request")

        @resilient(
            fallback=FallbackConfig(
                alternatives=[strict_backup], fallback_on=(ConnectionError,), handler="static"
            )
        )
        def primary(prompt: str) -> str:
            raise ConnectionError("primary is down")

        with pytest.raises(ValueError, match="backup rejects the request"):
            primary("hello")

    def test_retry_ignore_on_bypasses_the_chain(self) -> None:
        backup = Provider("backup")

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, ignore_on=(PermissionError,)),
            fallback=FallbackConfig(alternatives=[backup]),
        )
        def primary(prompt: str) -> str:
            raise PermissionError("invalid api key")

        with pytest.raises(PermissionError):
            primary("hello")
        assert backup.calls == 0

    def test_retries_run_before_alternatives(self) -> None:
        backup = Provider("backup")
        attempts = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
            fallback=FallbackConfig(alternatives=[backup]),
        )
        def primary(prompt: str) -> str:
            nonlocal attempts
            attempts += 1
            raise ConnectionError("primary is down")

        assert primary("hello") == "backup: hello"
        assert attempts == 3

    def test_open_circuit_routes_to_alternatives(self) -> None:
        backup = Provider("backup")
        attempts = 0

        @resilient(
            circuit_breaker=CircuitBreakerConfig(failure_threshold=1, recovery_timeout=60.0),
            fallback=FallbackConfig(alternatives=[backup], fallback_on=(ConnectionError,)),
        )
        def primary(prompt: str) -> str:
            nonlocal attempts
            attempts += 1
            raise ConnectionError("primary is down")

        assert primary("one") == "backup: one"
        # The circuit is open now: CircuitOpenError reaches the chain even though
        # it is not listed in fallback_on, exactly like the plain handler path
        assert primary("two") == "backup: two"
        assert attempts == 1

    def test_total_timeout_routes_to_alternatives(self) -> None:
        backup = Provider("backup")

        @resilient(
            retry=RetryConfig(max_attempts=5, delay=1.0, jitter=False),
            timeout=TimeoutConfig(seconds=1.0, total_seconds=0.2),
            fallback=FallbackConfig(alternatives=[backup], fallback_on=(ResilienceTimeoutError,)),
        )
        def primary(prompt: str) -> str:
            raise ConnectionError("primary is down")

        assert primary("hello") == "backup: hello"

    def test_alternative_can_be_a_resilient_function(self) -> None:
        attempts = 0

        @resilient(retry=RetryConfig(max_attempts=2, delay=0.01, jitter=False))
        def backup(prompt: str) -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("backup hiccup")
            return f"backup: {prompt}"

        @resilient(fallback=FallbackConfig(alternatives=[backup]))
        def primary(prompt: str) -> str:
            raise ConnectionError("primary is down")

        assert primary("hello") == "backup: hello"
        assert attempts == 2

    def test_streamed_alternative_result_gets_the_idle_timeout(self) -> None:
        def backup() -> Iterator[int]:
            yield 1
            time.sleep(3.0)
            yield 2

        @resilient(
            timeout=TimeoutConfig(seconds=1.0, stream_idle_seconds=0.5),
            fallback=FallbackConfig(alternatives=[backup]),
        )
        def primary() -> Iterator[int]:
            raise ConnectionError("primary is down")

        stream = primary()
        assert next(stream) == 1
        with pytest.raises(ResilienceTimeoutError):
            next(stream)

    def test_unnamed_callable_uses_its_type_name(self) -> None:
        class Backup:
            def __call__(self, prompt: str) -> str:
                return "ok"

        events: list[ResilienceEvent] = []

        @resilient(fallback=FallbackConfig(alternatives=[Backup()]), listeners=[events.append])
        def primary(prompt: str) -> str:
            raise ConnectionError("primary is down")

        assert primary("hello") == "ok"
        assert events[-1].detail == "alternative Backup"


class TestCooldownSync:
    def test_failing_primary_is_skipped_during_cooldown(self) -> None:
        backup = Provider("backup")
        events: list[ResilienceEvent] = []
        attempts = 0

        @resilient(
            fallback=FallbackConfig(alternatives=[backup], cooldown=30.0),
            listeners=[events.append],
        )
        def primary(prompt: str) -> str:
            nonlocal attempts
            attempts += 1
            raise ConnectionError("primary is down")

        assert primary("one") == "backup: one"
        assert primary("two") == "backup: two"
        assert primary("three") == "backup: three"
        # Only the first call reached the primary
        assert attempts == 1

        cooldowns = [e for e in events if e.event_type == EventType.COOLDOWN]
        assert len(cooldowns) == 1
        assert cooldowns[0].detail == "primary cooling down for 30.0s"
        assert isinstance(cooldowns[0].error, ConnectionError)

        state = primary._executor._router.state()  # type: ignore[attr-defined]
        assert state["primary"]["failures"] == 1
        assert 0 < state["primary"]["cooling_for"] <= 30.0
        assert state["backup"] == {"failures": 0, "cooling_for": 0.0}

    def test_threshold_counts_consecutive_failures(self) -> None:
        backup = Provider("backup")
        attempts = 0

        @resilient(
            fallback=FallbackConfig(alternatives=[backup], cooldown=30.0, cooldown_threshold=2)
        )
        def primary(prompt: str) -> str:
            nonlocal attempts
            attempts += 1
            raise ConnectionError("primary is down")

        primary("one")
        primary("two")
        primary("three")
        # Two failures start the cooldown; the third call skips the primary
        assert attempts == 2

    def test_success_resets_the_failure_streak(self) -> None:
        backup = Provider("backup")
        outcomes = [False, True, False, True]
        attempts = 0

        @resilient(
            fallback=FallbackConfig(alternatives=[backup], cooldown=30.0, cooldown_threshold=2)
        )
        def primary(prompt: str) -> str:
            nonlocal attempts
            attempts += 1
            if not outcomes.pop(0):
                raise ConnectionError("primary is down")
            return "primary"

        assert primary("one") == "backup: one"
        assert primary("two") == "primary"
        assert primary("three") == "backup: three"
        assert primary("four") == "primary"
        assert attempts == 4

    def test_primary_is_tried_again_after_cooldown(self) -> None:
        backup = Provider("backup")
        failing = True
        attempts = 0

        @resilient(fallback=FallbackConfig(alternatives=[backup], cooldown=0.2))
        def primary(prompt: str) -> str:
            nonlocal attempts
            attempts += 1
            if failing:
                raise ConnectionError("primary is down")
            return "primary"

        assert primary("one") == "backup: one"
        assert primary("two") == "backup: two"
        assert attempts == 1

        failing = False
        time.sleep(0.3)
        assert primary("three") == "primary"
        assert attempts == 2
        state = primary._executor._router.state()  # type: ignore[attr-defined]
        assert state["primary"] == {"failures": 0, "cooling_for": 0.0}

    def test_cooling_alternative_is_skipped(self) -> None:
        first = Provider("first", failing=True)
        second = Provider("second")
        events: list[ResilienceEvent] = []

        @resilient(
            fallback=FallbackConfig(alternatives=[first, second], cooldown=30.0),
            listeners=[events.append],
        )
        def primary(prompt: str) -> str:
            raise ConnectionError("primary is down")

        assert primary("one") == "second: one"
        assert primary("two") == "second: two"
        assert first.calls == 1
        assert second.calls == 2
        details = [e.detail for e in events if e.event_type == EventType.COOLDOWN]
        assert details == ["primary cooling down for 30.0s", "first cooling down for 30.0s"]

    def test_primary_is_called_when_nothing_else_is_available(self) -> None:
        backup = Provider("backup", failing=True)
        attempts = 0

        @resilient(fallback=FallbackConfig(alternatives=[backup], cooldown=30.0))
        def primary(prompt: str) -> str:
            nonlocal attempts
            attempts += 1
            raise ConnectionError("primary is down")

        with pytest.raises(ConnectionError, match="backup is down"):
            primary("one")
        # Primary and backup are both cooling down and there is no handler:
        # the cooldown must not turn into an outage of its own
        with pytest.raises(ConnectionError, match="primary is down"):
            primary("two")
        assert attempts == 2
        assert backup.calls == 1

    def test_handler_only_cooldown(self) -> None:
        seen: list[BaseException] = []
        attempts = 0

        def handler(exc: BaseException) -> str:
            seen.append(exc)
            return "cached answer"

        @resilient(fallback=FallbackConfig(handler=handler, cooldown=30.0))
        def primary(prompt: str) -> str:
            nonlocal attempts
            attempts += 1
            raise ConnectionError("primary is down")

        assert primary("one") == "cached answer"
        assert primary("two") == "cached answer"
        assert attempts == 1
        # While cooling down, the handler receives the error that started the cooldown
        assert seen[0] is seen[1]

    def test_cooldown_without_any_fallback_target_is_inert(self) -> None:
        @resilient(fallback=FallbackConfig(cooldown=30.0))
        def primary(prompt: str) -> str:
            raise ConnectionError("primary is down")

        assert primary._executor._router is None  # type: ignore[attr-defined]
        with pytest.raises(ConnectionError):
            primary("one")

    def test_no_cooldown_by_default(self) -> None:
        backup = Provider("backup")
        attempts = 0

        @resilient(fallback=FallbackConfig(alternatives=[backup]))
        def primary(prompt: str) -> str:
            nonlocal attempts
            attempts += 1
            raise ConnectionError("primary is down")

        primary("one")
        primary("two")
        assert attempts == 2

    def test_concurrent_callers_share_cooldown_state(self) -> None:
        backup = Provider("backup")
        attempts = 0
        lock = threading.Lock()

        @resilient(fallback=FallbackConfig(alternatives=[backup], cooldown=30.0))
        def primary(prompt: str) -> str:
            nonlocal attempts
            with lock:
                attempts += 1
            raise ConnectionError("primary is down")

        primary("warm-up")  # starts the cooldown
        results: list[str] = []

        def worker() -> None:
            for _ in range(25):
                value = primary("x")
                with lock:
                    results.append(value)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert results == ["backup: x"] * 100
        assert attempts == 1


class TestFallbackConfigValidation:
    def test_cooldown_must_not_be_negative(self) -> None:
        with pytest.raises(ValueError, match="cooldown must be >= 0"):
            FallbackConfig(handler="x", cooldown=-1)

    def test_cooldown_threshold_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="cooldown_threshold must be >= 1"):
            FallbackConfig(handler="x", cooldown_threshold=0)

    def test_alternatives_keep_fallback_on_without_a_handler(self) -> None:
        config = FallbackConfig(alternatives=[lambda: "ok"])
        assert config.fallback_on == (Exception,)

    def test_no_handler_and_no_alternatives_clears_fallback_on(self) -> None:
        assert FallbackConfig(cooldown=5.0).fallback_on == ()

    def test_circuit_open_error_reaches_a_plain_handler(self) -> None:
        @resilient(
            circuit_breaker=CircuitBreakerConfig(failure_threshold=1, recovery_timeout=60.0),
            fallback=FallbackConfig(handler=lambda exc: type(exc).__name__),
        )
        def primary() -> str:
            raise ConnectionError("primary is down")

        assert primary() == "ConnectionError"
        assert primary() == CircuitOpenError.__name__
