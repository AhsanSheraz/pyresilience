"""Cross-process sharing of rate limits and retry budgets through a StateBackend.

Two mechanisms, chosen per pattern:

- Rate limits are exact: every acquisition increments a fixed-window counter in the
  backend (``_SharedWindows``). The increment is atomic, so all processes together
  never exceed the limit of a window.
- Retry budgets and circuit breakers are synchronised in the background
  (``_Syncer``): each process decides locally and exchanges its numbers with the
  backend every ``sync_interval`` seconds. The call path does no backend I/O.

The circuit breaker part lives in ``pyresilience._shared_breaker``.

Threads do not survive ``os.fork()``. A hook registered with
``os.register_at_fork`` gives a forked child new locks and its own sync thread.
"""

from __future__ import annotations

import logging
import os
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
# Seconds without backend calls after a failed one, unless the config asks for more
_MIN_OUTAGE_PAUSE = 1.0
# The backend is also left alone for this many times the time the failed call took,
# so that a client that is slow to give up cannot keep a caller waiting most of the time
_OUTAGE_BACKOFF = 10.0
# Longest pause that results from that, and the longest time the other calls keep
# skipping the backend while one call is trying it again (it only matters when that
# call does not report back)
_MAX_OUTAGE_PAUSE = 30.0


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
        _syncers.add(self)

    def _start(self) -> None:
        """Start the sync thread. The caller holds the lock."""
        self._thread = threading.Thread(
            target=self._run, name="pyresilience-state-sync", daemon=True
        )
        self._thread.start()

    def add(self, part: Any) -> None:
        with self._lock:
            self._parts.append(weakref.ref(part))
            if self._interval > 0 and self._thread is None:
                self._start()

    def _after_fork(self) -> None:
        """Runs in a forked child: the parent's thread is gone and its locks may be held."""
        self._lock = threading.Lock()
        self._thread = None
        parts = self._live_parts()
        for part in parts:
            part._after_fork()
        if parts and self._interval > 0:
            with self._lock:
                self._start()

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


_syncers: weakref.WeakSet[_Syncer] = weakref.WeakSet()


def _after_fork_in_child() -> None:
    """Give a forked child working shared state: new locks and a new sync thread."""
    global _syncer_lock
    _syncer_lock = threading.Lock()
    for syncer in list(_syncers):
        syncer._after_fork()


if hasattr(os, "register_at_fork"):  # not on Windows
    os.register_at_fork(after_in_child=_after_fork_in_child)


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

    After a failed backend call the backend is left alone for ``pause`` seconds,
    or longer when the failed call was slow: calls are answered at once according
    to ``fail_open`` instead of each waiting for the client's own timeout. When the
    pause is over, one call tries again. Until that call reports back, the others
    keep being answered at once, so at most one call at a time waits for a backend
    that is down.
    """

    __slots__ = (
        "_backend",
        "_capacities",
        "_down_until",
        "_fail_open",
        "_failing",
        "_key",
        "_names",
        "_pause",
        "_periods",
    )

    def __init__(
        self,
        backend: StateBackend,
        key: str,
        names: Sequence[str],
        capacities: Sequence[float],
        periods: Sequence[float],
        fail_open: bool,
        pause: float = _MIN_OUTAGE_PAUSE,
    ) -> None:
        self._backend = backend
        self._key = key
        self._names = list(names)
        self._capacities = list(capacities)
        self._periods = list(periods)
        self._fail_open = fail_open
        self._failing = False
        self._pause = max(_MIN_OUTAGE_PAUSE, pause)
        # Monotonic time until which the backend is not called; 0 while it works
        self._down_until = 0.0

    def _window_key(self, index: int, now: float) -> str:
        window = int(now // self._periods[index])
        return f"{self._key}:rl:{self._names[index]}:{window}"

    def _backend_failed(self, took: float) -> None:
        """Start the pause after a backend call that failed after *took* seconds."""
        log = _logger.debug if self._failing else _logger.warning
        log("Shared rate limit backend failed for %r", self._key, exc_info=True)
        self._failing = True
        # The longer the client took to give up, the longer the backend is left alone
        pause = max(self._pause, min(_OUTAGE_BACKOFF * took, _MAX_OUTAGE_PAUSE))
        self._down_until = time.monotonic() + pause

    def _backend_ok(self) -> None:
        if self._failing:
            self._failing = False
            self._down_until = 0.0

    def _not_tried(self) -> None:
        """The call had nothing to send to the backend, so it learned nothing about it."""
        if self._down_until:
            # This call was the one to try the backend again: the next call does it
            self._down_until = time.monotonic()

    def _paused(self) -> bool:
        """True while the backend is left alone after a failure."""
        until = self._down_until
        if not until:
            return False
        now = time.monotonic()
        if now < until:
            return True
        # The pause is over: this call tries the backend. The others keep skipping it
        # until this call reports back, however long the client takes to give up.
        self._down_until = now + max(self._pause, _MAX_OUTAGE_PAUSE)
        return False

    def _unavailable(self, count: int) -> tuple[bool, float, str, list[Optional[str]]]:
        """Answer for a call that cannot be counted in the backend."""
        if self._fail_open:
            # Keep serving on the local limit alone until the backend is back
            return True, 0.0, "", [None] * count
        return False, _INF, "state backend unavailable", [None] * count

    def acquire(self, costs: list[float]) -> tuple[bool, float, str, list[Optional[str]]]:
        """Count a call against every shared window.

        Returns ``(ok, wait, blocker, windows)``. On rejection ``wait`` is the time
        until the blocking window ends. ``windows`` names the counter each limit
        was counted in, so a later correction reaches the same window.
        """
        if self._paused():
            return self._unavailable(len(costs))
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
                    # The backend answered: a full window is not an outage
                    self._backend_ok()
                    wait = (int(now // period) + 1) * period - now
                    return False, wait, self._names[index], windows
        except Exception:
            self._backend_failed(time.time() - now)
            for taken_key, taken_cost, taken_period in taken:
                try:
                    backend.incr(taken_key, -taken_cost, ttl=taken_period * 2)
                except Exception:
                    break
            return self._unavailable(len(costs))
        if taken:
            self._backend_ok()
        else:
            self._not_tried()
        return True, 0.0, "", windows

    def charge(self, costs: list[float]) -> Optional[list[Optional[str]]]:
        """Add ``costs`` to the current windows without checking the limits.

        Used for retry attempts. Returns the windows that were charged, or None
        when the backend could not be reached.
        """
        if self._paused():
            return None
        now = time.time()
        windows: list[Optional[str]] = [None] * len(costs)
        sent = False
        try:
            for index, cost in enumerate(costs):
                if cost > 0:
                    key = self._window_key(index, now)
                    self._backend.incr(key, cost, ttl=self._periods[index] * 2)
                    windows[index] = key
                    sent = True
        except Exception:
            self._backend_failed(time.time() - now)
            return None
        if sent:
            self._backend_ok()
        else:
            self._not_tried()
        return windows

    def adjust(self, deltas: list[float], windows: Optional[list[Optional[str]]]) -> None:
        """Correct the shared counters after a call reported its real usage.

        A positive delta gives units back, but only to the window they were taken
        from and only while that window is still current: a later window never had
        them, so giving them back there would let it exceed its limit. A negative
        delta (more used than reserved) is charged to the current window.
        """
        if self._paused():
            return
        now = time.time()
        sent = False
        try:
            for index, delta in enumerate(deltas):
                if not delta:
                    continue
                current = self._window_key(index, now)
                ttl = self._periods[index] * 2
                if delta < 0 or (windows is not None and windows[index] == current):
                    self._backend.incr(current, -delta, ttl=ttl)
                    sent = True
        except Exception:
            self._backend_failed(time.time() - now)
            return
        if sent:
            self._backend_ok()
        else:
            self._not_tried()


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

    def _after_fork(self) -> None:
        """Runs in a forked child: take new locks; the parent publishes what it spent."""
        self._lock = threading.Lock()
        self._sync_lock = threading.Lock()
        self._seen_spent = self._spent

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
