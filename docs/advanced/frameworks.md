# Framework Integrations

pyresilience provides built-in integrations for the most popular Python web frameworks.

## FastAPI

### Dependency Injection (Recommended)

Use `ResilientDependency` with FastAPI's `Depends()` for per-route resilience:

```python
from fastapi import Depends, FastAPI
from pyresilience import ResilienceConfig, RetryConfig, CircuitBreakerConfig
from pyresilience.contrib.fastapi import ResilientDependency

app = FastAPI()

# Create a resilience dependency for the payment service
payment_resilience = ResilientDependency(ResilienceConfig(
    retry=RetryConfig(max_attempts=3),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
))

@app.post("/charge")
async def charge(
    amount: float,
    resilience: ResilientDependency = Depends(payment_resilience),
):
    return await resilience.call(payment_service.charge, amount)

@app.post("/refund")
async def refund(
    amount: float,
    resilience: ResilientDependency = Depends(payment_resilience),
):
    return await resilience.call(payment_service.refund, amount)
```

### ASGI Middleware

Apply resilience to the entire request pipeline:

```python
from fastapi import FastAPI
from pyresilience import ResilienceConfig, TimeoutConfig, CircuitBreakerConfig
from pyresilience.contrib.fastapi import ResilientMiddleware

app = FastAPI()
app.add_middleware(
    ResilientMiddleware,
    config=ResilienceConfig(
        timeout=TimeoutConfig(seconds=30),
        circuit_breaker=CircuitBreakerConfig(failure_threshold=10),
    ),
)
```

### Factory Function

For convenience:

```python
from pyresilience.contrib.fastapi import resilient_dependency

payment_dep = resilient_dependency(ResilienceConfig(
    retry=RetryConfig(max_attempts=3),
))

@app.post("/charge")
async def charge(resilience=Depends(payment_dep)):
    return await resilience.call(charge_service, amount=100)
```

## Django

### Middleware

Apply resilience to all Django views:

```python
# settings.py
MIDDLEWARE = [
    # ... other middleware
    'pyresilience.contrib.django.ResilientMiddleware',
]

PYRESILIENCE_CONFIG = {
    'timeout_seconds': 30,
    'circuit_failure_threshold': 10,
    'circuit_recovery_seconds': 60,
    'max_attempts': 3,
    'retry_delay': 1.0,
}
```

### Per-View Decorator

Apply resilience to specific views:

```python
from pyresilience.contrib.django import resilient_view
from pyresilience import RetryConfig, TimeoutConfig, CircuitBreakerConfig

@resilient_view(
    retry=RetryConfig(max_attempts=3),
    timeout=TimeoutConfig(seconds=10),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
)
def payment_view(request):
    result = payment_service.charge(request.POST['amount'])
    return JsonResponse(result)
```

## Flask

### Extension

Apply resilience to your entire Flask app:

```python
from flask import Flask
from pyresilience import ResilienceConfig, TimeoutConfig, CircuitBreakerConfig
from pyresilience.contrib.flask import Resilience

app = Flask(__name__)
resilience = Resilience(app, config=ResilienceConfig(
    timeout=TimeoutConfig(seconds=30),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=10),
))

# Use directly in views:
@app.route("/data")
def get_data():
    return resilience.call(external_api.get_data)
```

### Factory Pattern

```python
resilience = Resilience()

def create_app():
    app = Flask(__name__)
    resilience.init_app(app, config=ResilienceConfig(...))
    return app
```

### Per-Route Decorator

```python
from pyresilience.contrib.flask import resilient_route
from pyresilience import RetryConfig, TimeoutConfig

@app.route("/data")
@resilient_route(
    retry=RetryConfig(max_attempts=3),
    timeout=TimeoutConfig(seconds=10),
)
def get_data():
    return external_api.get_data()
```

## Using Without Integrations

You can always use pyresilience directly with any framework:

```python
from pyresilience import resilient, RetryConfig

@resilient(retry=RetryConfig(max_attempts=3))
async def my_service_call():
    return await http_client.get("/api/data")
```

The framework integrations are convenience wrappers — the core `@resilient()` decorator works everywhere.

!!! tip "Async Fallback Handlers"
    When using async frameworks (FastAPI, async Django), your `FallbackConfig.handler` can be an async function. pyresilience detects this automatically and awaits the handler:

    ```python
    async def async_fallback(exc: Exception) -> dict:
        return {"status": "degraded", "error": str(exc)}

    @resilient(
        fallback=FallbackConfig(handler=async_fallback, fallback_on=(Exception,)),
    )
    async def my_endpoint():
        return await external_service.call()
    ```
