"""Presets example — use opinionated defaults instead of manual configuration."""

import random
import time

from pyresilience import resilient
from pyresilience.presets import db_policy, http_policy, queue_policy, strict_policy


@resilient(**http_policy())
def call_http_api() -> dict:
    """HTTP API call with sensible defaults: 10s timeout, 3 retries, circuit breaker."""
    if random.random() < 0.5:
        raise ConnectionError("API unavailable")
    return {"status": "ok"}


@resilient(**db_policy())
def query_database() -> list:
    """Database query with: 30s timeout, 2 retries, bulkhead of 10, circuit breaker."""
    time.sleep(0.01)
    return [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]


@resilient(**queue_policy())
def publish_to_queue(message: str) -> bool:
    """Queue publish with: 15s timeout, 5 retries, high failure tolerance."""
    if random.random() < 0.3:
        raise ConnectionError("Broker unavailable")
    return True


@resilient(**strict_policy())
def cache_lookup(key: str) -> str:
    """Cache lookup with strict policy: 5s timeout, 1 retry, fail fast."""
    return f"cached_value_for_{key}"


if __name__ == "__main__":
    print("=== HTTP Policy ===")
    try:
        print(f"Result: {call_http_api()}")
    except Exception as e:
        print(f"Failed: {e}")

    print("\n=== DB Policy ===")
    print(f"Result: {query_database()}")

    print("\n=== Queue Policy ===")
    try:
        print(f"Published: {publish_to_queue('hello')}")
    except Exception as e:
        print(f"Failed: {e}")

    print("\n=== Strict Policy ===")
    print(f"Result: {cache_lookup('user:42')}")
