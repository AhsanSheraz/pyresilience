# Observability

pyresilience provides a unified event system for monitoring all resilience patterns. Every retry, timeout, circuit state change, and rejection emits an event that you can observe, log, and measure.

## Event System

Every resilience action emits a `ResilienceEvent`:

```python
from pyresilience import ResilienceEvent, EventType

@dataclass(frozen=True)
class ResilienceEvent:
    event_type: EventType        # What happened
    function_name: str           # Which function
    attempt: int = 0             # Current attempt number
    error: BaseException = None  # The exception, if any
    detail: str = ""             # Additional context
    context: Optional[dict] = None  # Request-scoped metadata (from resilience_context)
```

### Event Types

| Event | When Emitted |
|-------|-------------|
| `RETRY` | A retry attempt is about to be made |
| `RETRY_EXHAUSTED` | All retry attempts have been used |
| `TIMEOUT` | A call exceeded its time limit |
| `CIRCUIT_OPEN` | Circuit breaker opened or rejected a call |
| `CIRCUIT_HALF_OPEN` | Circuit breaker entered half-open state |
| `CIRCUIT_CLOSED` | Circuit breaker closed (recovered) |
| `FALLBACK_USED` | A fallback value was returned |
| `BULKHEAD_REJECTED` | A call was rejected by the bulkhead |
| `RATE_LIMITED` | A call was rejected by the rate limiter |
| `CACHE_HIT` | A cached result was returned |
| `CACHE_MISS` | No cache entry found |
| `SUCCESS` | The call succeeded |
| `FAILURE` | The call failed (non-retryable or exhausted) |
| `SLOW_CALL` | A call exceeded the slow call duration threshold |

## Context Propagation

Use `resilience_context` to attach request-scoped metadata to every event. This is useful for correlating resilience events with traces, users, or requests.

```python
from pyresilience import resilience_context

# Set context for the current async task / thread
resilience_context.set({"trace_id": "abc-123", "user_id": "u-456"})

# All events emitted during this context will include:
# event.context == {"trace_id": "abc-123", "user_id": "u-456"}
```

In a web framework, set the context in middleware:

```python
@app.middleware("http")
async def add_resilience_context(request, call_next):
    resilience_context.set({
        "trace_id": request.headers.get("x-trace-id"),
        "path": request.url.path,
    })
    return await call_next(request)
```

## Custom Listeners

A listener is any callable that accepts a `ResilienceEvent`:

```python
from pyresilience import resilient, RetryConfig, ResilienceEvent

def my_listener(event: ResilienceEvent) -> None:
    print(f"[{event.event_type.value}] {event.function_name} "
          f"attempt={event.attempt} {event.detail}")

@resilient(
    retry=RetryConfig(max_attempts=3),
    listeners=[my_listener],
)
def my_function():
    return do_work()
```

You can attach multiple listeners:

```python
@resilient(
    retry=RetryConfig(max_attempts=3),
    listeners=[logger, metrics, alerter],
)
def critical_function():
    ...
```

!!! note
    Listener exceptions are logged as warnings (via `logging.warning()`) to prevent broken observability from being silently swallowed, while still protecting the application from listener failures.

## JsonEventLogger

Structured JSON logging out of the box:

```python
from pyresilience import resilient, RetryConfig, JsonEventLogger

logger = JsonEventLogger()  # Uses Python's logging module

@resilient(retry=RetryConfig(max_attempts=3), listeners=[logger])
def my_function():
    return do_work()
```

Output:

```json
{"event_type": "retry", "function_name": "my_function", "attempt": 1, "detail": "retrying in 1.00s", "error_type": "ConnectionError", "error_message": "Connection refused"}
{"event_type": "success", "function_name": "my_function", "attempt": 2}
```

### Custom Logger

```python
import logging

my_logger = logging.getLogger("resilience")
json_logger = JsonEventLogger(logger=my_logger, level=logging.WARNING)
```

### Performance

`JsonEventLogger` automatically uses `orjson` if installed for ~10x faster JSON serialization:

```bash
pip install pyresilience[fast]
```

## MetricsCollector

In-memory metrics collection for dashboards and health checks:

```python
from pyresilience import resilient, RetryConfig, MetricsCollector

metrics = MetricsCollector()

@resilient(retry=RetryConfig(max_attempts=3), listeners=[metrics])
def my_function():
    return do_work()

# After some calls:
summary = metrics.summary()
```

### Summary Output

```python
{
    "total_events": 150,
    "event_counts": {
        "success": 120,
        "retry": 25,
        "failure": 5,
    },
    "success_rate": 0.8,
    "functions": {
        "my_function": {
            "total": 150,
            "success": 120,
            "failure": 5,
        }
    }
}
```

### Per-Function Metrics

```python
# Counts for a specific function
counts = metrics.get_counts("my_function")
# {"success": 120, "retry": 25, "failure": 5, ...}

# Latency percentiles
latencies = metrics.get_latencies("my_function")
# {"p50": 0.15, "p95": 0.89, "p99": 1.23, "min": 0.01, "max": 2.1}

# Reset all metrics
metrics.reset()
```

### Integration with Monitoring Systems

Export metrics to Prometheus, Datadog, etc.:

```python
from pyresilience import MetricsCollector

metrics = MetricsCollector()

# In your health check / metrics endpoint:
@app.get("/metrics")
def get_metrics():
    return metrics.summary()
```

## Alerting Example

```python
from pyresilience import EventType

def alert_on_circuit_open(event):
    if event.event_type == EventType.CIRCUIT_OPEN:
        send_slack_alert(
            f"Circuit breaker opened for {event.function_name}: {event.error}"
        )
    elif event.event_type == EventType.CIRCUIT_CLOSED:
        send_slack_alert(
            f"Circuit breaker recovered for {event.function_name}"
        )

@resilient(
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
    listeners=[json_logger, metrics, alert_on_circuit_open],
)
def payment_service():
    ...
```

## OpenTelemetry

`OpenTelemetryListener` emits spans and attributes for each resilience event, integrating with the OpenTelemetry SDK.

```python
from pyresilience import resilient, RetryConfig
from pyresilience.logging import OpenTelemetryListener

otel = OpenTelemetryListener()

@resilient(retry=RetryConfig(max_attempts=3), listeners=[otel])
def call_api():
    return requests.get("https://api.example.com").json()
```

Each event creates a span with attributes like `resilience.event_type`, `resilience.function_name`, `resilience.attempt`, and `resilience.context.*` (from `resilience_context`).

!!! note
    Requires the `opentelemetry-api` package. Install with `pip install opentelemetry-api opentelemetry-sdk`.

## Prometheus

`PrometheusListener` exports counters, histograms, and gauges to Prometheus via the official client library.

```python
from pyresilience import resilient, RetryConfig
from pyresilience.logging import PrometheusListener

prom = PrometheusListener(namespace="myapp")

@resilient(retry=RetryConfig(max_attempts=3), listeners=[prom])
def call_api():
    return requests.get("https://api.example.com").json()
```

Exported metrics:

| Metric | Type | Description |
|--------|------|-------------|
| `myapp_resilience_events_total` | Counter | Total events by type and function |
| `myapp_resilience_latency_seconds` | Histogram | Call latency by function |
| `myapp_resilience_circuit_state` | Gauge | Circuit breaker state (0=closed, 1=open, 2=half-open) |

!!! note
    Requires the `prometheus-client` package. Install with `pip install prometheus-client`.

## Health Check

`health_check()` returns a summary of resilience state for all registered functions in a registry:

```python
from pyresilience import ResilienceRegistry, health_check

registry = ResilienceRegistry()
# ... register configs and decorate functions ...

status = health_check(registry)
```

Returns a dict like:

```python
{
    "payment-api": {
        "circuit_breaker": "closed",
        "in_flight": 3,
        "rate_limiter_available": True,
    },
    "inventory-service": {
        "circuit_breaker": "open",
        "in_flight": 0,
        "rate_limiter_available": True,
    },
}
```

Expose it from your health endpoint:

```python
@app.get("/health/resilience")
def resilience_health():
    return health_check(registry)
```
