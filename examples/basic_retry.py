"""Basic retry example — retries a flaky function with exponential backoff."""

import random

from pyresilience import resilient, RetryConfig


@resilient(
    retry=RetryConfig(
        max_attempts=5,
        delay=0.5,
        backoff_factor=2.0,
        jitter=True,
    )
)
def flaky_api_call() -> str:
    """Simulates a flaky API that fails 60% of the time."""
    if random.random() < 0.6:
        raise ConnectionError("Service temporarily unavailable")
    return "Success!"


if __name__ == "__main__":
    try:
        result = flaky_api_call()
        print(f"Result: {result}")
    except ConnectionError as e:
        print(f"Failed after all retries: {e}")
