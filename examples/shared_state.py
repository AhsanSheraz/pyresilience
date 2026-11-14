"""Shared state — one rate limit and one circuit breaker for several processes.

Two decorated functions stand in for two replicas of a service. They share state
through an InMemoryBackend here; in production pass RedisBackend(your_redis_client)
from pyresilience.contrib.redis instead. Nothing else changes.
"""

import contextlib

from pyresilience import (
    CircuitBreakerConfig,
    CircuitOpenError,
    InMemoryBackend,
    RateLimiterConfig,
    RateLimitExceededError,
    SharedStateConfig,
    resilient,
)

backend = InMemoryBackend()


def make_replica(name: str):
    """Build one 'replica' of a service that calls the payment API."""
    # sync_interval=0: no background thread, the example syncs by hand to stay deterministic
    shared = SharedStateConfig(backend=backend, key="payment-api", sync_interval=0)
    state = {"down": False}

    @resilient(
        circuit_breaker=CircuitBreakerConfig(failure_threshold=4, recovery_timeout=30.0),
        rate_limiter=RateLimiterConfig(max_calls=5, period=3600.0),
        shared_state=shared,
    )
    def charge(amount: float) -> str:
        if state["down"]:
            raise ConnectionError("payment API is down")
        return f"{name} charged {amount:.2f}"

    return charge, shared, state


if __name__ == "__main__":
    charge_a, shared_a, state_a = make_replica("replica-a")
    charge_b, shared_b, state_b = make_replica("replica-b")

    print("=== One rate limit for both replicas (5 calls per hour) ===")
    for charge in (charge_a, charge_b, charge_a, charge_b, charge_a):
        print(charge(10.0))
    try:
        charge_b(10.0)
    except RateLimitExceededError as exc:
        print(f"replica-b: {exc}  (it made only 2 calls itself)")

    print("\n=== One circuit breaker for both replicas (threshold 4) ===")
    # Fresh backend and replicas, so the rate limit above does not interfere
    backend = InMemoryBackend()
    charge_a, shared_a, state_a = make_replica("replica-a")
    charge_b, shared_b, state_b = make_replica("replica-b")
    state_a["down"] = state_b["down"] = True

    for charge in (charge_a, charge_b, charge_a, charge_b):
        with contextlib.suppress(ConnectionError):
            charge(10.0)
    print("each replica saw 2 failures: neither reached the threshold of 4 alone")

    shared_a.sync_now()  # in production a background thread does this every second
    shared_b.sync_now()
    shared_a.sync_now()

    for name, charge in (("replica-a", charge_a), ("replica-b", charge_b)):
        try:
            charge(10.0)
        except CircuitOpenError:
            print(f"{name}: circuit is open (4 failures across the fleet)")
