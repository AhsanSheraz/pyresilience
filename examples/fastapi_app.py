"""FastAPI integration example.

Run with: uvicorn examples.fastapi_app:app --reload

Requires: pip install fastapi uvicorn
"""

from __future__ import annotations

from pyresilience import (
    CircuitBreakerConfig,
    RateLimiterConfig,
    ResilienceConfig,
    RetryConfig,
    TimeoutConfig,
)
from pyresilience.contrib.fastapi import ResilientDependency

# Create resilience configs for different services
payment_resilience = ResilientDependency(
    ResilienceConfig(
        retry=RetryConfig(max_attempts=3, delay=0.5),
        timeout=TimeoutConfig(seconds=10),
        circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
        rate_limiter=RateLimiterConfig(max_calls=100, period=60.0),
    )
)


async def _fetch_user(user_id: int) -> dict:
    """Simulate fetching a user from a database."""
    return {"id": user_id, "name": f"User {user_id}"}


async def _charge_payment(amount: float) -> dict:
    """Simulate charging a payment."""
    return {"status": "charged", "amount": amount}


def create_app():  # type: ignore[no-untyped-def]
    """Create the FastAPI app. Import FastAPI only if available."""
    try:
        from fastapi import Depends, FastAPI
    except ImportError:
        print("FastAPI not installed. Run: pip install fastapi")
        return None

    app = FastAPI(title="pyresilience FastAPI Example")

    @app.get("/users/{user_id}")
    async def get_user(
        user_id: int,
        resilience: ResilientDependency = Depends(payment_resilience),
    ) -> dict:
        return await resilience.call(_fetch_user, user_id)

    @app.post("/payments/charge")
    async def charge(
        amount: float = 100.0,
        resilience: ResilientDependency = Depends(payment_resilience),
    ) -> dict:
        return await resilience.call(_charge_payment, amount)

    return app


app = create_app()
