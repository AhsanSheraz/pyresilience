# Shared State

By default every process keeps its own circuit breaker, rate limits and retry budget. That is correct for one process and wrong for a fleet: with five replicas, a limit of 100 calls per minute becomes 500, and a circuit breaker with `failure_threshold=5` lets 25 failures through before any replica opens.

`SharedStateConfig` stores that state in a **backend** so that all processes act as one.

## Quick Start

```python
import redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from pyresilience import (
    resilient, CircuitBreakerConfig, RateLimiterConfig, RetryBudgetConfig,
    RetryConfig, SharedStateConfig,
)
from pyresilience.contrib.redis import RedisBackend

client = redis.Redis(
    host="localhost",
    port=6379,
    socket_connect_timeout=0.5,   # rate-limited calls wait for this client,
    socket_timeout=0.5,           # so keep its timeouts short
    retry=Retry(NoBackoff(), 0),  # and switch off its own retries
)
shared = SharedStateConfig(backend=RedisBackend(client), key="payment-api")

@resilient(
    retry=RetryConfig(max_attempts=3),
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
    rate_limiter=RateLimiterConfig(max_calls=100, period=60.0),
    retry_budget=RetryBudgetConfig(max_retries=50, refill_rate=5.0),
    shared_state=shared,
)
def charge(amount: float) -> dict:
    return payment_client.charge(amount)
```

Every process that runs this code with the same backend and `key` now shares one rate limit, one circuit breaker and one retry budget.

pyresilience does not depend on a Redis library. `RedisBackend` takes the client you already use; any client with redis-py's synchronous API works.

## What Is Shared, and How

| Pattern | Shared | Mechanism | Accuracy |
|---|---|---|---|
| Rate limiter | Yes | Every call is counted in the backend (atomic increment of a fixed window) | Acquisitions never exceed a window; corrections are conservative |
| Circuit breaker | Yes | Background pass every `sync_interval` seconds | Open state arrives within two passes: one publishes it, one adopts it |
| Retry budget | Yes | Background pass every `sync_interval` seconds | Converges on one budget; a burst shorter than a pass is not capped |
| Fallback cooldown | No | In-process | — |
| Bulkhead | No | In-process | — |
| Cache | No | In-process | — |

### Rate limiter

Each acquisition increments a counter for the current window (`period` seconds long) in the backend. The increment is atomic, so all processes together cannot exceed the limit of a window. The local token bucket still applies first, so a single process stays within the limit on its own, also while the backend is down.

- Weighted costs, several limits and reconciliation with the real cost all carry over to the shared counters.
- One backend round trip per call (plus one per additional limit). For async functions the round trip runs in a worker thread, so the event loop is not blocked.
- Shared windows are fixed windows aligned to the wall clock; the local limiter is a token bucket.
- Fixed windows can pass up to twice the limit across a boundary: a full window at the end of one period and another at the start of the next. If the provider enforces a rolling window, set the limit with that in mind.
- A correction after the call (`actual_cost`) goes to the window the call was counted in. If that window has already passed, unused units are not given back, because the later window never held them. Usage above the estimate is charged to the current window.
- A pause from server feedback (`Retry-After`) applies to the process that received it. Other processes learn the same from their own responses.

### Circuit breaker

Every process keeps deciding locally, so a call never waits for the backend. A background pass exchanges:

- **The open state.** When one instance opens, the others open within two passes at most (one publishes the state, one adopts it) and recover at the same moment.
- **The failure streak** (consecutive-count mode). Failures of all instances add up, so `failure_threshold=5` means five failures across the fleet. A success on any instance ends the shared streak. The streak is exchanged once per pass, so the exact order of failures and successes between instances inside one interval is not preserved.

Sliding-window breakers share only the open state: a failure rate is the same on every instance and needs no adding up.

!!! note "Shared state means shared fate"
    An instance that cannot reach the dependency because of its own network problem will open the circuit for everyone. Use `ignore_on` for errors that say nothing about the dependency's health.

### Retry budget

Each pass publishes the retries a process spent and debits the retries the others spent. Over time the fleet converges on one budget. Between two passes each process still spends what it believed it had, so a burst of retries that is shorter than `sync_interval` is limited by every process's own budget, not by the shared one. Use a short `sync_interval` when retry storms are the concern.

## Configuration

```python
from pyresilience import SharedStateConfig

SharedStateConfig(
    backend=backend,      # where the state lives
    key="payment-api",    # name of the state in the backend
    sync_interval=1.0,    # seconds between background passes
    fail_open=True,       # behaviour of rate limiting while the backend is down
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `backend` | `StateBackend` | required | `InMemoryBackend()`, `RedisBackend(client)` or your own |
| `key` | `str` | `""` | Everything using the same backend and key shares state. Defaults to the registry name, or to `module.qualname` of the function decorated with `@resilient` |
| `sync_interval` | `float` | `1.0` | Seconds between background passes for circuit breaker and retry budget. `0` starts no thread; call `sync_now()` yourself |
| `fail_open` | `bool` | `True` | While the backend cannot be reached: `True` keeps rate limiting on the local limit, `False` rejects calls |

Set an explicit `key`:

- when the default would differ between deployments of the same service, for example when the function lives in a module that is imported under different names;
- for functions created inside a factory or closure, which would otherwise all share one default key;
- with the FastAPI, Django and Flask integrations, which have no function path to derive a key from. Leaving it empty there raises `ValueError`.

## When the Backend Is Down

A backend failure never raises into your call.

| Pattern | `fail_open=True` (default) | `fail_open=False` |
|---|---|---|
| Rate limiter | Calls proceed on this process's local limit | Calls are rejected with `RateLimitExceededError` |
| Circuit breaker | Keeps working on local state | Same |
| Retry budget | Keeps working on local state | Same |

The first failure of an outage is logged as a warning on the `pyresilience` logger, the following ones at debug level.

After a failed backend call, rate limiting leaves the backend alone for `sync_interval` seconds (at least one second) and answers at once according to `fail_open`. When that pause is over, one call tries the backend again. While it is trying, the other calls keep being answered at once, so one call at a time waits for a backend that is down, however long the client takes to give up. If that call has not come back after 30 seconds, another one tries.

That one call still waits for the client to give up, and so does every call that was already talking to the backend when it went down. Give the client you pass to `RedisBackend` short timeouts (`socket_connect_timeout`, `socket_timeout`) and few or no retries of its own, as the Quick Start does: the client's defaults can add up to many seconds.

## With the Registry

Put `shared_state` in the registered config. The registry name becomes the key:

```python
registry = ResilienceRegistry()
registry.register("payment-api", ResilienceConfig(
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
    rate_limiter=RateLimiterConfig(max_calls=100, period=60.0),
    shared_state=SharedStateConfig(backend=RedisBackend(client)),
))

@registry.decorator("payment-api")
def charge(amount: float) -> dict: ...
```

Without a backend, a registry name already shares circuit breaker, rate limits, retry budget and fallback cooldown between the sync and async functions of one process. See [Registry](registry.md).

## Backends

### InMemoryBackend

Keeps the state in process memory. It shares state between separate `@resilient` functions and registries of one process, and replaces a real backend in tests:

```python
from pyresilience import InMemoryBackend, SharedStateConfig

backend = InMemoryBackend()
shared = SharedStateConfig(backend=backend, key="svc", sync_interval=0)

# ... exercise the functions ...
shared.sync_now()   # run one pass deterministically
```

### RedisBackend

```python
from pyresilience.contrib.redis import RedisBackend

backend = RedisBackend(redis.Redis.from_url("redis://localhost:6379/0"), prefix="myapp:")
```

It uses `GET`, `SET` with `PX`, `INCRBYFLOAT`, `PEXPIRE` and `DEL`. Keys are written with an expiry, so abandoned state cleans itself up. Increment and expiry travel in one pipeline (one round trip) when the client offers `pipeline()`.

### Writing Your Own

A backend is any object with these four methods. `incr` must be atomic.

```python
from typing import Optional

class MyBackend:
    def get(self, key: str) -> Optional[str]: ...
    def set(self, key: str, value: str, ttl: Optional[float] = None) -> None: ...
    def incr(self, key: str, amount: float, ttl: Optional[float] = None) -> float: ...
    def delete(self, key: str) -> None: ...
```

`isinstance(MyBackend(), pyresilience.StateBackend)` is `True` for any object with these methods.

## Things to Know

- **Clocks.** Shared timestamps use the wall clock. Clock skew between hosts shifts the shared recovery moment of a circuit breaker and the window boundaries of a rate limit by the skew. Keep hosts on NTP.
- **Manual control.** `reset()`, `force_open()` and `force_close()` act on the local breaker. A reset also clears the shared record at the next pass; instances that already adopted the open state stay open until their recovery time.
- **Background thread.** One daemon thread per `SharedStateConfig` runs the passes. It stops when nothing uses the config any more.
- **Forked workers.** Threads do not survive `fork()`. A forked child (gunicorn with `--preload`, Celery's prefork pool, `multiprocessing` with the fork start method) starts its own background thread automatically, so functions decorated before the fork keep syncing. uWSGI forks its workers without running Python's fork hooks, so there the thread is not restarted and the workers do not sync: start uWSGI with `py-call-osafterfork = true` or `lazy-apps = true`. Also set `enable-threads = true`, as uWSGI's documentation requires for threads the application starts.
- **Latency.** Only rate limiting adds a backend round trip to the call. Circuit breaker and retry budget cost nothing on the call path.
