"""Registry example — shared circuit breaker across multiple functions."""

from pyresilience import (
    CircuitBreakerConfig,
    ResilienceConfig,
    ResilienceRegistry,
    RetryConfig,
)

# Create a registry
registry = ResilienceRegistry()

# Register a config — all functions using "payment-api" share the same circuit breaker
registry.register(
    "payment-api",
    ResilienceConfig(
        retry=RetryConfig(max_attempts=2),
        circuit_breaker=CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=10.0,
        ),
    ),
)


@registry.decorator("payment-api")
def charge_card(amount: float) -> dict:
    raise ConnectionError("Payment service is down")


@registry.decorator("payment-api")
def refund_card(amount: float) -> dict:
    return {"status": "refunded", "amount": amount}


if __name__ == "__main__":
    print("Demonstrating shared circuit breaker state...\n")

    # Trip the circuit breaker with charge_card failures
    for i in range(4):
        try:
            charge_card(100.0)
        except (ConnectionError, RuntimeError) as e:
            print(f"charge_card attempt {i + 1}: {e}")

    # Now refund_card is ALSO blocked because they share the circuit breaker
    print()
    try:
        result = refund_card(50.0)
        print(f"refund_card: {result}")
    except RuntimeError as e:
        print(f"refund_card blocked: {e}")
        print("\n(Circuit breaker is shared — charge_card failures blocked refund_card too)")
