"""Stateful parts of an executor that can be shared between executors.

A registry builds one ``_Parts`` per name and hands it to the sync and the async
executor of that name, so both call styles see the same circuit breaker, rate
limits, retry budget and cooldown state. A plain ``@resilient`` function builds
its own. With ``SharedStateConfig`` the parts also share state across processes.

Bulkheads and caches are not part of this: they stay per executor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Type

from pyresilience._circuit_breaker import CircuitBreaker
from pyresilience._fallback import _FallbackRouter, _needs_router
from pyresilience._limiter_core import _LimiterCore
from pyresilience._rate_limiter import RateLimiter
from pyresilience._retry_budget import RetryBudget
from pyresilience._shared import _SharedWindows, _SyncedRetryBudget, _syncer_for
from pyresilience._shared_breaker import _SyncedCircuitBreaker
from pyresilience._weighted_limiter import _needs_weighted_limiter

if TYPE_CHECKING:
    from pyresilience._types import ResilienceConfig


class _Parts:
    """The shareable components built from one ``ResilienceConfig``."""

    __slots__ = ("circuit_breaker", "limiter_core", "plain_limiter", "retry_budget", "router")

    def __init__(self) -> None:
        self.circuit_breaker: Optional[CircuitBreaker] = None
        self.retry_budget: Optional[RetryBudget] = None
        # Exactly one of the two limiters is set when a rate limiter is configured
        self.plain_limiter: Optional[RateLimiter] = None
        self.limiter_core: Optional[_LimiterCore] = None
        self.router: Optional[_FallbackRouter] = None


def _build_parts(config: ResilienceConfig, state_key: str = "") -> _Parts:
    """Create the shareable components for *config*.

    ``state_key`` names the state in the backend when ``config.shared_state`` is
    set and does not carry a key of its own.
    """
    parts = _Parts()
    shared = config.shared_state
    backend = None
    key = ""
    syncer = None
    if shared is not None:
        backend = shared.backend
        key = shared.key or state_key
        if not key:
            raise ValueError("shared_state needs a key: set SharedStateConfig.key")
        syncer = _syncer_for(shared)

    if config.circuit_breaker is not None:
        if backend is not None and syncer is not None:
            breaker = _SyncedCircuitBreaker(config.circuit_breaker, backend, key)
            syncer.add(breaker)
            parts.circuit_breaker = breaker
        else:
            parts.circuit_breaker = CircuitBreaker(config.circuit_breaker)

    if config.retry_budget is not None:
        if backend is not None and syncer is not None:
            budget = _SyncedRetryBudget(config.retry_budget, backend, key)
            syncer.add(budget)
            parts.retry_budget = budget
        else:
            parts.retry_budget = RetryBudget(config.retry_budget)

    limiter_cfg = config.rate_limiter
    if limiter_cfg is not None:
        if backend is not None and shared is not None:
            # Shared limits always use the weighted limiter: it knows the cost per limit
            core = _LimiterCore(limiter_cfg)
            core.shared = _SharedWindows(
                backend,
                key,
                [bucket.name for bucket in core.buckets],
                [bucket.capacity for bucket in core.buckets],
                [bucket.period for bucket in core.buckets],
                shared.fail_open,
                shared.sync_interval,
            )
            parts.limiter_core = core
        elif _needs_weighted_limiter(limiter_cfg):
            parts.limiter_core = _LimiterCore(limiter_cfg)
        else:
            parts.plain_limiter = RateLimiter(limiter_cfg)

    if _needs_router(config.fallback):
        ignore_on: tuple[Type[BaseException], ...] = (
            tuple(config.retry.ignore_on) if config.retry else ()
        )
        parts.router = _FallbackRouter(config.fallback, ignore_on)  # type: ignore[arg-type]

    return parts
