"""Tests for the shared retry budget and the background synchronisation pass."""

from __future__ import annotations

import gc
import logging
import threading
import time
from typing import Any, Optional

import pytest

from pyresilience import (
    CircuitBreakerConfig,
    CircuitOpenError,
    CircuitState,
    InMemoryBackend,
    RetryBudgetConfig,
    RetryConfig,
    SharedStateConfig,
    resilient,
)


class BrokenBackend:
    """A backend that is unreachable."""

    def get(self, key: str) -> Optional[str]:
        raise ConnectionError("backend down")

    def set(self, key: str, value: str, ttl: Optional[float] = None) -> None:
        raise ConnectionError("backend down")

    def incr(self, key: str, amount: float, ttl: Optional[float] = None) -> float:
        raise ConnectionError("backend down")

    def delete(self, key: str) -> None:
        raise ConnectionError("backend down")


def _budget_instance(backend: Any, sync_interval: float = 0) -> Any:
    """A function that always fails and retries twice, drawing on a 5-retry budget."""
    shared = SharedStateConfig(backend=backend, key="svc", sync_interval=sync_interval)

    @resilient(
        retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
        retry_budget=RetryBudgetConfig(max_retries=5, refill_rate=0.0001),
        shared_state=shared,
    )
    def call() -> str:
        raise ConnectionError("down")

    return call, shared


def _wait_until(condition: Any, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


class TestSharedRetryBudget:
    def test_retries_spent_elsewhere_reduce_the_local_budget(self) -> None:
        backend = InMemoryBackend()
        call_a, shared_a = _budget_instance(backend)
        call_b, shared_b = _budget_instance(backend)
        budget_a = call_a._executor._retry_budget
        budget_b = call_b._executor._retry_budget

        with pytest.raises(ConnectionError):
            call_a()  # spends 2 of a's 5 retries
        assert budget_a.available == pytest.approx(3.0, abs=0.01)
        assert budget_b.available == pytest.approx(5.0, abs=0.01)

        shared_a.sync_now()
        shared_b.sync_now()
        # b learns that 2 retries of the common budget are gone
        assert budget_b.available == pytest.approx(3.0, abs=0.01)

    def test_own_retries_are_not_counted_twice(self) -> None:
        backend = InMemoryBackend()
        call_a, shared_a = _budget_instance(backend)
        budget_a = call_a._executor._retry_budget

        with pytest.raises(ConnectionError):
            call_a()
        shared_a.sync_now()
        shared_a.sync_now()
        assert budget_a.available == pytest.approx(3.0, abs=0.01)

    def test_repeated_passes_do_not_debit_again(self) -> None:
        backend = InMemoryBackend()
        call_a, shared_a = _budget_instance(backend)
        call_b, shared_b = _budget_instance(backend)
        budget_b = call_b._executor._retry_budget

        with pytest.raises(ConnectionError):
            call_a()
        shared_a.sync_now()
        shared_b.sync_now()
        shared_b.sync_now()
        assert budget_b.available == pytest.approx(3.0, abs=0.01)

    def test_shared_budget_runs_out_for_everyone(self) -> None:
        backend = InMemoryBackend()
        call_a, shared_a = _budget_instance(backend)
        call_b, shared_b = _budget_instance(backend)
        budget_b = call_b._executor._retry_budget

        for _ in range(3):  # 2 + 2 + 1 retries: a's budget is empty
            with pytest.raises(ConnectionError):
                call_a()
        shared_a.sync_now()
        shared_b.sync_now()
        assert budget_b.available == pytest.approx(0.0, abs=0.01)

    def test_exhausted_budget_is_not_counted_as_spent(self) -> None:
        backend = InMemoryBackend()
        call_a, shared_a = _budget_instance(backend)

        for _ in range(4):
            with pytest.raises(ConnectionError):
                call_a()
        shared_a.sync_now()
        (key,) = backend.keys()
        assert key.startswith("svc:rb:")
        assert backend.get(key) == "5.0"


class TestBackgroundSync:
    def test_sync_interval_must_not_be_negative(self) -> None:
        with pytest.raises(ValueError, match="sync_interval must be >= 0"):
            SharedStateConfig(backend=InMemoryBackend(), sync_interval=-1)

    def test_sync_now_without_components_is_a_no_op(self) -> None:
        SharedStateConfig(backend=InMemoryBackend(), sync_interval=0).sync_now()

    def test_no_thread_when_interval_is_zero(self) -> None:
        _, shared = _budget_instance(InMemoryBackend())
        assert shared._syncer._thread is None

    def test_background_thread_propagates_an_open_circuit(self) -> None:
        backend = InMemoryBackend()
        breaker_cfg = CircuitBreakerConfig(failure_threshold=1, recovery_timeout=60.0)

        @resilient(
            circuit_breaker=breaker_cfg,
            shared_state=SharedStateConfig(backend=backend, key="svc", sync_interval=0.05),
        )
        def a() -> str:
            raise ConnectionError("down")

        @resilient(
            circuit_breaker=breaker_cfg,
            shared_state=SharedStateConfig(backend=backend, key="svc", sync_interval=0.05),
        )
        def b() -> str:
            return "ok"

        with pytest.raises(ConnectionError):
            a()
        breaker_b = b._executor._circuit_breaker  # type: ignore[attr-defined]
        # No sync_now(): the background threads carry the open state across
        assert _wait_until(lambda: breaker_b.state is CircuitState.OPEN)

    def test_background_thread_stops_when_nothing_is_left(self) -> None:
        call, shared = _budget_instance(InMemoryBackend(), sync_interval=0.05)
        syncer = shared._syncer
        assert syncer._thread is not None
        assert syncer._thread.daemon is True

        del call
        gc.collect()
        assert _wait_until(lambda: syncer._thread is None)

    def test_dead_components_are_pruned(self) -> None:
        call, shared = _budget_instance(InMemoryBackend())
        syncer = shared._syncer
        assert syncer.sync_now() == 1
        del call
        gc.collect()
        assert syncer.sync_now() == 0
        assert syncer._parts == []

    def test_backend_failure_never_raises_and_is_logged_once(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        call, shared = _budget_instance(BrokenBackend())

        with caplog.at_level(logging.DEBUG, logger="pyresilience"):
            shared.sync_now()
            shared.sync_now()

        levels = [record.levelno for record in caplog.records]
        assert levels == [logging.WARNING, logging.DEBUG]
        # The local budget keeps working
        with pytest.raises(ConnectionError):
            call()
        assert call._executor._retry_budget.available == pytest.approx(3.0, abs=0.01)

    def test_one_config_syncs_all_its_components(self) -> None:
        backend = InMemoryBackend()
        shared = SharedStateConfig(backend=backend, key="svc", sync_interval=0)

        @resilient(
            retry=RetryConfig(max_attempts=2, delay=0.01, jitter=False),
            circuit_breaker=CircuitBreakerConfig(failure_threshold=1, recovery_timeout=60.0),
            retry_budget=RetryBudgetConfig(max_retries=5, refill_rate=0.0001),
            shared_state=shared,
        )
        def call() -> str:
            raise ConnectionError("down")

        # The first failure opens the circuit, so the retry is rejected
        with pytest.raises(CircuitOpenError):
            call()
        assert shared._syncer.sync_now() == 2
        keys = backend.keys()
        assert "svc:cb:open" in keys
        assert any(key.startswith("svc:rb:") for key in keys)


class FlakyBackend(InMemoryBackend):
    """In-memory backend whose writes can be switched off."""

    down = False

    def incr(self, key: str, amount: float, ttl: Optional[float] = None) -> float:
        if self.down:
            raise ConnectionError("backend down")
        return super().incr(key, amount, ttl)

    def set(self, key: str, value: str, ttl: Optional[float] = None) -> None:
        if self.down:
            raise ConnectionError("backend down")
        super().set(key, value, ttl)


class TestSyncSurvivesBackendFailures:
    def test_failures_are_published_after_the_backend_returns(self) -> None:
        backend = FlakyBackend()
        shared = SharedStateConfig(backend=backend, key="svc", sync_interval=0)

        @resilient(
            circuit_breaker=CircuitBreakerConfig(failure_threshold=10, recovery_timeout=60.0),
            shared_state=shared,
        )
        def call() -> str:
            raise ConnectionError("down")

        for _ in range(3):
            with pytest.raises(ConnectionError):
                call()

        backend.down = True
        shared.sync_now()  # the write fails; the three failures must not be forgotten
        backend.down = False
        shared.sync_now()
        assert backend.get("svc:cb:fails") == "3.0"
        shared.sync_now()  # and they are not published twice
        assert backend.get("svc:cb:fails") == "3.0"

    def test_spent_retries_are_published_after_the_backend_returns(self) -> None:
        backend = FlakyBackend()
        call_a, shared_a = _budget_instance(backend)
        call_b, shared_b = _budget_instance(backend)

        with pytest.raises(ConnectionError):
            call_a()  # spends 2 retries

        backend.down = True
        shared_a.sync_now()
        backend.down = False
        shared_a.sync_now()
        shared_b.sync_now()
        assert call_b._executor._retry_budget.available == pytest.approx(3.0, abs=0.01)

    def test_refunded_retry_is_not_published(self) -> None:
        backend = InMemoryBackend()
        call, shared = _budget_instance(backend)
        budget = call._executor._retry_budget

        assert budget.acquire() is True
        budget.refund()
        shared.sync_now()
        (key,) = backend.keys()
        assert backend.get(key) == "0.0"
        assert budget.available == pytest.approx(5.0, abs=0.01)


class TestConcurrentSync:
    def test_parallel_passes_do_not_double_count(self) -> None:
        backend = InMemoryBackend()
        shared = SharedStateConfig(backend=backend, key="svc", sync_interval=0)

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
            circuit_breaker=CircuitBreakerConfig(failure_threshold=100, recovery_timeout=60.0),
            retry_budget=RetryBudgetConfig(max_retries=50, refill_rate=0.0001),
            shared_state=shared,
        )
        def call() -> str:
            raise ConnectionError("down")

        with pytest.raises(ConnectionError):
            call()  # 3 failures, 2 retries

        threads = [
            threading.Thread(target=lambda: [shared.sync_now() for _ in range(50)])
            for _ in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert backend.get("svc:cb:fails") == "3.0"
        names = backend.keys()
        (budget_key,) = [key for key in names if key.startswith("svc:rb:")]
        assert backend.get(budget_key) == "2.0"

    def test_one_syncer_per_config_under_threads(self) -> None:
        from pyresilience._shared import _syncer_for

        shared = SharedStateConfig(backend=InMemoryBackend(), sync_interval=0)
        found: list[Any] = []
        lock = threading.Lock()

        def worker() -> None:
            syncer = _syncer_for(shared)
            with lock:
                found.append(syncer)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(found) == 8
        assert all(syncer is found[0] for syncer in found)
