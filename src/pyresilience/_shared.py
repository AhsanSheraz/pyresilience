"""Cross-process sharing of rate limits and retry budgets through a StateBackend.

Two mechanisms, chosen per pattern:

- Rate limits are exact: every acquisition increments a fixed-window counter in the
  backend (``_SharedWindows``). The increment is atomic, so all processes together
  never exceed the limit of a window.
- Retry budgets and circuit breakers are synchronised in the background
  (``_Syncer``): each process decides locally and exchanges its numbers with the
  backend every ``sync_interval`` seconds. The call path does no backend I/O.

The circuit breaker part lives in ``pyresilience._shared_breaker``.
"""

from __future__ import annotations

import logging
import threading
import time
import weakref
from typing import TYPE_CHECKING, Any, Optional, Sequence

from pyresilience._retry_budget import RetryBudget

if TYPE_CHECKING:
    from pyresilience._backend import StateBackend
    from pyresilience._types import RetryBudgetConfig, SharedStateConfig

_logger = logging.getLogger("pyresilience")
_INF = float("inf")
_syncer_lock = threading.Lock()


class _Syncer:
    """Runs the periodic synchronisation pass for the components of one config.

    Components are held weakly and must offer ``sync()``. With an interval > 0 a
    daemon thread runs the pass; it stops by itself once no component is left.
    """

    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._parts: list[weakref.ref[Any]] = []
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._failing = False

    def add(self, part: Any) -> None:
        with self._lock:
            self._parts.append(weakref.ref(part))
            if self._interval > 0 and self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="pyresilience-state-sync", daemon=True
                )
                self._thread.start()

    def _live_parts(self) -> list[Any]:
        with self._lock:
            parts = [part for part in (ref() for ref in self._parts) if part is not None]
            if len(parts) != len(self._parts):
                self._parts = [weakref.ref(part) for part in parts]
            return parts

    def sync_now(self) -> int:
        """Synchronise every live component once. Returns how many there are."""
        parts = self._live_parts()
        failed = False
        for part in parts:
            try:
                part.sync()
            except Exception:
                failed = True
                # Log the first failure of an outage loudly, the rest quietly
                log = _logger.debug if self._failing else _logger.warning
                log("Shared state sync failed; keeping local state", exc_info=True)
        self._failing = failed
        return len(parts)

    def _run(self) -> None:
        while True:
            time.sleep(self._interval)
            if self.sync_now() == 0:
                with self._lock:
                    if not any(ref() is not None for ref in self._parts):
                        self._thread = None
                        return


def _syncer_for(config: SharedStateConfig) -> _Syncer:
    """Return the syncer of a shared-state config, creating it on first use."""
    with _syncer_lock:
        syncer: Optional[_Syncer] = config._syncer
        if syncer is None:
            syncer = _Syncer(config.sync_interval)
            config._syncer = syncer
        return syncer


class _SharedWindows:
    """Fixed-window counters in the backend, one per rate limit.

    ``acquire`` adds a call's costs to the counters of the current windows and
    takes them back when any limit would be exceeded. Because the increment is
    atomic, the limit holds across every process that uses the same key.
    """

    __slots__ = ("_backend", "_capacities", "_fail_open", "_failing", "_key", "_names", "_periods")

    def __init__(
        self,
        backend: StateBackend,
        key: str,
        names: Sequence[str],
        capacities: Sequence[float],
        periods: Sequence[float],
        fail_open: bool,
    ) -> None:
        self._backend = backend
        self._key = key
        self._names = list(names)
        self._capacities = list(capacities)
        self._periods = list(periods)
        self._fail_open = fail_open
        self._failing = False

    def _window_key(self, index: int, now: float) -> str:
        window = int(now // self._periods[index])
        return f"{self._key}:rl:{self._names[index]}:{window}"

    def _backend_failed(self) -> None:
        log = _logger.debug if self._failing else _logger.warning
        log("Shared rate limit backend failed for %r", self._key, exc_info=True)
        self._failing = True

    def acquire(self, costs: list[float]) -> tuple[bool, float, str, list[Optional[str]]]:
        """Count a call against every shared window.

        Returns ``(ok, wait, blocker, windows)``. On rejection ``wait`` is the time
        until the blocking window ends. ``windows`` names the counter each limit
        was counted in, so a later correction reaches the same window.
        """
        backend = self._backend
        now = time.time()
        windows: list[Optional[str]] = [None] * len(costs)
        taken: list[tuple[str, float, float]] = []
        try:
            for index, cost in enumerate(costs):
                if cost <= 0:
                    continue
                period = self._periods[index]
                key = self._window_key(index, now)
                total = backend.incr(key, cost, ttl=period * 2)
                taken.append((key, cost, period))
                windows[index] = key
                if total > self._capacities[index]:
                    for taken_key, taken_cost, taken_period in taken:
                        backend.incr(taken_key, -taken_cost, ttl=taken_period * 2)
                    wait = (int(now // period) + 1) * period - now
                    return False, wait, self._names[index], windows
        except Exception:
            self._backend_failed()
            for taken_key, taken_cost, taken_period in taken:
                try:
                    backend.incr(taken_key, -taken_cost, ttl=taken_period * 2)
                except Exception:
                    break
            if self._fail_open:
                # Keep serving on the local limit alone until the backend is back
                return True, 0.0, "", [None] * len(costs)
            return False, _INF, "state backend unavailable", windows
        self._failing = False
        return True, 0.0, "", windows

    def charge(self, costs: list[float]) -> Optional[list[Optional[str]]]:
        """Add ``costs`` to the current windows without checking the limits.

        Used for retry attempts. Returns the windows that were charged, or None
        when the backend could not be reached.
        """
        now = time.time()
        windows: list[Optional[str]] = [None] * len(costs)
        try:
            for index, cost in enumerate(costs):
                if cost > 0:
                    key = self._window_key(index, now)
                    self._backend.incr(key, cost, ttl=self._periods[index] * 2)
                    windows[index] = key
        except Exception:
            self._backend_failed()
            return None
        return windows

    def adjust(self, deltas: list[float], windows: Optional[list[Optional[str]]]) -> None:
        """Correct the shared counters after a call reported its real usage.

        A positive delta gives units back, but only to the window they were taken
        from and only while that window is still current: a later window never had
        them, so giving them back there would let it exceed its limit. A negative
        delta (more used than reserved) is charged to the current window.
        """
        now = time.time()
        try:
            for index, delta in enumerate(deltas):
                if not delta:
                    continue
                current = self._window_key(index, now)
                ttl = self._periods[index] * 2
                if delta < 0 or (windows is not None and windows[index] == current):
                    self._backend.incr(current, -delta, ttl=ttl)
        except Exception:
            self._backend_failed()


class _SyncedRetryBudget(RetryBudget):
    """Retry budget whose consumption is shared with other processes.

    Each pass publishes the retries this process spent and debits the retries
    other processes spent, so the fleet as a whole stays close to one budget.
    """

    __slots__ = (
        "__weakref__",
        "_backend",
        "_key",
        "_seen_spent",
        "_seen_total",
        "_spent",
        "_sync_lock",
        "_window",
    )

    def __init__(self, config: RetryBudgetConfig, backend: StateBackend, key: str) -> None:
        super().__init__(config)
        self._backend = backend
        self._key = key
        self._spent = 0
        self._seen_spent = 0
        self._sync_lock = threading.Lock()
        self._seen_total = 0.0
        self._window = -1

    def acquire(self) -> bool:
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                self._spent += 1
                return True
            return False

    def refund(self) -> None:
        with self._lock:
            self._tokens = min(self._capacity, self._tokens + 1.0)
            self._spent -= 1

    def sync(self) -> None:
        """Publish local consumption and absorb what other processes consumed."""
        # One pass at a time: a manual sync_now() may meet the background thread
        with self._sync_lock:
            self._sync_once()

    def _sync_once(self) -> None:
        # One window is the time a full budget needs to refill
        window_length = self._capacity / self._rate
        window = int(time.time() // window_length)
        with self._lock:
            spent = self._spent
        delta = spent - self._seen_spent
        if window != self._window:
            self._window = window
            self._seen_total = 0.0
        total = self._backend.incr(f"{self._key}:rb:{window}", float(delta), ttl=window_length * 2)
        # Only now is the delta published; a failed write is retried by the next pass
        self._seen_spent = spent
        others = total - self._seen_total - delta
        self._seen_total = total
        if others > 0:
            with self._lock:
                self._refill()
                self._tokens = max(0.0, self._tokens - others)
