"""Fallback alternatives with cooldown — route around a provider that is down."""

import time

from pyresilience import EventType, FallbackConfig, ResilienceEvent, resilient

primary_calls = 0
primary_is_down = True


def ask_backup_model(prompt: str, *, max_tokens: int = 64) -> str:
    """Second provider. Receives exactly the arguments of the original call."""
    return f"[backup, max_tokens={max_tokens}] answer to: {prompt}"


def on_event(event: ResilienceEvent) -> None:
    if event.event_type in (EventType.COOLDOWN, EventType.FALLBACK_USED):
        print(f"    event: {event.event_type.value} {event.detail}")


@resilient(
    fallback=FallbackConfig(
        alternatives=[ask_backup_model],
        handler="No model is available right now.",
        cooldown=1.0,  # skip a failing provider for one second
        cooldown_threshold=2,  # after two failures in a row
    ),
    listeners=[on_event],
)
def ask(prompt: str, *, max_tokens: int = 64) -> str:
    global primary_calls
    primary_calls += 1
    if primary_is_down:
        raise ConnectionError("primary provider is down")
    return f"[primary] answer to: {prompt}"


if __name__ == "__main__":
    print("=== Primary is down ===")
    for index in range(4):
        print(f"call {index + 1}: {ask('What is a circuit breaker?', max_tokens=32)}")
    print(f"primary was called {primary_calls} times; later calls skipped it\n")

    print("=== Primary recovers, cooldown ends ===")
    primary_is_down = False
    time.sleep(1.1)
    print(f"call 5: {ask('What is a bulkhead?')}")
    print(f"primary was called {primary_calls} times in total")
