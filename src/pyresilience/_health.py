"""Health check utilities for resilience components."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from pyresilience._registry import ResilienceRegistry


def health_check(registry: ResilienceRegistry) -> Dict[str, Any]:
    """Return health status of all registered resilience components.

    Returns a dict mapping registered names to their circuit breaker states.
    Only includes entries that have circuit breakers configured.

    Example::

        registry = ResilienceRegistry()
        registry.register("payment-api", ResilienceConfig(
            circuit_breaker=CircuitBreakerConfig()
        ))

        status = health_check(registry)
        # {"payment-api": {"circuit_breaker": {"state": "closed", "failure_count": 0}}}
    """
    result: Dict[str, Any] = {}
    for name in registry.names:
        entry: Dict[str, Any] = {}
        executor = registry.get_executor(name)

        if executor is not None:
            cb = getattr(executor, "_circuit_breaker", None)
            if cb is not None:
                entry["circuit_breaker"] = {
                    "state": cb.state.value,
                    "failure_count": cb.failure_count,
                }

        if entry:
            result[name] = entry
    return result
