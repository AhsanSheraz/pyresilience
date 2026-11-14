"""Tests for shared state in a forked child process."""

from __future__ import annotations

import contextlib
import gc
import os
import threading
import time
import warnings
from typing import Any

import pytest

from pyresilience import (
    CircuitBreakerConfig,
    InMemoryBackend,
    RetryBudgetConfig,
    RetryConfig,
    SharedStateConfig,
    _shared,
    resilient,
)
from pyresilience._shared import _after_fork_in_child, _Syncer


def _decorated(backend: InMemoryBackend, sync_interval: float) -> tuple[Any, _Syncer]:
    shared = SharedStateConfig(backend=backend, key="svc", sync_interval=sync_interval)

    @resilient(
        retry=RetryConfig(max_attempts=2, delay=0.01, jitter=False),
        circuit_breaker=CircuitBreakerConfig(failure_threshold=2, recovery_timeout=30.0),
        retry_budget=RetryBudgetConfig(max_retries=10, refill_rate=1.0),
        shared_state=shared,
    )
    def call(fail: bool = False) -> str:
        if fail:
            raise ConnectionError("down")
        return "ok"

    syncer = shared._syncer
    assert isinstance(syncer, _Syncer)
    return call, syncer


class TestAfterForkHook:
    def test_hook_is_registered_where_fork_exists(self) -> None:
        # Nothing to assert on Windows; elsewhere the module registered the hook on import
        assert callable(_after_fork_in_child)
        assert hasattr(os, "register_at_fork") == hasattr(os, "fork")

    def test_child_gets_a_new_sync_thread(self) -> None:
        call, syncer = _decorated(InMemoryBackend(), sync_interval=0.05)
        old_thread = syncer._thread
        old_lock = syncer._lock
        assert old_thread is not None

        _after_fork_in_child()

        assert syncer._thread is not None
        assert syncer._thread is not old_thread
        assert syncer._thread.is_alive()
        assert syncer._lock is not old_lock
        assert call() == "ok"

    def test_child_sync_thread_reaches_the_backend(self) -> None:
        backend = InMemoryBackend()
        call, _ = _decorated(backend, sync_interval=0.05)
        _after_fork_in_child()

        with pytest.raises(ConnectionError):
            call(fail=True)
        # Two failed attempts open the breaker; the background pass publishes it
        deadline = time.monotonic() + 5.0
        while backend.get("svc:cb:open") is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert backend.get("svc:cb:open") is not None

    def test_locks_held_at_fork_time_are_replaced(self) -> None:
        call, syncer = _decorated(InMemoryBackend(), sync_interval=0)
        breaker = call._executor._circuit_breaker
        budget = call._executor._retry_budget
        module_lock = _shared._syncer_lock
        held = [
            syncer._lock,
            breaker._lock,
            breaker._counts_lock,
            breaker._sync_lock,
            budget._lock,
            budget._sync_lock,
            module_lock,
        ]
        # A thread of the parent held every lock at the moment of the fork
        for lock in held:
            lock.acquire()
        try:
            _after_fork_in_child()

            finished = threading.Event()

            def use() -> None:
                with pytest.raises(ConnectionError):
                    call(fail=True)
                syncer.sync_now()
                finished.set()

            worker = threading.Thread(target=use, daemon=True)
            worker.start()
            # Generous bound for slow CI: with the old locks this never finishes
            assert finished.wait(10.0)
            assert _shared._syncer_lock is not module_lock
        finally:
            for lock in held:
                lock.release()

    def test_child_does_not_publish_what_the_parent_counted(self) -> None:
        backend = InMemoryBackend()
        call, syncer = _decorated(backend, sync_interval=0)
        with pytest.raises(ConnectionError):
            call(fail=True)
        breaker = call._executor._circuit_breaker
        budget = call._executor._retry_budget
        assert breaker._fail_total == 2
        assert budget._spent == 1

        _after_fork_in_child()

        assert breaker._seen_fail == 2
        assert budget._seen_spent == 1
        syncer.sync_now()
        # The parent publishes these numbers; the child adds nothing for them
        assert backend.get("svc:cb:fails") is None
        budget_keys = [key for key in backend.keys() if ":rb:" in key]  # noqa: SIM118
        assert [float(backend.get(key) or 0) for key in budget_keys] == [0.0]

    def test_no_thread_without_an_interval(self) -> None:
        _, syncer = _decorated(InMemoryBackend(), sync_interval=0)
        _after_fork_in_child()
        assert syncer._thread is None

    def test_no_thread_when_nothing_is_left_to_sync(self) -> None:
        call, syncer = _decorated(InMemoryBackend(), sync_interval=30.0)
        del call
        gc.collect()
        _after_fork_in_child()
        assert syncer._thread is None


@pytest.mark.skipif(not hasattr(os, "fork"), reason="os.fork is not available on this platform")
class TestRealFork:
    def test_forked_child_keeps_syncing(self) -> None:
        backend = InMemoryBackend()
        # Decorated before the fork, as with a preloading application server
        call, _ = _decorated(backend, sync_interval=0.05)

        with warnings.catch_warnings():
            # Python warns about forking a multi-threaded process
            warnings.simplefilter("ignore", DeprecationWarning)
            pid = os.fork()
        if pid == 0:  # pragma: no cover - runs in the child process
            code = 1
            try:
                with contextlib.suppress(ConnectionError):
                    call(fail=True)
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline:
                    if backend.get("svc:cb:open") is not None:
                        code = 0
                        break
                    time.sleep(0.02)
            finally:
                os._exit(code)

        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 0
