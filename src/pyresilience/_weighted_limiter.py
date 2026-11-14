"""Weighted rate limiter — several limits, cost-based acquisition, server feedback.

Used instead of the plain ``RateLimiter`` when ``RateLimiterConfig`` sets ``cost``,
``actual_cost``, ``limits``, ``feedback`` or ``charge_retries``:

- every limit is a token bucket; a call takes its cost from all of them or from none
- after the call, the reserved estimate is reconciled with the real cost
- ``Retry-After`` and rate-limit headers reported by the server pause or lower the limits

The state lives in ``pyresilience._limiter_core._LimiterCore``.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, Callable, List, Optional

from pyresilience._limiter_core import _LimiterCore

if TYPE_CHECKING:
    from pyresilience._types import RateLimiterConfig

_monotonic = time.monotonic
_MIN_SLEEP = 0.001


def _needs_weighted_limiter(config: RateLimiterConfig) -> bool:
    """True when the config asks for more than one token per call on one limit."""
    return bool(
        config.cost is not None
        or config.actual_cost is not None
        or config.limits
        or config.feedback is not None
        or config.charge_retries
    )


class _Reservation(List[float]):
    """Units reserved per limit for one call, plus the shared windows they were counted in."""

    __slots__ = ("windows",)

    def __init__(self, costs: list[float]) -> None:
        super().__init__(costs)
        self.windows: Optional[list[Optional[str]]] = None


class _WeightedRateLimiter:
    """Thread-safe limiter with several limits and weighted, all-or-nothing acquisition."""

    __slots__ = ("_core",)

    def __init__(self, config: RateLimiterConfig, core: Optional[_LimiterCore] = None) -> None:
        self._core = core if core is not None else _LimiterCore(config)

    @property
    def observes(self) -> bool:
        """True when calls must be wrapped with ``bind`` to observe their outcome."""
        return self._core.observes

    def reserve(
        self, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> tuple[Optional[_Reservation], str]:
        """Reserve capacity for a call, waiting up to ``max_wait``.

        Returns ``(reservation, "")`` on success or ``(None, blocker)`` when rejected.
        """
        core = self._core
        costs = _Reservation(core.costs(args, kwargs))
        max_wait = core.max_wait
        deadline = _monotonic() + max_wait

        while True:
            ok, wait, blocker = core.try_reserve(costs)
            if ok:
                shared = core.shared
                if shared is None:
                    return costs, ""
                ok, wait, blocker, windows = shared.acquire(costs)
                if ok:
                    costs.windows = windows
                    return costs, ""
                core.give_back(costs)

            if max_wait <= 0 or wait > deadline - _monotonic():
                return None, blocker

            time.sleep(wait if wait > _MIN_SLEEP else _MIN_SLEEP)

    def acquire(self) -> bool:
        """Reserve capacity for a call without arguments. Returns False if rejected."""
        return self.reserve((), {})[0] is not None

    def bind(self, func: Callable[..., Any], costs: list[float]) -> Callable[..., Any]:
        """Wrap ``func`` so every attempt is observed (reconcile, feedback, retries).

        Without ``charge_retries`` the call has one reservation: it stays open across
        failed attempts and is settled by the first attempt that reports its usage.
        With ``charge_retries`` every retry takes a reservation of its own.
        """
        core = self._core
        shared = core.shared
        attempts = [0]
        call_reserved = list(costs)
        call_windows: Optional[list[Optional[str]]] = getattr(costs, "windows", None)

        def bound(*args: Any, **kwargs: Any) -> Any:
            attempts[0] += 1
            reserved = call_reserved
            windows = call_windows
            if core.charge_retries:
                reserved = list(costs)
                if attempts[0] > 1:
                    core.charge(costs)
                    windows = shared.charge(costs) if shared is not None else None
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                core.observe(reserved, exc, True)
                raise
            deltas = core.observe(reserved, result, False)
            if deltas is not None and shared is not None:
                shared.adjust(deltas, windows)
            return result

        return bound

    def levels(self) -> dict[str, float]:
        """Units currently available per limit."""
        return self._core.levels()

    def reset(self) -> None:
        """Refill every limit and lift any pause."""
        self._core.reset()


class _AsyncWeightedRateLimiter:
    """Async limiter with several limits and weighted, all-or-nothing acquisition."""

    __slots__ = ("_core",)

    def __init__(self, config: RateLimiterConfig, core: Optional[_LimiterCore] = None) -> None:
        self._core = core if core is not None else _LimiterCore(config)

    @property
    def observes(self) -> bool:
        """True when calls must be wrapped with ``bind`` to observe their outcome."""
        return self._core.observes

    async def reserve(
        self, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> tuple[Optional[_Reservation], str]:
        """Reserve capacity for a call, waiting up to ``max_wait``.

        Returns ``(reservation, "")`` on success or ``(None, blocker)`` when rejected.
        """
        core = self._core
        costs = _Reservation(core.costs(args, kwargs))
        max_wait = core.max_wait
        deadline = _monotonic() + max_wait

        while True:
            ok, wait, blocker = core.try_reserve(costs)
            if ok:
                shared = core.shared
                if shared is None:
                    return costs, ""
                # Backend I/O runs in a worker thread so the event loop stays free
                loop = asyncio.get_running_loop()
                ok, wait, blocker, windows = await loop.run_in_executor(None, shared.acquire, costs)
                if ok:
                    costs.windows = windows
                    return costs, ""
                core.give_back(costs)

            if max_wait <= 0 or wait > deadline - _monotonic():
                return None, blocker

            await asyncio.sleep(wait if wait > _MIN_SLEEP else _MIN_SLEEP)

    async def acquire(self) -> bool:
        """Reserve capacity for a call without arguments. Returns False if rejected."""
        return (await self.reserve((), {}))[0] is not None

    def bind(self, func: Callable[..., Any], costs: list[float]) -> Callable[..., Any]:
        """Wrap ``func`` so every attempt is observed (reconcile, feedback, retries).

        Without ``charge_retries`` the call has one reservation: it stays open across
        failed attempts and is settled by the first attempt that reports its usage.
        With ``charge_retries`` every retry takes a reservation of its own.
        """
        core = self._core
        shared = core.shared
        attempts = [0]
        call_reserved = list(costs)
        call_windows: Optional[list[Optional[str]]] = getattr(costs, "windows", None)

        async def bound(*args: Any, **kwargs: Any) -> Any:
            attempts[0] += 1
            reserved = call_reserved
            windows = call_windows
            if core.charge_retries:
                reserved = list(costs)
                if attempts[0] > 1:
                    core.charge(costs)
                    if shared is not None:
                        loop = asyncio.get_running_loop()
                        windows = await loop.run_in_executor(None, shared.charge, costs)
                    else:
                        windows = None
            try:
                result = await func(*args, **kwargs)
            except Exception as exc:
                core.observe(reserved, exc, True)
                raise
            deltas = core.observe(reserved, result, False)
            if deltas is not None and shared is not None:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, shared.adjust, deltas, windows)
            return result

        return bound

    def levels(self) -> dict[str, float]:
        """Units currently available per limit."""
        return self._core.levels()

    def reset(self) -> None:
        """Refill every limit and lift any pause."""
        self._core.reset()
