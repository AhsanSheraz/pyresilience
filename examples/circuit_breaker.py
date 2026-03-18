"""Circuit breaker example — stops calling a failing service."""

from pyresilience import (
    CircuitBreakerConfig,
    FallbackConfig,
    ResilienceEvent,
    resilient,
)


def on_event(event: ResilienceEvent) -> None:
    print(f"  [{event.event_type.value}] {event.function_name} {event.detail}")


@resilient(
    circuit_breaker=CircuitBreakerConfig(
        failure_threshold=3,
        recovery_timeout=5.0,
        success_threshold=1,
    ),
    fallback=FallbackConfig(handler=lambda e: {"status": "degraded", "source": "cache"}),
    listeners=[on_event],
)
def call_service() -> dict:
    """Simulates a service that is always down."""
    raise ConnectionError("Service is down")


if __name__ == "__main__":
    print("Calling a failing service 5 times...")
    for i in range(5):
        result = call_service()
        print(f"Call {i + 1}: {result}")

    print("\nCircuit is now open — calls fail fast without hitting the service.")
