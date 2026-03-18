"""Combined patterns example — all resilience patterns working together."""

import random
import time

from pyresilience import (
    BulkheadConfig,
    CacheConfig,
    CircuitBreakerConfig,
    FallbackConfig,
    JsonEventLogger,
    MetricsCollector,
    RateLimiterConfig,
    RetryConfig,
    TimeoutConfig,
    resilient,
)

logger = JsonEventLogger()
metrics = MetricsCollector()


@resilient(
    cache=CacheConfig(max_size=100, ttl=30.0),
    retry=RetryConfig(max_attempts=3, delay=0.1, backoff_factor=2.0),
    timeout=TimeoutConfig(seconds=2.0),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5, recovery_timeout=10),
    rate_limiter=RateLimiterConfig(max_calls=10, period=1.0),
    bulkhead=BulkheadConfig(max_concurrent=5),
    fallback=FallbackConfig(handler=lambda e: {"user": "unknown", "source": "fallback"}),
    listeners=[logger, metrics],
)
def get_user(user_id: int) -> dict:
    """Simulates fetching a user from an external API."""
    # Simulate occasional failures
    if random.random() < 0.3:
        raise ConnectionError("Service unavailable")
    # Simulate variable latency
    time.sleep(random.uniform(0.01, 0.1))
    return {"user_id": user_id, "name": f"User {user_id}", "source": "api"}


if __name__ == "__main__":
    print("Fetching users with full resilience stack...\n")

    for i in range(10):
        result = get_user(i % 3)  # Only 3 unique users to test caching
        print(f"get_user({i % 3}): {result}")

    print("\n--- Metrics Summary ---")
    summary = metrics.summary()
    for key, value in summary.items():
        print(f"  {key}: {value}")
