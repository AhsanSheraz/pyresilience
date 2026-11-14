"""Circuit breaker whose state is shared with other processes through a StateBackend.

Every process keeps deciding locally, so the call path does no backend I/O and a
backend outage leaves each breaker working on its own. A background pass
(``pyresilience._shared._Syncer``) exchanges two things:

- the open state: when one instance opens, the others open within one pass and
  recover at the same moment
- in consecutive-count mode, the failure streak: failures of all instances add up,
  so the threshold is not multiplied by the number of instances

Sliding-window breakers share only the open state. A failure *rate* is the same
on every instance, so it needs no adding up.

Shared timestamps use the wall clock; clock skew between hosts shifts the shared
recovery moment by the skew.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from pyresilience._circuit_breaker import CircuitBreaker
from pyresilience._types import CircuitState

if TYPE_CHECKING:
    from pyresilience._backend import StateBackend
    from pyresilience._types import CircuitBreakerConfig

_CLOSED = CircuitState.CLOSED
_OPEN = CircuitState.OPEN

_monotonic = time.monotonic
# Extra lifetime of shared records beyond their use, in seconds
_GRACE = 5.0


class _SyncedCircuitBreaker(CircuitBreaker):
    """Circuit breaker that publishes and adopts state via ``sync()``."""

    __slots__ = (
        "__weakref__",
        "_adopted_open_at",
        "_aggregate",
        "_backend",
        "_counts_lock",
        "_fail_total",
        "_key",
        "_published_open_at",
        "_seen_fail",
        "_seen_succ",
        "_shared_open",
        "_succ_total",
        "_sync_lock",
    )

    def __init__(self, config: CircuitBreakerConfig, backend: StateBackend, key: str) -> None:
        super().__init__(config)
        self._backend = backend
        self._key = key
        # Failure streaks only add up in consecutive-count mode
        self._aggregate = config.sliding_window_size == 0
        self._counts_lock = threading.Lock()
        self._sync_lock = threading.Lock()
        self._fail_total = 0
        self._succ_total = 0
        self._seen_fail = 0
        self._seen_succ = 0
        # Monotonic open times already published to / adopted from the backend
        self._published_open_at = -1.0
        self._adopted_open_at = -1.0
        # True while the backend holds an open record this instance knows about
        self._shared_open = False

    def record_success_atomic(self, duration: float = 0.0) -> tuple[CircuitState, CircuitState]:
        states = super().record_success_atomic(duration)
        with self._counts_lock:
            self._succ_total += 1
        return states

    def record_success(self, duration: float = 0.0) -> CircuitState:
        state = super().record_success(duration)
        with self._counts_lock:
            self._succ_total += 1
        return state

    def record_failure(self, duration: float = 0.0) -> CircuitState:
        state = super().record_failure(duration)
        with self._counts_lock:
            self._fail_total += 1
        return state

    def _after_fork(self) -> None:
        """Runs in a forked child: take new locks; the parent publishes its own counts."""
        self._lock = threading.Lock()
        self._counts_lock = threading.Lock()
        self._sync_lock = threading.Lock()
        self._seen_fail = self._fail_total
        self._seen_succ = self._succ_total

    def _open_until(self, remaining: float) -> float:
        """Open locally so that recovery starts in *remaining* seconds."""
        if remaining > self._recovery_timeout:
            remaining = self._recovery_timeout
        with self._lock:
            opened_at = _monotonic() - (self._recovery_timeout - remaining)
            self._state = _OPEN
            self._success_count = 0
            self._last_failure_time = opened_at
            return opened_at

    def sync(self) -> None:
        """Exchange state with the backend once."""
        # One pass at a time: a manual sync_now() may meet the background thread
        with self._sync_lock:
            self._sync_once()

    def _sync_once(self) -> None:
        backend = self._backend
        open_key = f"{self._key}:cb:open"
        fails_key = f"{self._key}:cb:fails"
        recovery = self._recovery_timeout
        now_wall = time.time()

        with self._lock:
            self._check_recovery()
            state = self._state
            opened_at = self._last_failure_time
            failure_count = self._failure_count
        with self._counts_lock:
            fail_total = self._fail_total
            succ_total = self._succ_total
        new_failures = fail_total - self._seen_fail
        new_successes = succ_total - self._seen_succ

        # 1. This instance closed again (probes passed or manual reset): clear the record
        if state is _CLOSED and self._shared_open:
            backend.delete(open_key)
            backend.delete(fails_key)
            self._shared_open = False

        # 2. This instance opened on its own: tell the others when it will recover
        if (
            state is not _CLOSED
            and opened_at is not None
            and opened_at != self._published_open_at
            and opened_at != self._adopted_open_at
        ):
            remaining = recovery - (_monotonic() - opened_at)
            if remaining > 0:
                backend.set(open_key, repr(now_wall + remaining), ttl=remaining + _GRACE)
            self._published_open_at = opened_at
            self._shared_open = True

        # 3. Add this instance's failure streak to the shared one
        if self._aggregate and (new_failures or new_successes):
            ttl = max(60.0, recovery * 2)
            if new_successes:
                # A success ends the shared streak; only failures after it remain
                total = float(min(failure_count, new_failures))
                backend.set(fails_key, repr(total), ttl=ttl)
            else:
                total = backend.incr(fails_key, float(new_failures), ttl=ttl)
            if total >= self._failure_threshold and state is _CLOSED:
                opened_at = self._open_until(recovery)
                backend.set(open_key, repr(now_wall + recovery), ttl=recovery + _GRACE)
                self._published_open_at = opened_at
                self._shared_open = True
                state = _OPEN

        # The counts are published; a failed write above is retried by the next pass
        self._seen_fail = fail_total
        self._seen_succ = succ_total

        # 4. Another instance has the circuit open: open here until the same moment
        if state is not _OPEN:
            raw = backend.get(open_key)
            if raw is not None:
                try:
                    remaining = float(raw) - now_wall
                except ValueError:
                    remaining = 0.0
                if remaining > 0:
                    self._adopted_open_at = self._open_until(remaining)
                    self._shared_open = True
