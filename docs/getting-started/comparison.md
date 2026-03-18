# Comparison with Other Libraries

## Python Ecosystem

| Feature | pyresilience | tenacity | backoff | pybreaker | stamina |
|---------|-------------|----------|---------|-----------|---------|
| Retry | Yes | Yes | Yes | No | Yes |
| Circuit Breaker | Yes | No | No | Yes | No |
| Timeout | Yes | No | No | No | No |
| Fallback | Yes | No | No | No | No |
| Bulkhead | Yes | No | No | No | No |
| Rate Limiter | Yes | No | No | No | No |
| Cache | Yes | No | No | No | No |
| Registry | Yes | No | No | No | No |
| Unified API | Yes | N/A | N/A | N/A | N/A |
| Async Support | Yes | Yes | Yes | No | Yes |
| Zero Dependencies | Yes | Yes | No | No | No |
| Type-Safe | Yes | Partial | Partial | No | Yes |

## vs Resilience4j (Java)

pyresilience provides complete feature parity with Resilience4j's core modules:

| Resilience4j | pyresilience | Notes |
|-------------|-------------|-------|
| `CircuitBreaker` | `CircuitBreakerConfig` | Same state machine: CLOSED -> OPEN -> HALF_OPEN |
| `Retry` | `RetryConfig` | Exponential backoff, jitter, configurable exceptions |
| `Bulkhead` | `BulkheadConfig` | Semaphore-based (like Resilience4j's `SemaphoreBulkhead`) |
| `TimeLimiter` | `TimeoutConfig` | Thread-based (sync) and `asyncio.wait_for` (async) |
| `RateLimiter` | `RateLimiterConfig` | Token bucket (similar to Resilience4j's `AtomicRateLimiter`) |
| `Cache` | `CacheConfig` | LRU with TTL (like JCache integration) |
| `CircuitBreakerRegistry` | `ResilienceRegistry` | Centralized management of named instances |

### Key Differences

**Decorator composition**: In Resilience4j, you compose decorators manually:

```java
// Java — Resilience4j
Supplier<String> supplier = () -> service.call();
supplier = Decorators.ofSupplier(supplier)
    .withRetry(retry)
    .withCircuitBreaker(circuitBreaker)
    .withRateLimiter(rateLimiter)
    .get();
```

In pyresilience, everything is one decorator:

```python
# Python — pyresilience
@resilient(
    retry=RetryConfig(max_attempts=3),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
    rate_limiter=RateLimiterConfig(max_calls=10, period=1.0),
)
def call_service() -> str:
    return service.call()
```

**Registry**: Resilience4j uses separate registries per pattern (`CircuitBreakerRegistry`, `RetryRegistry`, etc.). pyresilience uses a single `ResilienceRegistry` that manages the complete config:

```python
registry = ResilienceRegistry()
registry.register("payment-api", ResilienceConfig(
    retry=RetryConfig(max_attempts=3),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
))

# Multiple functions share the same circuit breaker
@registry.decorator("payment-api")
def charge(): ...

@registry.decorator("payment-api")
def refund(): ...
```

## When to Use pyresilience

**Use pyresilience when you need:**

- Multiple resilience patterns working together
- A single, clean API instead of stacking decorators
- Consistent observability across all patterns
- Shared circuit breaker state across functions
- Production presets for common integration patterns

**Use tenacity when you only need:**

- Retry logic and nothing else
- Very fine-grained retry control (tenacity has more retry options)

**Use pybreaker when you only need:**

- A standalone circuit breaker with no other patterns
