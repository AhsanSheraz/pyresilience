"""Async example — all patterns work with async functions automatically."""

import asyncio
import random

from pyresilience import (
    CacheConfig,
    CircuitBreakerConfig,
    MetricsCollector,
    RateLimiterConfig,
    RetryConfig,
    TimeoutConfig,
    resilient,
)

metrics = MetricsCollector()


@resilient(
    retry=RetryConfig(max_attempts=3, delay=0.1),
    timeout=TimeoutConfig(seconds=2.0),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
    rate_limiter=RateLimiterConfig(max_calls=20, period=1.0),
    cache=CacheConfig(max_size=50, ttl=10.0),
    listeners=[metrics],
)
async def fetch_user(user_id: int) -> dict:
    """Simulate an async API call."""
    await asyncio.sleep(random.uniform(0.01, 0.05))
    if random.random() < 0.2:
        raise ConnectionError("Service unavailable")
    return {"id": user_id, "name": f"User {user_id}"}


async def main() -> None:
    print("Fetching users concurrently with full resilience...\n")

    tasks = [fetch_user(i % 5) for i in range(20)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    successes = sum(1 for r in results if not isinstance(r, Exception))
    failures = sum(1 for r in results if isinstance(r, Exception))

    print(f"\nResults: {successes} successes, {failures} failures")
    print(f"\nMetrics: {metrics.summary()}")


if __name__ == "__main__":
    asyncio.run(main())
