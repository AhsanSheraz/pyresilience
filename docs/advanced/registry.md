# Registry

The registry provides centralized management of named resilience configurations. Multiple functions decorated with the same registry name share the same circuit breaker, rate limiter, and other stateful components — just like Resilience4j's `CircuitBreakerRegistry`.

## Concepts

Without a registry, each `@resilient()` call creates its own independent circuit breaker:

```python
# These have SEPARATE circuit breakers — one can be open while the other is closed
@resilient(circuit_breaker=CircuitBreakerConfig(failure_threshold=5))
def charge_card(): ...

@resilient(circuit_breaker=CircuitBreakerConfig(failure_threshold=5))
def refund_card(): ...
```

With a registry, they **share state**:

```python
registry = ResilienceRegistry()
registry.register("payment-api", ResilienceConfig(
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
))

# These SHARE the same circuit breaker
@registry.decorator("payment-api")
def charge_card(): ...

@registry.decorator("payment-api")
def refund_card(): ...

# If charge_card trips the circuit, refund_card is also blocked
```

## Usage

### Basic Registry

```python
from pyresilience import ResilienceRegistry, ResilienceConfig, RetryConfig, CircuitBreakerConfig

registry = ResilienceRegistry()

# Register named configurations
registry.register("payment-api", ResilienceConfig(
    retry=RetryConfig(max_attempts=3),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5, recovery_timeout=30),
))

registry.register("inventory-api", ResilienceConfig(
    retry=RetryConfig(max_attempts=2),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=3, recovery_timeout=60),
))

# Decorate functions
@registry.decorator("payment-api")
async def charge_card(amount: float) -> dict:
    return await payment_client.charge(amount)

@registry.decorator("payment-api")
async def refund_card(amount: float) -> dict:
    return await payment_client.refund(amount)

@registry.decorator("inventory-api")
async def check_stock(item_id: str) -> int:
    return await inventory_client.get_stock(item_id)
```

### Default Configuration

Set a default config for unregistered names:

```python
registry = ResilienceRegistry()
registry.set_default(ResilienceConfig(
    retry=RetryConfig(max_attempts=2),
    timeout=TimeoutConfig(seconds=10),
))

# Uses the default config since "analytics-api" isn't registered
@registry.decorator("analytics-api")
def track_event(event: dict) -> None:
    analytics_client.track(event)
```

### Querying the Registry

```python
# Get a specific config
config = registry.get("payment-api")

# Get config with fallback to default
config = registry.get_or_default("unknown-api")

# List all registered names
names = registry.names  # ["payment-api", "inventory-api"]

# Remove a config
registry.unregister("payment-api")

# Clear everything
registry.clear()
```

### Dynamic Registration

Register configs at application startup:

```python
# config.py
from pyresilience import ResilienceRegistry, ResilienceConfig, RetryConfig, CircuitBreakerConfig

registry = ResilienceRegistry()

def configure_resilience():
    """Call this at application startup."""
    registry.register("payment-api", ResilienceConfig(
        retry=RetryConfig(max_attempts=3),
        circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
    ))
    registry.register("user-api", ResilienceConfig(
        retry=RetryConfig(max_attempts=2),
        timeout=TimeoutConfig(seconds=5),
    ))
```

```python
# services.py
from config import registry

@registry.decorator("payment-api")
async def charge(amount: float) -> dict: ...

@registry.decorator("user-api")
async def get_user(user_id: int) -> dict: ...
```

```python
# main.py
from config import configure_resilience

configure_resilience()
# Now all decorated functions use the registered configs
```

## Shared State

The key benefit of the registry is **shared state**. Functions using the same registry name share:

- **Circuit breaker state** — if one function trips the circuit, all functions under the same name are blocked
- **Rate limiter tokens** — all functions share the same token bucket
- **Bulkhead slots** — concurrent calls across all functions count toward the same limit

This models real-world dependencies: if the payment API is down, all payment operations should fail fast — not just the one that discovered the failure.

## Sync and Async

The registry handles both sync and async functions transparently:

```python
@registry.decorator("payment-api")
def sync_charge(amount: float) -> dict:
    return payment_client.charge(amount)

@registry.decorator("payment-api")
async def async_charge(amount: float) -> dict:
    return await payment_client.async_charge(amount)
```

!!! note
    Sync and async executors are created separately, so they have independent circuit breaker instances even under the same registry name. This is intentional — sync and async code paths typically run in different contexts.
