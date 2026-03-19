# Changelog

## v0.3.1 (2026-03-19)

### New Features
- **Context propagation**: `resilience_context` ContextVar carries request-scoped metadata (trace ID, user ID, etc.) into every `ResilienceEvent.context` field automatically
- **Per-attempt timeout**: `TimeoutConfig(per_attempt=False)` enforces a single deadline across all retry attempts instead of resetting per attempt
- **Retry budget**: `RetryBudgetConfig(max_retries=100, refill_rate=10)` provides a shared token pool that prevents cascading retries across decorated functions
- **Health check**: `health_check(registry)` returns a dict summarizing circuit breaker states, in-flight calls, and rate limiter availability for all registered functions
- **OpenTelemetry listener**: `OpenTelemetryListener` emits spans and attributes for each resilience event, integrating with the OpenTelemetry SDK
- **Prometheus listener**: `PrometheusListener` exports counters and histograms to Prometheus via the official client library
- **Graceful shutdown**: `shutdown()` drains in-flight calls and releases thread pool resources cleanly
- **Event duration tracking**: `ResilienceEvent.duration` field populated on SUCCESS events for observability integrations
- **Production/Stable classifier**: PyPI classifier bumped to `Development Status :: 5 - Production/Stable`

### Bug Fixes
- **AsyncResultCache.put() race condition**: Fixed unsafe read of `_store.keys()` without holding the lock; `ResultCache.put()` now returns evicted keys directly
- **Prometheus histogram unused**: `PrometheusListener` now observes call duration via `_duration_histogram` on SUCCESS events
- **Cache lock memory leak**: Per-key locks in cache stampede prevention are now evicted alongside their cache entries, preventing unbounded lock accumulation
- **`asyncio.iscoroutinefunction` deprecation**: Replaced remaining usage with `inspect.iscoroutinefunction` for Python 3.14+ compatibility
- **`install_uvloop` deprecated API**: Switched from `uvloop.install()` to `uvloop.EventLoopPolicy()` to silence deprecation warnings
- **Registry executor exposure**: `ResilienceRegistry` now exposes executors via `get_executor(name)` for runtime introspection without private attribute access

### Performance
- Zero overhead from new features when no listeners attached
- Duration timing gated behind `if has_listeners:` — zero cost on hot path
- Lazy in-flight tracking: counter and lock only allocated when `enable_in_flight_tracking()` is called
- Benchmark results (Apple Silicon): 0.64μs decorator overhead, 223,934 ops/sec throughput, 14.4x faster than tenacity async

### Tests
- 365 tests (up from 289), 96% branch coverage
- New tests for context propagation, per-attempt timeout, retry budget, health check, OpenTelemetry listener, Prometheus listener, graceful shutdown, event duration, and async cache race fix

---

## v0.3.0 (2026-03-19)

### New Features
- **Circuit breaker manual control**: Added `reset()`, `force_open()`, `force_close()` methods to `CircuitBreaker` for operational needs (maintenance windows, graceful degradation)
- **Async fallback handlers**: `FallbackConfig.handler` can now be an async function when used with async decorated functions. Detected via `asyncio.iscoroutinefunction`
- **Cache stampede prevention**: Per-key locking with double-check pattern prevents thundering herd on cache miss. Only one thread/coroutine computes per cache key; others wait for the result
- **Sync timeout thread cancellation**: Uses `ctypes.pythonapi.PyThreadState_SetAsyncExc` for best-effort thread interruption on CPython. Exception chain preserved (`from exc`). Will not interrupt blocking C extensions
- **AsyncBulkhead loop safety**: Detects event loop changes and recreates semaphore automatically. Safe across multiple `asyncio.run()` calls

### Bug Fixes
- **FallbackConfig default constructor**: `FallbackConfig()` now works without arguments. When `handler=None`, `fallback_on` is auto-cleared to `()` to prevent silently returning `None` on exceptions
- **Circuit breaker race condition**: Removed lock-free fast path in `allow_request()` — always acquires lock. Safe for free-threaded Python 3.13+ (`--disable-gil`)
- **Circuit breaker re-checked between retries**: CB state is verified before each retry attempt. If the CB opened (from other threads), retries stop immediately with `CircuitOpenError`
- **MetricsCollector async collision**: Replaced `threading.get_ident()` with `contextvars.ContextVar` — concurrent async coroutines no longer corrupt latency tracking
- **Jitter zero-delay floor**: Jitter now has a 10% minimum floor (`max(base * 0.1, random() * delay)`), preventing zero-delay retry storms
- **Timeout exception chaining**: `ResilienceTimeoutError` now chains via `from exc` instead of `from None`, preserving original traceback for debugging
- **`strict_policy` docstring**: Corrected from "1 retry (2 total attempts)" to "No retries (1 total attempt)"
- **Django `max_retries` → `max_attempts`**: Config key renamed for consistency with `RetryConfig`. Old key still works with `DeprecationWarning`
- **mypy clean**: Fixed uvloop/orjson import errors via `pyproject.toml` overrides. mypy now passes with zero errors

### Improvements
- **Bulkhead released during retry sleep**: Bulkhead slot is now released during retry backoff and reacquired before the next attempt, preventing slot starvation
- **Cooperative timeout cancel**: Sync timeout uses `threading.Event` for cancel signaling instead of no-op `future.cancel()`
- **Listener errors logged**: Broken listeners now emit `logging.warning()` instead of being silently swallowed
- **Bounded MetricsCollector memory**: Latency history bounded to 10,000 entries via `collections.deque(maxlen=10000)`
- **Larger default thread pool**: Sync timeout pool increased from 4 to `min(32, cpu_count + 4)` workers
- **Decorator introspection**: Wrapped functions now expose `_executor` attribute for runtime access to circuit breaker, cache, etc.
- **Config validation**: `FallbackConfig` and `CacheConfig` now validate inputs in `__post_init__`
- **`BulkheadFullError` import cleanup**: Now imported directly from `_exceptions` module

### Performance
- Decorator overhead: 0.73us (tenacity 7.89us = 10.8x faster)
- Throughput: 152K-244K ops/sec (tenacity 67K = 2.3-3.6x faster)
- Async: 0.69us (tenacity 12.14us = 17.6x faster)
- Memory: 1,208KB per 1,000 decorated functions (tenacity 2,181KB = 45% less)
- Circuit breaker: 0.95us (pybreaker 0.64us — trade-off for full thread safety)
- Cache hot path: 0.58us
- Fallback: 0.68us
- Bulkhead: 0.66us

### Tests
- 276 tests (up from 232), 98% branch coverage
- Removed `test_coverage.py` — all tests distributed to relevant feature test files
- Added config validation tests for all dataclasses

---

## v0.2.0 (2026-03-19)

### New Features
- **Sliding window circuit breaker** — Count-based sliding window replaces fragile consecutive failure counting. Configure with `sliding_window_size` parameter.
- **Failure rate % threshold** — `failure_rate_threshold=0.5` trips at 50% failure rate within the sliding window, matching production circuit breaker behavior.
- **Retry on result predicate** — `retry_on_result=lambda r: r.get("status") == 429` retries based on return values without requiring exceptions.
- **Slow call detection** — Calls exceeding `slow_call_duration` count toward circuit opening via `slow_call_rate_threshold`. Detects slow degradation without errors.
- **Circuit breaker metrics** — `.metrics` property exposes real-time failure_rate, slow_call_rate, total_calls.
- **`SLOW_CALL` event type** — New event emitted when a call exceeds the slow call duration threshold.

### Performance
- `__slots__` on all hot-path classes (executor, circuit breaker, cache, rate limiter, logger)
- Cached module-level locals for `time.monotonic`, `random.random`, enum members
- Inlined `isinstance()` checks, guarded event emission with `has_listeners` bool
- Pre-computed rate (tokens/sec) in rate limiter
- Lock-free circuit breaker reads for CLOSED state (CPython GIL atomic reference)
- `atexit` + `weakref` thread pool lifecycle management
- Tuple-based cache keys (fast path for hashable args)
- Integer nanosecond arithmetic in rate limiter (avoids float overhead)
- Fast path: skip retry loop when no retry/timeout/slow-call configured
- Atomic counter with lock for non-waiting bulkhead mode
- Decorator overhead: 0.55us (13x faster than tenacity at 7.02us)
- Circuit breaker overhead: 0.99us (was 1.25us)
- All 7 patterns combined: 0.66us (was 0.94us)
- Memory: 1,104KB per 1,000 decorated functions (51% less than tenacity)
- Throughput: 242K ops/sec (2.8x tenacity)

### Code Quality
- **Error hierarchy**: `ResilienceError` base class with `CircuitOpenError`, `BulkheadFullError`, `RateLimitExceededError`, `ResilienceTimeoutError` subclasses
- **Input validation**: `__post_init__` validation on all config dataclasses
- **Preset naming**: `max_retries` → `max_attempts` for consistency with `RetryConfig`
- Bare `@resilient` is now a passthrough (no auto-retry)

### Fixes
- Replaced deprecated `asyncio.iscoroutinefunction` with `inspect.iscoroutinefunction`
- `BaseException` → `Exception` in retry loops (no longer catches KeyboardInterrupt/SystemExit)
- Full jitter (`random.random() * delay`) for better thundering-herd protection
- Configurable thread pool size for sync timeouts (`TimeoutConfig(pool_size=N)`)
- Thread pool lifecycle management with `atexit` cleanup (prevents resource leaks)
- Cache key collisions fixed with type-qualified string keys for unhashable args

### Tests
- 232 tests (up from 176), 98.56% branch coverage
- New: `test_sliding_window.py` (15 tests), `test_retry_on_result.py` (11 tests)
- Expanded `test_coverage.py` with edge case tests for executor, contrib, presets, and logging modules

---

## v0.1.0 (2026-03-19)

Initial release with all 7 resilience patterns.

### Core Modules
- **CircuitBreaker** — State machine (CLOSED/OPEN/HALF_OPEN) with configurable thresholds
- **Retry** — Exponential backoff with jitter, configurable exception types
- **Bulkhead** — Semaphore-based concurrency limiting (sync + async)
- **TimeLimiter** — Per-call timeouts (thread-based sync, asyncio.wait_for async)
- **RateLimiter** — Token bucket algorithm for call rate limiting
- **Cache** — LRU result cache with TTL and hit/miss statistics

### Infrastructure
- **Registry** — Centralized management of named resilience instances with shared state
- **Presets** — `http_policy()`, `db_policy()`, `queue_policy()`, `strict_policy()`
- **Observability** — `JsonEventLogger`, `MetricsCollector`, unified event system
- **Performance** — Optional uvloop + orjson backends via `pip install pyresilience[fast]`

### Quality
- Zero runtime dependencies
- Full async support (auto-detects sync vs async)
- Strict mypy type checking
- 157 tests, 98% coverage
- Python 3.9 — 3.14 support
- Linux, macOS, Windows CI
