"""Tests for circuit breaker state shared between instances through a StateBackend.

Two decorated functions with separate SharedStateConfig objects stand in for two
processes. sync_interval=0 disables the background thread, so every pass is
triggered explicitly with sync_now() and the tests are deterministic.
"""

from __future__ import annotations

import time
from typing import Any, Callable

import pytest

from pyresilience import (
    CircuitBreakerConfig,
    CircuitOpenError,
    CircuitState,
    InMemoryBackend,
    SharedStateConfig,
    resilient,
)

OPEN_KEY = "svc:cb:open"
FAILS_KEY = "svc:cb:fails"


class Instance:
    """One 'process': a resilient function plus its shared-state config."""

    def __init__(self, backend: Any, **breaker: Any) -> None:
        self.failing = True
        self.shared = SharedStateConfig(backend=backend, key="svc", sync_interval=0)

        @resilient(circuit_breaker=CircuitBreakerConfig(**breaker), shared_state=self.shared)
        def call() -> str:
            if self.failing:
                raise ConnectionError("down")
            return "ok"

        self.call: Callable[[], str] = call
        self.breaker = call._executor._circuit_breaker  # type: ignore[attr-defined]

    def fail(self, times: int = 1) -> None:
        for _ in range(times):
            with pytest.raises(ConnectionError):
                self.call()

    def sync(self) -> None:
        self.shared.sync_now()


class TestOpenStateIsShared:
    def test_open_circuit_propagates_to_the_other_instance(self) -> None:
        backend = InMemoryBackend()
        a = Instance(backend, failure_threshold=2, recovery_timeout=60.0)
        b = Instance(backend, failure_threshold=2, recovery_timeout=60.0)

        a.fail(2)
        assert a.breaker.state is CircuitState.OPEN
        assert b.breaker.state is CircuitState.CLOSED

        a.sync()
        assert backend.get(OPEN_KEY) is not None
        b.sync()
        assert b.breaker.state is CircuitState.OPEN
        with pytest.raises(CircuitOpenError):
            b.call()

    def test_instances_recover_at_the_same_moment(self) -> None:
        backend = InMemoryBackend()
        a = Instance(backend, failure_threshold=1, recovery_timeout=0.3, success_threshold=1)
        b = Instance(backend, failure_threshold=1, recovery_timeout=0.3, success_threshold=1)

        a.fail()
        a.sync()
        b.sync()
        assert b.breaker.state is CircuitState.OPEN

        time.sleep(0.4)
        assert a.breaker.state is CircuitState.HALF_OPEN
        assert b.breaker.state is CircuitState.HALF_OPEN

        # A successful probe closes b and clears the shared record
        b.failing = False
        assert b.call() == "ok"
        assert b.breaker.state is CircuitState.CLOSED
        b.sync()
        assert backend.get(OPEN_KEY) is None

    def test_adopted_open_is_not_published_again(self) -> None:
        backend = InMemoryBackend()
        a = Instance(backend, failure_threshold=1, recovery_timeout=60.0)
        b = Instance(backend, failure_threshold=1, recovery_timeout=60.0)

        a.fail()
        a.sync()
        published = backend.get(OPEN_KEY)
        b.sync()
        b.sync()
        # b only adopted the record; it must not extend it
        assert backend.get(OPEN_KEY) == published

    def test_failed_probe_reopens_everywhere(self) -> None:
        backend = InMemoryBackend()
        a = Instance(backend, failure_threshold=1, recovery_timeout=0.2, success_threshold=1)
        b = Instance(backend, failure_threshold=1, recovery_timeout=0.2, success_threshold=1)

        a.fail()
        a.sync()
        b.sync()
        time.sleep(0.3)

        # a closes after a good probe; b's probe fails and reopens the circuit
        a.failing = False
        assert a.call() == "ok"
        a.sync()
        assert a.breaker.state is CircuitState.CLOSED
        b.fail()
        assert b.breaker.state is CircuitState.OPEN
        b.sync()
        a.sync()
        assert a.breaker.state is CircuitState.OPEN

    def test_manual_reset_clears_the_shared_record(self) -> None:
        backend = InMemoryBackend()
        a = Instance(backend, failure_threshold=1, recovery_timeout=60.0)

        a.fail()
        a.sync()
        assert backend.get(OPEN_KEY) is not None
        a.breaker.reset()
        a.sync()
        assert backend.get(OPEN_KEY) is None
        assert a.breaker.state is CircuitState.CLOSED

    def test_expired_record_is_ignored(self) -> None:
        backend = InMemoryBackend()
        backend.set(OPEN_KEY, repr(time.time() - 10))
        b = Instance(backend, failure_threshold=1, recovery_timeout=60.0)
        b.sync()
        assert b.breaker.state is CircuitState.CLOSED

    def test_malformed_record_is_ignored(self) -> None:
        backend = InMemoryBackend()
        backend.set(OPEN_KEY, "not a timestamp")
        b = Instance(backend, failure_threshold=1, recovery_timeout=60.0)
        b.sync()
        assert b.breaker.state is CircuitState.CLOSED

    def test_remaining_time_is_capped_by_the_local_recovery_timeout(self) -> None:
        backend = InMemoryBackend()
        # A record far in the future, as a host with a fast clock might write it
        backend.set(OPEN_KEY, repr(time.time() + 3600))
        b = Instance(backend, failure_threshold=1, recovery_timeout=0.2)
        b.sync()
        assert b.breaker.state is CircuitState.OPEN
        time.sleep(0.3)
        assert b.breaker.state is CircuitState.HALF_OPEN

    def test_open_that_already_recovered_is_not_published(self) -> None:
        backend = InMemoryBackend()
        a = Instance(backend, failure_threshold=1, recovery_timeout=0.05)
        a.fail()
        time.sleep(0.1)  # the open window passed before the first sync
        a.sync()
        assert backend.get(OPEN_KEY) is None

    def test_sliding_window_mode_shares_only_the_open_state(self) -> None:
        backend = InMemoryBackend()
        window = {
            "sliding_window_size": 4,
            "failure_rate_threshold": 0.5,
            "minimum_calls": 4,
            "recovery_timeout": 60.0,
        }
        a = Instance(backend, **window)
        b = Instance(backend, **window)

        a.fail(4)
        assert a.breaker.state is CircuitState.OPEN
        a.sync()
        assert backend.get(FAILS_KEY) is None  # no failure streak in rate mode
        b.sync()
        assert b.breaker.state is CircuitState.OPEN


class TestFailureStreakIsShared:
    def test_failures_of_all_instances_add_up(self) -> None:
        backend = InMemoryBackend()
        a = Instance(backend, failure_threshold=4, recovery_timeout=60.0)
        b = Instance(backend, failure_threshold=4, recovery_timeout=60.0)

        a.fail(2)
        b.fail(2)
        # Neither instance reached the threshold of 4 on its own
        assert a.breaker.state is CircuitState.CLOSED
        assert b.breaker.state is CircuitState.CLOSED

        a.sync()
        assert backend.get(FAILS_KEY) == "2.0"
        b.sync()  # the shared streak reaches 4: b opens and publishes
        assert b.breaker.state is CircuitState.OPEN
        a.sync()
        assert a.breaker.state is CircuitState.OPEN

    def test_a_success_ends_the_shared_streak(self) -> None:
        backend = InMemoryBackend()
        a = Instance(backend, failure_threshold=5, recovery_timeout=60.0)
        b = Instance(backend, failure_threshold=5, recovery_timeout=60.0)

        a.fail(3)
        a.sync()
        assert backend.get(FAILS_KEY) == "3.0"

        b.failing = False
        b.call()
        b.sync()
        assert backend.get(FAILS_KEY) == "0.0"

        b.failing = True
        b.fail(3)
        b.sync()
        # 3 + 3 would have opened the circuit without the success in between
        assert backend.get(FAILS_KEY) == "3.0"
        assert b.breaker.state is CircuitState.CLOSED

    def test_failures_after_a_success_stay_in_the_streak(self) -> None:
        backend = InMemoryBackend()
        a = Instance(backend, failure_threshold=5, recovery_timeout=60.0)

        a.failing = False
        a.call()
        a.failing = True
        a.fail(2)
        a.sync()
        assert backend.get(FAILS_KEY) == "2.0"

    def test_idle_pass_does_not_touch_the_backend(self) -> None:
        backend = InMemoryBackend()
        a = Instance(backend, failure_threshold=5, recovery_timeout=60.0)
        a.sync()
        assert backend.keys() == []

    def test_record_success_counts_like_record_success_atomic(self) -> None:
        backend = InMemoryBackend()
        a = Instance(backend, failure_threshold=5, recovery_timeout=60.0)
        a.fail(2)
        a.sync()
        a.breaker.record_success()
        a.sync()
        assert backend.get(FAILS_KEY) == "0.0"


class TestSharedBreakerAsync:
    async def test_open_circuit_propagates_to_an_async_function(self) -> None:
        backend = InMemoryBackend()
        a = Instance(backend, failure_threshold=1, recovery_timeout=60.0)
        shared = SharedStateConfig(backend=backend, key="svc", sync_interval=0)

        @resilient(
            circuit_breaker=CircuitBreakerConfig(failure_threshold=1, recovery_timeout=60.0),
            shared_state=shared,
        )
        async def call() -> str:
            return "ok"

        assert await call() == "ok"
        a.fail()
        a.sync()
        shared.sync_now()
        with pytest.raises(CircuitOpenError):
            await call()
