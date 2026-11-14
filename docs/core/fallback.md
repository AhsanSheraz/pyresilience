# Fallback

The fallback pattern decides what a caller gets when the protected call cannot succeed: a default value, the answer of another provider, or the original error.

## Concepts

A failing call walks down a chain until something produces a value:

```
call fails (retries exhausted, circuit open, rate limited, bulkhead full, deadline spent)
     |
     v
 [alternatives]  tried in order with the original arguments ── first success ──> return
     |
     all failed or none configured
     |
     v
 [handler]  static value or fn(exc) ──────────────────────────────────────────> return
     |
     none configured
     |
     v
 raise the last error
```

With a **cooldown**, a target that keeps failing is skipped for a while, so callers stop paying for a provider that is known to be down:

```
cooldown=30, cooldown_threshold=1

Call 1:  primary fails ──> backup answers        (primary starts cooling down)
Call 2:  primary skipped ─> backup answers        (no time lost on the primary)
...
30s later: primary is tried again
```

## Configuration

```python
from pyresilience import FallbackConfig

config = FallbackConfig(
    handler=None,                 # Static value, fn(exc), or async fn(exc)
    fallback_on=(Exception,),     # Errors that start the chain
    alternatives=(),              # Callables tried with the original arguments
    cooldown=0.0,                 # Seconds a failing target is skipped (0 = off)
    cooldown_threshold=1,         # Consecutive failures that start a cooldown
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `handler` | `Callable` or any value | `None` | Last resort: a static value, `fn(exc)`, or an async `fn(exc)` for async functions |
| `fallback_on` | `Sequence[Type[BaseException]]` | `(Exception,)` | Errors that start the fallback chain. Cleared to `()` when there is no handler and no alternative |
| `alternatives` | `Sequence[Callable]` | `()` | Callables tried in order with the original `*args, **kwargs`. The first success supplies the result |
| `cooldown` | `float` | `0.0` | Seconds a target is skipped after `cooldown_threshold` consecutive failures. `0` disables cooldown |
| `cooldown_threshold` | `int` | `1` | Consecutive failures that start a cooldown |

Rejections raised by pyresilience itself (`CircuitOpenError`, `RateLimitExceededError`, `BulkheadFullError`) always start the chain, whatever `fallback_on` says. Errors listed in `RetryConfig.ignore_on` never do: they are raised immediately.

## Usage

### Static Value or Handler

```python
from pyresilience import resilient, FallbackConfig

@resilient(fallback=FallbackConfig(handler={"items": [], "stale": True}))
def list_items() -> dict:
    return requests.get("https://api.example.com/items").json()

@resilient(fallback=FallbackConfig(handler=lambda exc: {"error": str(exc)}))
def get_profile(user_id: str) -> dict:
    return requests.get(f"https://api.example.com/users/{user_id}").json()
```

### Alternatives: Another Provider With the Same Arguments

An alternative receives exactly what the decorated function received, so it can run the same request somewhere else:

```python
from pyresilience import resilient, FallbackConfig, RetryConfig

def ask_backup_model(prompt: str, *, max_tokens: int = 256) -> str:
    return backup_client.complete(prompt, max_tokens=max_tokens)

def ask_small_model(prompt: str, *, max_tokens: int = 256) -> str:
    return small_client.complete(prompt, max_tokens=max_tokens)

@resilient(
    retry=RetryConfig(max_attempts=2),
    fallback=FallbackConfig(
        alternatives=[ask_backup_model, ask_small_model],
        handler="Sorry, no model is available right now.",
    ),
)
def ask(prompt: str, *, max_tokens: int = 256) -> str:
    return primary_client.complete(prompt, max_tokens=max_tokens)
```

`ask("hello", max_tokens=100)` retries the primary twice, then calls `ask_backup_model("hello", max_tokens=100)`, then `ask_small_model(...)`, and finally returns the handler value.

An alternative can be decorated with `@resilient` itself, which gives it its own retry, timeout or circuit breaker.

### Cooldown: Stop Calling a Provider That Is Down

```python
@resilient(
    fallback=FallbackConfig(
        alternatives=[ask_backup_model],
        cooldown=30.0,            # skip a failing target for 30 seconds
        cooldown_threshold=3,     # after 3 failures in a row
    ),
)
def ask(prompt: str) -> str:
    return primary_client.complete(prompt)
```

- Each target (the decorated function and every alternative) has its own failure streak and cooldown.
- A success resets the streak. When a cooldown ends, the streak starts again from zero.
- While the decorated function cools down, calls go straight to the alternatives and the handler. The handler then receives the error that started the cooldown.
- A cooldown never fails a call by itself. If every alternative is cooling down too and there is no handler, the decorated function is called anyway.

Cooldown also works with a handler alone:

```python
@resilient(fallback=FallbackConfig(handler=load_cached_answer, cooldown=10.0))
def fetch_live(key: str) -> dict: ...
```

### Async

Use async alternatives and handlers with async functions (sync ones are accepted too). A sync function needs sync alternatives: an alternative that returns an awaitable raises `TypeError`.

```python
async def ask_backup_model(prompt: str) -> str:
    return await backup_client.complete(prompt)

@resilient(fallback=FallbackConfig(alternatives=[ask_backup_model], cooldown=30.0))
async def ask(prompt: str) -> str:
    return await primary_client.complete(prompt)
```

### Cooldown or Circuit Breaker?

| | Cooldown | Circuit breaker |
|---|---|---|
| **Scope** | One target of the fallback chain | The whole decorated call |
| **While active** | Target is skipped, the chain continues | Call is rejected with `CircuitOpenError` (the fallback chain still runs) |
| **Recovery** | Target is tried again after the cooldown | Half-open probes, success threshold |
| **Use when** | You have somewhere else to send the call | You want to stop calling a dependency and observe its recovery |

They combine: an open circuit on the primary routes calls to the alternatives.

## Events

| Event | When |
|-------|------|
| `EventType.FALLBACK_USED` | An alternative or the handler supplied the result. `detail` is `"alternative <name>"` for alternatives |
| `EventType.COOLDOWN` | A target entered cooldown. `detail` is `"<name> cooling down for <seconds>s"` |

With alternatives or a cooldown configured, a failing call emits `FAILURE` for the decorated function before `FALLBACK_USED`.

## Limits

- A stream that already started is not covered: alternatives run only when the call itself fails. Combine with `TimeoutConfig.stream_idle_seconds` to bound a stalled stream.
- Results of alternatives are not written to the result cache.
- Cooldown state lives in the process. Under a [registry](../advanced/registry.md) name it is shared by sync and async functions.
