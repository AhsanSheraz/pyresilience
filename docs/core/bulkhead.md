# Bulkhead

The bulkhead pattern limits the number of concurrent executions to prevent resource exhaustion. Named after the compartments in a ship's hull that prevent a single breach from sinking the entire vessel.

## Concepts

A bulkhead acts as a semaphore that limits how many calls can execute simultaneously:

```
                    Bulkhead (max_concurrent=3)
                    ┌──────────────────────────┐
Request 1 ────────> │  Slot 1: [executing]     │
Request 2 ────────> │  Slot 2: [executing]     │
Request 3 ────────> │  Slot 3: [executing]     │
                    └──────────────────────────┘
Request 4 ────────> REJECTED (BulkheadFullError)
```

This prevents a single slow dependency from consuming all available threads/connections in your application.

## Configuration

```python
from pyresilience import BulkheadConfig

config = BulkheadConfig(
    max_concurrent=10,  # Allow up to 10 concurrent executions
    max_wait=0.0,       # Fail immediately if no slot available (0 = no waiting)
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_concurrent` | `int` | `10` | Maximum number of concurrent executions |
| `max_wait` | `float` | `0.0` | Maximum seconds to wait for a slot. `0` means fail immediately. |

## Usage

### Basic Bulkhead

```python
from pyresilience import resilient, BulkheadConfig

@resilient(bulkhead=BulkheadConfig(max_concurrent=5))
def query_database(sql: str) -> list:
    return cursor.execute(sql).fetchall()
```

If more than 5 calls are in progress, new calls raise `BulkheadFullError`.

### With Waiting

Allow callers to wait briefly for a slot:

```python
@resilient(bulkhead=BulkheadConfig(max_concurrent=10, max_wait=5.0))
def call_api() -> dict:
    return requests.get("https://api.example.com").json()
```

Callers wait up to 5 seconds for a slot. If no slot opens, `BulkheadFullError` is raised.

### With Fallback

Return a degraded response instead of raising:

```python
from pyresilience import resilient, BulkheadConfig, FallbackConfig, BulkheadFullError

@resilient(
    bulkhead=BulkheadConfig(max_concurrent=10),
    fallback=FallbackConfig(
        handler=lambda e: {"status": "busy", "retry_after": 5},
        fallback_on=(BulkheadFullError,),
    ),
)
def get_data() -> dict:
    return requests.get("https://api.example.com/data").json()
```

### Protecting Database Connection Pools

```python
@resilient(bulkhead=BulkheadConfig(max_concurrent=20, max_wait=3.0))
def db_query(sql: str) -> list:
    with connection_pool.get_connection() as conn:
        return conn.execute(sql).fetchall()
```

## Events

| Event | When |
|-------|------|
| `EventType.BULKHEAD_REJECTED` | A call was rejected because the bulkhead is full |

## Exception

```python
from pyresilience import BulkheadFullError

try:
    result = my_function()
except BulkheadFullError:
    # No concurrent slots available
    return fallback_response()
```
